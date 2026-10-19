from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuickQueryAction:
    key: str
    label: str
    prompt: str
    enabled: bool = True
    help_text: str = ""


def build_quick_query_actions(selection: dict | None = None) -> tuple[QuickQueryAction, ...]:
    selection = selection or {}
    has_selection = bool(selection.get("edge_id") or selection.get("lane_id"))
    object_type = str(selection.get("object_type") or "road")

    if object_type == "pickup_zone":
        object_prompt = "查询当前选择的上客区详细信息"
    elif object_type in {"lane", "intersection_lane"}:
        object_prompt = "查询当前选择的车道详细信息和连接关系"
    else:
        object_prompt = "查询当前选择的道路详细信息和连接关系"

    signal_scope_prompt = (
        "查询当前选择的道路或车道由哪个信号控制器管理"
        if has_selection
        else "查询当前场景有哪些信号控制器？"
    )
    phase_prompt = "查询当前选择的道路或车道由哪个信号控制器管理，并显示当前相位配置"
    selection_help = "请先在主页面的空间对象选择器中点选道路、车道或上客区。"

    return (
        QuickQueryAction(
            key="scene_overview",
            label="场景概况",
            prompt="查询当前场景概况，包括路口、道路、车道、信号控制器和上客区数量",
        ),
        QuickQueryAction(
            key="selected_object",
            label="已选对象详情",
            prompt=object_prompt,
            enabled=has_selection,
            help_text=selection_help,
        ),
        QuickQueryAction(
            key="signal_scope",
            label="信号控制范围",
            prompt=signal_scope_prompt,
        ),
        QuickQueryAction(
            key="signal_phases",
            label="当前相位方案",
            prompt=phase_prompt,
            enabled=has_selection,
            help_text="请先在地图上选择一条受信号控制的道路或车道。",
        ),
    )
