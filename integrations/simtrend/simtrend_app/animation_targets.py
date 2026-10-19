from __future__ import annotations

from typing import Any


PARAMETERIZED_KEYS = {
    "reference": "parameterized_reference",
    "candidate": "parameterized_candidate",
    "latest": "parameterized",
}

PARAMETERIZED_LABELS = {
    "reference": "参数化基准方案动画",
    "candidate": "参数化候选方案动画",
    "latest": "参数化信号方案动画",
}

ANIMATION_PRIORITY = (
    "optimized",
    "parameterized_candidate",
    "parameterized",
    "baseline",
    "parameterized_reference",
)


def parameterized_animation_targets(data: dict[str, Any]) -> dict[str, dict]:
    signal_plan = data.get("signal_plan") or {}
    slot = str(signal_plan.get("result_slot") or data.get("result_slot") or "latest")
    key = PARAMETERIZED_KEYS.get(slot, "parameterized")
    target = _animation_target(
        label=PARAMETERIZED_LABELS.get(slot, "参数化信号方案动画"),
        cfg_file=data.get("cfg_file"),
        animation=data.get("animation") or {},
        result_slot=slot,
    )
    return {key: target} if target else {}


def comparison_animation_targets(comparison: dict[str, Any]) -> dict[str, dict]:
    targets = {}
    for role, default_label in (("reference", "基准方案动画"), ("candidate", "候选方案动画")):
        source = comparison.get(role) or {}
        slot = str(source.get("selector") or role)
        key = PARAMETERIZED_KEYS.get(slot, f"comparison_{role}")
        label = PARAMETERIZED_LABELS.get(slot, default_label)
        target = _animation_target(
            label=label,
            cfg_file=source.get("cfg_file"),
            animation=source.get("animation") or {},
            result_slot=slot,
        )
        if target:
            targets[key] = target
    return targets


def merge_animation_targets(existing: dict | None, incoming: dict | None) -> dict:
    merged = dict(existing or {})
    for key, target in (incoming or {}).items():
        if target:
            merged[key] = dict(target)
    return merged


def ordered_animation_targets(targets: dict | None) -> list[tuple[str, dict]]:
    payload = dict(targets or {})
    order = {key: index for index, key in enumerate(ANIMATION_PRIORITY)}
    return sorted(
        payload.items(),
        key=lambda item: (order.get(item[0], len(order)), item[0]),
    )


def replay_charts(targets: dict | None) -> list[dict]:
    charts = []
    for _, target in ordered_animation_targets(targets):
        gif_file = target.get("gif_file")
        if not gif_file:
            continue
        charts.append(
            {
                "type": "replay_gif",
                "title": target.get("label", "仿真网页回放"),
                "caption": target.get("label", "仿真网页回放"),
                "gif_file": str(gif_file),
            }
        )
    return charts


def _animation_target(
    *,
    label: str,
    cfg_file: Any,
    animation: dict,
    result_slot: str,
) -> dict:
    gif_file = animation.get("gif_file") if animation.get("ok") else ""
    if not cfg_file and not gif_file:
        return {}
    target = {
        "label": label,
        "cfg_file": str(cfg_file or ""),
        "result_slot": result_slot,
        "replay_status": dict(animation),
    }
    if gif_file:
        target["gif_file"] = str(gif_file)
    return target
