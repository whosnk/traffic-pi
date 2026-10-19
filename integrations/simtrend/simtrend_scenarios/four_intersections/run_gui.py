from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.common import find_sumo_binary


def main() -> None:
    root = Path(__file__).resolve().parent
    cfg = root / "cfg" / "intersection.sumocfg"
    net = root / "network" / "intersection.net.xml"

    if not net.exists():
        raise FileNotFoundError(
            "请先运行: python scripts/build_net.py 生成 intersection.net.xml"
        )

    cmd = [find_sumo_binary("sumo-gui"), "-c", str(cfg)]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
