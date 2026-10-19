from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape


def write_edge_data_additional(
    additional_file: str | Path,
    output_file: str | Path,
    duration_seconds: int,
) -> None:
    target = Path(additional_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    output_path = escape(str(Path(output_file).resolve()), {'"': "&quot;"})
    target.write_text(
        "\n".join(
            [
                "<additional>",
                (
                    '    <edgeData id="simtrend_edge_metrics" '
                    f'file="{output_path}" period="{max(int(duration_seconds), 1)}" '
                    'excludeEmpty="true" withInternal="false"/>'
                ),
                "</additional>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def collect_edge_metrics(path: str | Path) -> dict[str, dict]:
    root = ET.parse(path).getroot()
    accumulators: dict[str, dict] = {}
    for interval in root.findall("interval"):
        for edge in interval.findall("edge"):
            edge_id = edge.get("id", "")
            if not edge_id or edge_id.startswith(":"):
                continue
            sampled_seconds = _float(edge.get("sampledSeconds"))
            row = accumulators.setdefault(
                edge_id,
                {
                    "edge_id": edge_id,
                    "sampled_seconds": 0.0,
                    "vehicle_entered": 0.0,
                    "vehicle_left": 0.0,
                    "waiting_time_s": 0.0,
                    "time_loss_s": 0.0,
                    "speed_weighted": 0.0,
                    "density_weighted": 0.0,
                    "weight": 0.0,
                },
            )
            weight = max(sampled_seconds, 1.0)
            row["sampled_seconds"] += sampled_seconds
            row["vehicle_entered"] += _float(edge.get("entered"), edge.get("nVehEntered"))
            row["vehicle_left"] += _float(edge.get("left"), edge.get("nVehLeft"))
            row["waiting_time_s"] += _float(edge.get("waitingTime"))
            row["time_loss_s"] += _float(edge.get("timeLoss"))
            row["speed_weighted"] += _float(edge.get("speed"), edge.get("meanSpeed")) * weight
            row["density_weighted"] += _float(edge.get("density")) * weight
            row["weight"] += weight

    metrics: dict[str, dict] = {}
    for edge_id, row in accumulators.items():
        weight = max(float(row["weight"]), 1.0)
        metrics[edge_id] = {
            "edge_id": edge_id,
            "vehicle_entered": round(float(row["vehicle_entered"]), 3),
            "vehicle_left": round(float(row["vehicle_left"]), 3),
            "sampled_seconds": round(float(row["sampled_seconds"]), 3),
            "mean_speed_mps": round(float(row["speed_weighted"]) / weight, 3),
            "density_veh_per_km": round(float(row["density_weighted"]) / weight, 3),
            "waiting_time_s": round(float(row["waiting_time_s"]), 3),
            "time_loss_s": round(float(row["time_loss_s"]), 3),
        }
    return metrics


def compare_edge_metrics(reference: dict[str, dict], adjusted: dict[str, dict]) -> list[dict]:
    rows = []
    for edge_id in sorted(set(reference) | set(adjusted)):
        before = reference.get(edge_id, _empty_edge_metrics(edge_id))
        after = adjusted.get(edge_id, _empty_edge_metrics(edge_id))
        before_entered = float(before.get("vehicle_entered", 0.0))
        after_entered = float(after.get("vehicle_entered", 0.0))
        before_speed = float(before.get("mean_speed_mps", 0.0))
        after_speed = float(after.get("mean_speed_mps", 0.0))
        before_wait = float(before.get("waiting_time_s", 0.0))
        after_wait = float(after.get("waiting_time_s", 0.0))
        before_loss = float(before.get("time_loss_s", 0.0))
        after_loss = float(after.get("time_loss_s", 0.0))
        rows.append(
            {
                "edge_id": edge_id,
                "reference_vehicle_entered": before_entered,
                "adjusted_vehicle_entered": after_entered,
                "vehicle_entered_delta": round(after_entered - before_entered, 3),
                "vehicle_entered_change_ratio": round(
                    (after_entered - before_entered) / max(before_entered, 1.0), 4
                ),
                "reference_mean_speed_mps": before_speed,
                "adjusted_mean_speed_mps": after_speed,
                "mean_speed_delta_mps": round(after_speed - before_speed, 3),
                "reference_waiting_time_s": before_wait,
                "adjusted_waiting_time_s": after_wait,
                "waiting_time_delta_s": round(after_wait - before_wait, 3),
                "reference_time_loss_s": before_loss,
                "adjusted_time_loss_s": after_loss,
                "time_loss_delta_s": round(after_loss - before_loss, 3),
                "adjusted_density_veh_per_km": float(after.get("density_veh_per_km", 0.0)),
            }
        )

    _assign_impact_scores(rows)
    return sorted(
        rows,
        key=lambda row: (
            float(row["impact_score"]),
            float(row["vehicle_entered_delta"]),
            float(row["time_loss_delta_s"]),
        ),
        reverse=True,
    )


def _assign_impact_scores(rows: list[dict]) -> None:
    if not rows:
        return
    flow_values = [max(float(row["vehicle_entered_change_ratio"]), 0.0) for row in rows]
    speed_values = [
        max(-float(row["mean_speed_delta_mps"]), 0.0)
        / max(float(row["reference_mean_speed_mps"]), 1.0)
        for row in rows
    ]
    loss_values = [
        max(float(row["time_loss_delta_s"]), 0.0)
        / max(float(row["reference_time_loss_s"]), 1.0)
        for row in rows
    ]
    max_flow = max(flow_values, default=0.0) or 1.0
    max_speed = max(speed_values, default=0.0) or 1.0
    max_loss = max(loss_values, default=0.0) or 1.0
    for row, flow, speed, loss in zip(rows, flow_values, speed_values, loss_values):
        score = 100 * (0.45 * flow / max_flow + 0.30 * speed / max_speed + 0.25 * loss / max_loss)
        row["impact_score"] = round(score, 1)
        row["impact_level"] = "高" if score >= 60 else "中" if score >= 30 else "低"


def _empty_edge_metrics(edge_id: str) -> dict:
    return {
        "edge_id": edge_id,
        "vehicle_entered": 0.0,
        "vehicle_left": 0.0,
        "sampled_seconds": 0.0,
        "mean_speed_mps": 0.0,
        "density_veh_per_km": 0.0,
        "waiting_time_s": 0.0,
        "time_loss_s": 0.0,
    }


def _float(primary: str | None, fallback: str | None = None) -> float:
    value = primary if primary is not None else fallback
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
