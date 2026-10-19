from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StructuredTaskDraft:
    task_type: str
    title: str
    prompt: str
    summary_markdown: str
    spatial_selection: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "title": self.title,
            "prompt": self.prompt,
            "summary_markdown": self.summary_markdown,
            "spatial_selection": dict(self.spatial_selection),
        }


def build_incident_task(
    *,
    scenario_name: str,
    location_name: str,
    incident_type: str,
    incident_duration_minutes: int,
    lane_closure_count: int,
    objective: str,
    simulation_duration_seconds: int,
    spatial_selection: dict,
) -> StructuredTaskDraft:
    location = location_name.strip()
    if not location or not spatial_selection.get("edge_id"):
        raise ValueError("事件处置任务需要先在地图中选择道路或车道。")
    incident_minutes = _bounded_integer(incident_duration_minutes, 1, 180, "事件持续时间")
    closure_count = _bounded_integer(lane_closure_count, 1, 8, "封闭车道数")
    simulation_seconds = _bounded_integer(simulation_duration_seconds, 60, 3600, "仿真时长")
    prompt = (
        f"{location}发生{incident_type}，持续{incident_minutes}分钟，封闭{closure_count}条车道，"
        f"{objective}，请进行信号优化仿真，仿真{simulation_seconds}秒"
    )
    summary = "\n".join(
        [
            "**事件处置任务确认**",
            f"- 当前场景：{scenario_name}",
            f"- 事件位置：{location}",
            f"- 事件类型：{incident_type}",
            f"- 持续时间：{incident_minutes} 分钟",
            f"- 封闭车道：{closure_count} 条",
            f"- 优化目标：{objective}",
            f"- 仿真时长：{simulation_seconds} 秒",
        ]
    )
    return StructuredTaskDraft(
        task_type="incident_response",
        title="事件处置与信号优化",
        prompt=prompt,
        summary_markdown=summary,
        spatial_selection=dict(spatial_selection),
    )


def build_demand_adjustment_task(
    *,
    scenario_name: str,
    target: str,
    direction: str,
    percentage: int,
    spatial_scope: str,
    simulation_duration_seconds: int,
) -> StructuredTaskDraft:
    if direction not in {"提高", "降低"}:
        raise ValueError("需求调整方向必须为提高或降低。")
    adjustment = _bounded_integer(percentage, 1, 100, "需求调整幅度")
    simulation_seconds = _bounded_integer(simulation_duration_seconds, 60, 3600, "仿真时长")
    scope_text = spatial_scope.strip() or "整个场景"
    prompt = (
        f"在{scope_text}将{target}{direction}{adjustment}%，仿真{simulation_seconds}秒，"
        "并与原始需求进行公平对比"
    )
    summary = "\n".join(
        [
            "**交通需求调整任务确认**",
            f"- 当前场景：{scenario_name}",
            f"- 调整范围：{scope_text}",
            f"- 调整对象：{target}",
            f"- 调整幅度：{direction} {adjustment}%",
            f"- 仿真时长：{simulation_seconds} 秒",
            "- 评估方式：原始需求与调整后需求公平对比",
        ]
    )
    return StructuredTaskDraft(
        task_type="demand_adjustment",
        title="交通需求影响评估",
        prompt=prompt,
        summary_markdown=summary,
    )


def demand_target_options(scenario_id: str) -> tuple[str, ...]:
    if "nanjing_south" in scenario_id or "ride_hailing" in scenario_id:
        return (
            "网约车到站流量",
            "网约车离站流量",
            "全部网约车流量",
            "背景社会车辆流量",
            "全部流量",
        )
    return ("全部流量",)


def demand_scope_options(scenario_id: str) -> tuple[str, ...]:
    if "nanjing_south" in scenario_id or "ride_hailing" in scenario_id:
        return ("整个场景", "南京南站北广场", "南京南站南广场")
    return ("整个场景",)


def _bounded_integer(value: int, minimum: int, maximum: int, label: str) -> int:
    integer_value = int(value)
    if not minimum <= integer_value <= maximum:
        raise ValueError(f"{label}应位于 {minimum}-{maximum} 之间。")
    return integer_value
