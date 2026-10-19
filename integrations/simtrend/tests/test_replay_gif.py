from pathlib import Path

from PIL import Image

from simtrend_app.tool_scripts.render_replay_gif import render_replay_gif


def test_render_replay_gif_from_tiny_fcd(tmp_path: Path) -> None:
    net_file = tmp_path / "tiny.net.xml"
    fcd_file = tmp_path / "tiny.fcd.xml"
    gif_file = tmp_path / "replay.gif"

    net_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<net>
  <edge id="e1" from="n1" to="n2">
    <lane id="e1_0" index="0" speed="13.9" length="100" shape="0,0 100,0"/>
  </edge>
</net>
""",
        encoding="utf-8",
    )
    fcd_file.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<fcd-export>
  <timestep time="0.00"><vehicle id="veh0" x="0" y="0" angle="90" speed="3"/></timestep>
  <timestep time="2.00"><vehicle id="veh0" x="30" y="0" angle="90" speed="5"/></timestep>
  <timestep time="4.00"><vehicle id="veh0" x="70" y="0" angle="90" speed="0"/></timestep>
</fcd-export>
""",
        encoding="utf-8",
    )

    result = render_replay_gif(
        net_file=net_file,
        fcd_file=fcd_file,
        output_file=gif_file,
        duration_seconds=6,
        width=320,
        height=240,
    )

    assert result["ok"]
    assert gif_file.exists()
    with Image.open(gif_file) as image:
        assert image.is_animated
        assert image.n_frames >= 2
