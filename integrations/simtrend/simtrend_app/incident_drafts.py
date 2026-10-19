"""Validate editable incident drafts without creating jobs or starting SUMO."""
from __future__ import annotations

from uuid import uuid4

FIELD_LABELS = {
    "edge_id": "事故道路", "lane_id": "事故车道", "incident_type": "事件类型",
    "incident_duration_minutes": "持续时间", "lane_closure_count": "封闭车道数",
    "objective": "优化目标", "duration_seconds": "仿真时长",
}
CHOICES = {
    "incident_type": ("追尾事故", "碰撞事故", "车辆抛锚"),
    "objective": ("优先缓解排队", "优先降低等待时间"),
}
BOUNDS = {"incident_duration_minutes": (1, 180), "lane_closure_count": (1, 8), "duration_seconds": (60, 3600)}


def prepare_incident_draft(scenario_id: str, fields: dict, base_revision: int = 0) -> dict:
    from simtrend_app.integration import map_data

    if not isinstance(fields, dict) or set(fields) - (set(FIELD_LABELS) | {"zone_id"}):
        raise ValueError("草案包含未知字段。")
    if type(base_revision) is not int or base_revision < 0:
        raise ValueError("草案版本无效。")
    data = map_data(scenario_id)
    values = {key: fields.get(key) for key in (*FIELD_LABELS, "zone_id")}
    for key, value in values.items():
        if value is None or value == "":
            values[key] = None
        elif key in BOUNDS:
            low, high = BOUNDS[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{FIELD_LABELS[key]}必须为 {low}-{high} 之间的整数。")
        elif not isinstance(value, str) or len(value) > 200:
            raise ValueError(f"{FIELD_LABELS.get(key, key)}无效。")
        elif key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f"{FIELD_LABELS[key]}不支持该选项。")
    edge = next((row for row in data["edges"] if row["edge_id"] == values["edge_id"]), None)
    if values["edge_id"] and not edge:
        raise ValueError("事故道路不属于当前场景。")
    lanes = data["lanes"].get(values["edge_id"], [])
    if values["lane_id"] and values["lane_id"] not in {row["lane_id"] for row in lanes}:
        raise ValueError("事故车道不属于所选道路，请先查询或在地图中选择。")
    if values["zone_id"] and not any(row["id"] == values["zone_id"] and row["edge_id"] == values["edge_id"] and row["lane_id"] == values["lane_id"] for row in data["zones"]):
        raise ValueError("上客区与事故道路、车道不匹配。")
    if edge and values["lane_closure_count"] and values["lane_closure_count"] > len(lanes):
        raise ValueError("封闭车道数不能超过道路车道数。")
    missing = [label for key, label in FIELD_LABELS.items() if values[key] is None]
    warnings = []
    minutes, seconds = values["incident_duration_minutes"], values["duration_seconds"]
    if minutes and seconds and minutes * 60 > seconds:
        warnings.append("事故持续时间超过仿真时长，本次仿真只能覆盖事故影响的一部分。")
    return {
        "ok": True, "type": "simtrend-task-draft", "status": "draft",
        "id": uuid4().hex, "base_revision": base_revision, "scenario_id": scenario_id,
        "scenario_name": data["name"], "simulation_started": False,
        "selection": {key: values[key] for key in ("edge_id", "lane_id", "zone_id") if values[key]},
        "location_name": edge["edge_name"] or edge["edge_id"] if edge else "",
        "lane_ids": [row["lane_id"] for row in lanes],
        "form": {key: values[key] for key in FIELD_LABELS if key not in {"edge_id", "lane_id"}},
        "missing_fields": missing, "warnings": warnings, "ready": not missing,
        "message": "事故任务草案已生成，请在任务面板补充或编辑，确认后运行。" if missing else "事故任务草案已生成，等待在任务面板确认运行。",
    }
