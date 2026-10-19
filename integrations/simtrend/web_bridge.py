"""Private JSON bridge invoked by Traffic Pi, never a public shell endpoint."""
import json
import os
from pathlib import Path
import sys

os.chdir(Path(__file__).resolve().parent)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from simtrend_app.integration import bridge, run_job

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--job":
        run_job(sys.argv[2])
    else:
        try:
            result = bridge(json.load(sys.stdin))
        except Exception as exc:
            result = {"ok": False, "status": "error", "message": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
