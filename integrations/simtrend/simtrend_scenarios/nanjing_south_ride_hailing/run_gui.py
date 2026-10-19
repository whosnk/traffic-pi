from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    scenario_dir = Path(__file__).resolve().parent
    subprocess.run(
        [
            "sumo-gui",
            "-c",
            str(scenario_dir / "cfg" / "intersection.sumocfg"),
            "--gui-settings-file",
            str(scenario_dir / "viewsettings.xml"),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
