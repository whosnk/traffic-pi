from simtrend_app.edge_metrics import collect_edge_metrics, compare_edge_metrics, write_edge_data_additional


def test_write_edge_data_additional_uses_full_simulation_period(tmp_path) -> None:
    additional = tmp_path / "edge_metrics.add.xml"
    output = tmp_path / "edge_metrics.xml"

    write_edge_data_additional(additional, output, 600)

    text = additional.read_text(encoding="utf-8")
    assert 'period="600"' in text
    assert 'excludeEmpty="true"' in text
    assert str(output.resolve()) in text


def test_collect_and_compare_edge_metrics(tmp_path) -> None:
    reference_file = tmp_path / "reference.xml"
    adjusted_file = tmp_path / "adjusted.xml"
    reference_file.write_text(
        """<meandata><interval begin="0" end="600">
        <edge id="road_a" sampledSeconds="100" entered="10" left="9" speed="12" density="3" waitingTime="20" timeLoss="30"/>
        <edge id="road_b" sampledSeconds="50" entered="5" left="5" speed="10" density="2" waitingTime="5" timeLoss="10"/>
        </interval></meandata>""",
        encoding="utf-8",
    )
    adjusted_file.write_text(
        """<meandata><interval begin="0" end="600">
        <edge id="road_a" sampledSeconds="180" entered="16" left="13" speed="8" density="7" waitingTime="70" timeLoss="120"/>
        <edge id="road_b" sampledSeconds="50" entered="5" left="5" speed="10" density="2" waitingTime="5" timeLoss="10"/>
        </interval></meandata>""",
        encoding="utf-8",
    )

    reference = collect_edge_metrics(reference_file)
    adjusted = collect_edge_metrics(adjusted_file)
    impacts = compare_edge_metrics(reference, adjusted)

    assert reference["road_a"]["vehicle_entered"] == 10
    assert adjusted["road_a"]["mean_speed_mps"] == 8
    assert impacts[0]["edge_id"] == "road_a"
    assert impacts[0]["vehicle_entered_delta"] == 6
    assert impacts[0]["mean_speed_delta_mps"] == -4
    assert impacts[0]["impact_level"] == "高"
    assert impacts[-1]["impact_score"] == 0
