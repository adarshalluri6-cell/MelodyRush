"""Runs the song generator on Kaggle's free GPU and downloads the result."""
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path


def log(m):
    print(m, flush=True)


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def generate_song(job, outdir, timeout_min=90):
    for k in ("KAGGLE_KEY", "KAGGLE_API_TOKEN"):  # ignore secrets that were left empty
        if not os.environ.get(k, "").strip():
            os.environ.pop(k, None)
    user = os.environ["KAGGLE_USERNAME"].strip()
    slug = "us-songs-gen"
    ref = f"{user}/{slug}"
    kdir = Path("kaggle_job")
    kdir.mkdir(exist_ok=True)
    code = Path("kernel_template.py").read_text()
    code = code.replace("__JOB_B64__", base64.b64encode(json.dumps(job).encode()).decode())
    (kdir / "gen.py").write_text(code)
    (kdir / "kernel-metadata.json").write_text(json.dumps({
        "id": ref, "title": slug, "code_file": "gen.py", "language": "python", "kernel_type": "script",
        "is_private": "true", "enable_gpu": "true", "enable_internet": "true",
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}))
    log("[kaggle] pushing job...")
    r = _run(["kaggle", "kernels", "push", "-p", str(kdir), "--accelerator", "NvidiaTeslaT4"])
    if r.returncode != 0:
        r = _run(["kaggle", "kernels", "push", "-p", str(kdir)])
    log(r.stdout.strip() + r.stderr.strip())
    if r.returncode != 0:
        raise RuntimeError("Kaggle push failed. Check KAGGLE_USERNAME / KAGGLE_KEY and phone verification.")
    time.sleep(60)
    t0, status = time.time(), ""
    while time.time() - t0 < timeout_min * 60:
        out = _run(["kaggle", "kernels", "status", ref]).stdout.lower()
        m = re.search(r'status "?([a-z._]+)"?', out)
        status = m.group(1) if m else out.strip()[:60]
        log(f"[kaggle] status: {status} ({int((time.time() - t0) / 60)} min)")
        if any(s in status for s in ("complete", "error", "cancel", "fail")):
            res = _download(ref, outdir, job["run_id"])
            if res:
                return res
            if "complete" in status:
                time.sleep(30)  # old results still showing, wait for the new run
                continue
            raise RuntimeError("Kaggle run ended with status: " + status)
        time.sleep(45)
    raise RuntimeError("Kaggle timed out")


def _download(ref, outdir, run_id):
    d = Path(outdir) / "kaggle_out"
    d.mkdir(parents=True, exist_ok=True)
    _run(["kaggle", "kernels", "output", ref, "-p", str(d)])
    mp = d / "meta.json"
    if not mp.exists():
        return None
    meta = json.loads(mp.read_text())
    if meta.get("run_id") != run_id:
        return None
    if not meta.get("ok"):
        for lg in d.glob("*.log"):
            log("---- Kaggle log (tail) ----\n" + lg.read_text(errors="ignore")[-3000:])
        raise RuntimeError("Song generation failed on Kaggle: " + str(meta.get("error", ""))[-800:])
    segs = json.loads((d / "segments.json").read_text()) if (d / "segments.json").exists() else []
    return {"audio": str(d / meta["audio"]), "segments": segs}
