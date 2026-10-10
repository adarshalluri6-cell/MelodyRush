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
pf = {f.name for f in dataclasses.fields(GenerationParams)}
print("GenerationParams fields:", sorted(pf), flush=True)
want = dict(caption=job["caption"], lyrics=job["lyrics"], bpm=job.get("bpm"), duration=job["duration"],
            vocal_language="en", instrumental=False, thinking=False, use_cot_caption=False,
            use_cot_language=False, use_cot_metas=False, use_cot_lyrics=False)
params = GenerationParams(**{k: v for k, v in want.items() if k in pf and v is not None})
cf = {f.name for f in dataclasses.fields(GenerationConfig)}
config = GenerationConfig(**{k: v for k, v in dict(batch_size=1, audio_format="flac").items() if k in cf})
os.makedirs("/tmp/ace/out", exist_ok=True)
result = generate_music(dit, llm, params, config, save_dir="/tmp/ace/out")
print("success:", getattr(result, "success", None), getattr(result, "error", None), flush=True)
'''


def newest_audio():
    files = [f for ext in ("flac", "mp3", "wav") for f in glob.glob(f"/tmp/ace/out/**/*.{ext}", recursive=True)]
    return max(files, key=lambda f: Path(f).stat().st_mtime) if files else None


def main():
    meta = {"run_id": JOB["run_id"], "ok": False}
    mp3 = OUT / "song.mp3"
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
        raw = newest_audio()
        if not raw:
            raise RuntimeError("no audio file was produced")
        try:
            sh(f'ffmpeg -y -loglevel error -i "{raw}" -b:a 192k "{mp3}"')
        except Exception:
            mp3 = OUT / ("song" + Path(raw).suffix)
            shutil.copy(raw, mp3)
        meta.update(ok=True, audio=mp3.name)
    except Exception:
        meta["error"] = traceback.format_exc()[-1500:]
        traceback.print_exc()
    segments = []
    if meta["ok"]:
        try:
            sh("pip install -q faster-whisper")
            from faster_whisper import WhisperModel
            model = WhisperModel("small.en", device="cpu", compute_type="int8")
            segs, _ = model.transcribe(str(mp3), language="en", condition_on_previous_text=False)
            segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
        except Exception:
            traceback.print_exc()
    (OUT / "segments.json").write_text(json.dumps(segments))
    (OUT / "meta.json").write_text(json.dumps(meta))
    if not meta["ok"]:
        raise SystemExit(1)


main()
