# This file runs ON KAGGLE (free GPU). The GitHub pipeline fills in the job below and pushes it.
import base64
import glob
import json
import shutil
import subprocess
import traceback
from pathlib import Path

JOB = json.loads(base64.b64decode("__JOB_B64__").decode())
OUT = Path("/kaggle/working")
REPO = Path("/tmp/ace/repo")


def sh(cmd, cwd=None):
    print(">>", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {cmd}")


INNER = r'''
import dataclasses, json, os
import torch
from huggingface_hub import snapshot_download
job = json.load(open("job.json"))
root = os.getcwd()
ckpt = os.path.join(root, "checkpoints")
print("downloading models...", flush=True)
snapshot_download("ACE-Step/Ace-Step1.5", local_dir=ckpt)
from acestep.handler import AceStepHandler
from acestep.llm_inference import LLMHandler
from acestep.inference import GenerationParams, GenerationConfig, generate_music
dit, llm = AceStepHandler(), LLMHandler()
dit.initialize_service(project_root=root, config_path="acestep-v15-turbo", device="cuda")
# Kaggle GPUs (T4/P100) break in float16 when lyrics are used. Force full precision.
for name, val in list(vars(dit).items()):
    if isinstance(val, torch.nn.Module):
        val.float()
        print("float32:", name, flush=True)
    elif torch.is_tensor(val) and val.is_floating_point():
        setattr(dit, name, val.float())
dit.dtype = torch.float32
print("dtype now:", dit.dtype, "gpu:", torch.cuda.get_device_name(0), flush=True)
import time, traceback
songs = job.get("songs") or [dict(caption=job["caption"], lyrics=job["lyrics"], bpm=job.get("bpm"), duration=job["duration"])]
pf = {f.name for f in dataclasses.fields(GenerationParams)}
cf = {f.name for f in dataclasses.fields(GenerationConfig)}
config = GenerationConfig(**{k: v for k, v in dict(batch_size=1, audio_format="flac").items() if k in cf})
t0 = time.time()
for i, s in enumerate(songs):
    if time.time() - t0 > job.get("budget_min", 170) * 60:
        print("time budget reached, stopping before song", i + 1, flush=True)
        break
    try:
        outdir = "/tmp/ace/out/%02d" % i
        os.makedirs(outdir, exist_ok=True)
        want = dict(caption=s["caption"], lyrics=s["lyrics"], bpm=s.get("bpm"), duration=s["duration"],
                    vocal_language="en", instrumental=False, thinking=False, use_cot_caption=False,
                    use_cot_language=False, use_cot_metas=False, use_cot_lyrics=False)
        params = GenerationParams(**{k: v for k, v in want.items() if k in pf and v is not None})
        result = generate_music(dit, llm, params, config, save_dir=outdir)
        print("song", i + 1, "of", len(songs), "success:", getattr(result, "success", None),
              getattr(result, "error", None), "elapsed", int(time.time() - t0), "s", flush=True)
    except Exception:
        traceback.print_exc()
    torch.cuda.empty_cache()
'''


WHISPER = r'''
import json, traceback
from faster_whisper import WhisperModel
songs = json.load(open("/tmp/ace/meta_songs.json"))
model = WhisperModel("small.en" if len(songs) == 1 else "base.en", device="cpu", compute_type="int8")
for sd in songs:
    try:
        segs, _ = model.transcribe("/kaggle/working/" + sd["file"], language="en", condition_on_previous_text=False)
        data = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
    except Exception:
        traceback.print_exc()
        data = []
    json.dump(data, open("/kaggle/working/segments_%02d.json" % sd["i"], "w"))
    print("lyrics timing done for song", sd["i"] + 1, "segments:", len(data), flush=True)
'''


def newest_audio(folder="/tmp/ace/out"):
    files = [f for ext in ("flac", "mp3", "wav") for f in glob.glob(f"{folder}/**/*.{ext}", recursive=True)]
    return max(files, key=lambda f: Path(f).stat().st_mtime) if files else None


def make_image():
    """High-quality portrait with Stable Diffusion XL (free GPU). Falls back silently if anything fails."""
    try:
        sh("pip install -q diffusers transformers accelerate safetensors")
        import numpy as np
        import torch
        from PIL import ImageFilter
        from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
        pipe = None
        for repo, kw in [("SG161222/RealVisXL_V5.0", {"variant": "fp16"}), ("SG161222/RealVisXL_V5.0", {}),
                         ("stabilityai/stable-diffusion-xl-base-1.0", {"variant": "fp16"})]:
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(repo, torch_dtype=torch.float16,
                                                                 use_safetensors=True, **kw)
                print("image model:", repo, flush=True)
                break
            except Exception:
                traceback.print_exc()
        if pipe is None:
            return
        pipe.to("cuda")
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
        neg = ("text, watermark, logo, signature, blurry, low quality, deformed face, extra fingers, bad hands, "
               "cartoon, 3d render, oversaturated, cropped head, multiple people")
        best, best_score = None, -1
        for i in range(3):
            gen = torch.Generator("cuda").manual_seed(JOB["seed"] + i)
            img = pipe(prompt=JOB["image_prompt"], negative_prompt=neg, width=1344, height=768,
                       num_inference_steps=32, guidance_scale=5.5, generator=gen).images[0]
            if np.asarray(img).std() < 4:  # black image = half-precision VAE problem
                pipe.upcast_vae()
                img = pipe(prompt=JOB["image_prompt"], negative_prompt=neg, width=1344, height=768,
                           num_inference_steps=32, guidance_scale=5.5, generator=gen).images[0]
            edges = np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32).mean()
            print(f"candidate {i + 1}: sharpness {edges:.1f}", flush=True)
            if edges > best_score:
                best, best_score = img, edges
        best.save(OUT / "singer.jpg", quality=96)
        if JOB.get("portrait_prompt"):
            best2, score2 = None, -1
            for i in range(2):
                gen = torch.Generator("cuda").manual_seed(JOB["seed"] + 10 + i)
                img = pipe(prompt=JOB["portrait_prompt"], negative_prompt=neg, width=768, height=1344,
                           num_inference_steps=32, guidance_scale=5.5, generator=gen).images[0]
                if np.asarray(img).std() < 4:
                    pipe.upcast_vae()
                    img = pipe(prompt=JOB["portrait_prompt"], negative_prompt=neg, width=768, height=1344,
                               num_inference_steps=32, guidance_scale=5.5, generator=gen).images[0]
                edges = np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32).mean()
                print(f"portrait candidate {i + 1}: sharpness {edges:.1f}", flush=True)
                if edges > score2:
                    best2, score2 = img, edges
            best2.save(OUT / "portrait.jpg", quality=96)
    except Exception:
        traceback.print_exc()


