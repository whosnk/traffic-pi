from pathlib import Path

from simtrend_app.config import Settings
from simtrend_app.parameterized_signal import evaluate_signal_plan


def test_invalid_signal_parameters_do_not_remove_previous_success_artifact(tmp_path) -> None:
    network_dir = tmp_path / "network"
    network_dir.mkdir(parents=True)
    (network_dir / "intersection.net.xml").write_text(
        """<net><tlLogic id="j0" type="static" programID="0">
        <phase duration="40" state="GG"/><phase duration="3" state="yy"/>
        <phase duration="40" state="GG"/><phase duration="3" state="yy"/>
        </tlLogic></net>""",
        encoding="utf-8",
    )
    for relative_path in (
        "cfg/intersection.sumocfg",
        "routes/intersection.rou.xml",
        "scripts/build_net.py",
        "run_gui.py",
        "train.py",
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    previous = tmp_path / "outputs/agent_runs/parameterized_latest/json/parameterized_result.json"
    previous.parent.mkdir(parents=True)
    previous.write_text('{"run":{"ok":true}}', encoding="utf-8")
    settings = Settings("", "", "", str(tmp_path), False, False, False, 1800)

    result = evaluate_signal_plan(settings, "j0", [40, 1, 40, 3])

    assert not result.ok
    assert result.data["error"]["code"] == "INVALID_SIGNAL_PARAMETERS"
    assert previous.exists()
