"""Start all five pipeline services. Ctrl-C stops them all.

Run from backend/:  .venv/Scripts/python.exe pipeline/run_all.py
"""
import subprocess
import sys
import time
from pathlib import Path

# This pipeline was archived to docs/bikes/pipeline/. The app it reads and
# writes (cache.db, app/models.py, app/prompts) still lives in backend/.
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
# `pipeline.*` now resolves under docs/bikes/, not backend/ — the package moved
# with the archive but the import path did not follow it.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.common import PORTS  # noqa: E402

SERVICES = [
    ("coordinator", "pipeline.coordinator:app"),
    ("researcher_details", "pipeline.researcher_details:app"),
    ("researcher_photos", "pipeline.researcher_photos:app"),
    ("validator", "pipeline.validator:app"),
    ("db_saver", "pipeline.db_saver:app"),
]


def main() -> int:
    procs = []
    for name, target in SERVICES:
        port = PORTS[name]
        cmd = [sys.executable, "-m", "uvicorn", target, "--port", str(port), "--log-level", "warning"]
        print(f"starting {name:20} :{port}")
        procs.append((name, subprocess.Popen(cmd, cwd=str(ROOT))))
        time.sleep(0.4)

    print("\nall services up. Ctrl-C to stop.")
    # A dead child is restarted, NOT treated as a reason to stop everything.
    # The original behaviour tore down all five whenever one exited, so
    # restarting a single service to reload its config took the whole pipeline
    # down with it — twice — stranding every worker mid-round.
    try:
        while True:
            time.sleep(1)
            for i, (name, p) in enumerate(procs):
                if p.poll() is None:
                    continue
                port = PORTS[name]
                target = dict(SERVICES)[name]
                print(f"!! {name} exited with {p.returncode} — restarting on :{port}")
                cmd = [sys.executable, "-m", "uvicorn", target,
                       "--port", str(port), "--log-level", "warning"]
                procs[i] = (name, subprocess.Popen(cmd, cwd=str(ROOT)))
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping...")
        for _, p in procs:
            p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