def main():
    meta = {"run_id": JOB["run_id"], "ok": False}
    n_songs = len(JOB.get("songs") or [1])
    try:
        sh("pip install -q uv huggingface_hub")
        sh(f"git clone --depth 1 https://github.com/ace-step/ACE-Step-1.5.git {REPO}")
        sh("uv sync", cwd=REPO)
        (REPO / "job.json").write_text(json.dumps(JOB))
        (REPO / "inner.py").write_text(INNER)
        patched = 0
        for f in (REPO / "acestep").rglob("*.py"):
            t = f.read_text(errors="ignore")
            if "self.dtype = torch.float16" in t:
                f.write_text(t.replace("self.dtype = torch.float16", "self.dtype = torch.float32"))
                patched += 1
        print("patched files for float32:", patched, flush=True)
        sh("ACESTEP_DTYPE=float32 CUDA_VISIBLE_DEVICES=0 uv run python inner.py", cwd=REPO)
        done = []
        for i in range(n_songs):
            raw = newest_audio("/tmp/ace/out/%02d" % i)
            if not raw:
                continue
            mp3 = OUT / f"song_{i:02d}.mp3"
            try:
                sh(f'ffmpeg -y -loglevel error -i "{raw}" -b:a 192k "{mp3}"')
            except Exception:
                mp3 = OUT / (f"song_{i:02d}" + Path(raw).suffix)
                shutil.copy(raw, mp3)
            done.append({"i": i, "file": mp3.name})
        if not done:
            raise RuntimeError("no audio file was produced")
        meta.update(ok=True, songs=done, audio=done[0]["file"])
        print(f"songs finished: {len(done)} of {n_songs}", flush=True)
    except Exception:
        meta["error"] = traceback.format_exc()[-1500:]
        traceback.print_exc()
    if meta["ok"]:
        try:
            (REPO / "whisper_run.py").write_text(WHISPER)
            Path("/tmp/ace/meta_songs.json").write_text(json.dumps(meta["songs"]))
            sh("uv pip install faster-whisper", cwd=REPO)
            sh("uv run python whisper_run.py", cwd=REPO)
        except Exception:
            traceback.print_exc()
            print("WHISPER (uv environment) failed, trying the system Python", flush=True)
            try:
                sh("pip install -q faster-whisper")
                from faster_whisper import WhisperModel
                model = WhisperModel("small.en" if n_songs == 1 else "base.en", device="cpu", compute_type="int8")
                for sd in meta["songs"]:
                    try:
                        segs, _ = model.transcribe(str(OUT / sd["file"]), language="en", condition_on_previous_text=False)
                        data = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
                    except Exception:
                        traceback.print_exc()
                        data = []
                    (OUT / f"segments_{sd['i']:02d}.json").write_text(json.dumps(data))
                    print("lyrics timing done for song", sd["i"] + 1, "segments:", len(data), flush=True)
            except Exception:
                traceback.print_exc()
                print("WHISPER failed completely: lyrics will be spread evenly", flush=True)
        make_image()
    (OUT / "meta.json").write_text(json.dumps(meta))
    if not meta["ok"]:
        raise SystemExit(1)


main()
