from __future__ import annotations

import subprocess
from pathlib import Path

from common import find_sumo_binary, project_root


def main() -> None:
    root = project_root()
    nod = root / "network" / "intersection.nod.xml"
    edg = root / "network" / "intersection.edg.xml"
    out = root / "network" / "intersection.net.xml"

    cmd = [
        find_sumo_binary("netconvert"),
        "--node-files",
        str(nod),
        "--edge-files",
        str(edg),
        "--output-file",
        str(out),
        "--no-turnarounds",
        "true",
    ]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"[OK] generated {out}")


if __name__ == "__main__":
    main()
