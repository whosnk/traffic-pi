from __future__ import annotations

from dataclasses import dataclass

from simtrend_app.network_query import looks_like_network_query


@dataclass(frozen=True)
class TaskRoute:
    task_type: str
    workflow: str
    confidence: float
    reason: str
    required_categories: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "workflow": self.workflow,
            "confidence": self.confidence,
            "reason": self.reason,
            "required_categories": list(self.required_categories),
        }


class TaskRouter:
    def route(self, text: str, conversation_memory: list[dict] | None = None) -> TaskRoute:
        if _looks_like_fair_simulation_comparison(text):
            return TaskRoute(
                task_type="fair_simulation_comparison",
                workflow="fair_simulation_comparison",
                confidence=0.98,
                reason="检测到基准方案与候选方案的公平对比请求。",
                required_categories=("analysis",),
            )

        if _looks_like_parameterized_signal_simulation(text):
            return TaskRoute(
                task_type="parameterized_signal_simulation",
                workflow="parameterized_signal_simulation",
                confidence=0.98,
                reason="检测到明确的信号控制器和完整相位参数，调用单方案参数化仿真工具。",
                required_categories=("simulation", "analysis"),
            )

        if _looks_like_scene_overview_query(text):
            return TaskRoute(
                task_type="network_query",
                workflow="network_knowledge_query",
                confidence=0.99,
                reason="检测到当前场景的综合路网概况查询。",
                required_categories=("network_query",),
            )

        if _looks_like_signal_control_query(text):
            return TaskRoute(
                task_type="signal_control_query",
                workflow="signal_control_query",
                confidence=0.98,
                reason="检测到信号控制器、相位配置或道路受控关系查询。",
                required_categories=("network_query",),
            )

        if _looks_like_simulation_diagnosis(text):
            return TaskRoute(
                task_type="simulation_diagnosis",
                workflow="simulation_diagnosis",
                confidence=0.96,
                reason="检测到对最近仿真结果、拥堵瓶颈或异常道路的诊断请求。",
                required_categories=("analysis",),
            )

        if looks_like_network_query(text, conversation_memory):
            return TaskRoute(
                task_type="network_query",
                workflow="network_knowledge_query",
                confidence=0.98,
                reason="检测到路网对象、属性、连接关系或最近仿真指标查询。",
                required_categories=("network_query",),
            )

        if any(word in text for word in ("流量", "需求", "OD", "od")) and any(
            word in text for word in ("提高", "降低", "调整", "增加", "减少", "倍")
        ):
            return TaskRoute(
                task_type="demand_adjustment",
                workflow="demand_impact_evaluation",
                confidence=0.90,
                reason="检测到交通需求强度或 OD 调整，进入原始需求与调整后需求的影响评估流程。",
                required_categories=("scenario_understanding", "simulation", "analysis"),
            )

        if any(word in text for word in ("优化", "信号", "信控", "配时", "事故", "封闭", "拥堵", "排队")):
            return TaskRoute(
                task_type="signal_optimization",
                workflow="signal_optimization",
                confidence=0.94,
                reason="检测到交通事件、信号控制或拥堵优化目标。",
                required_categories=(
                    "scenario_understanding",
                    "traffic_control",
                    "simulation",
                    "analysis",
                    "reporting",
                ),
            )

        if any(word in text for word in ("对比", "报告", "结果", "指标")):
            return TaskRoute(
                task_type="result_analysis",
                workflow="signal_optimization",
                confidence=0.72,
                reason="检测到结果分析意图；当前版本沿用受约束的仿真评估流程。",
                required_categories=("analysis", "reporting"),
            )

        if any(word in text for word in ("仿真", "运行", "模拟")):
            return TaskRoute(
                task_type="simulation",
                workflow="signal_optimization",
                confidence=0.78,
                reason="检测到仿真执行请求；当前版本使用完整评估流程保证结果可解释。",
                required_categories=("scenario_understanding", "simulation", "analysis"),
            )

        return TaskRoute(
            task_type="traffic_task",
            workflow="signal_optimization",
            confidence=0.50,
            reason="未识别到独立查询意图，交由现有结构化澄清与仿真流程处理。",
            required_categories=("scenario_understanding",),
        )


def _looks_like_simulation_diagnosis(text: str) -> bool:
    diagnosis_words = (
        "诊断",
        "瓶颈",
        "哪里最拥堵",
        "拥堵最严重",
        "异常道路",
        "异常路段",
        "运行问题",
    )
    result_words = ("最近", "上一次", "仿真结果", "运行结果", "本次仿真")
    execution_words = ("运行仿真", "重新仿真", "进行仿真", "优化仿真")
    return (
        any(word in text for word in diagnosis_words)
        and any(word in text for word in result_words)
        and not any(word in text for word in execution_words)
    )


def _looks_like_scene_overview_query(text: str) -> bool:
    return (
        any(word in text for word in ("场景概况", "场景信息", "路网概况", "路网统计"))
        and any(word in text for word in ("查询", "查看", "显示", "告诉我", "有哪些", "多少"))
        and not any(word in text for word in ("仿真", "运行", "优化", "调整"))
    )


def _looks_like_parameterized_signal_simulation(text: str) -> bool:
    return (
        "控制器" in text
        and "相位" in text
        and any(word in text for word in ("仿真", "运行"))
    )


def _looks_like_signal_control_query(text: str) -> bool:
    signal_words = ("控制器", "信号灯", "相位配置", "当前相位", "信号周期", "受控车道")
    query_words = ("查询", "查看", "显示", "哪个", "哪些", "有哪些", "列出", "当前", "管理")
    action_words = ("运行", "仿真", "优化", "调整", "设置", "设为", "生成方案")
    return (
        any(word in text for word in signal_words)
        and any(word in text for word in query_words)
        and not any(word in text for word in action_words)
    )


def _looks_like_fair_simulation_comparison(text: str) -> bool:
    has_pair = "基准方案" in text and "候选方案" in text
    has_comparison = any(word in text for word in ("对比", "比较", "哪个更好", "是否改善", "公平评估"))
    return has_pair and has_comparison and not any(word in text for word in ("运行仿真", "重新仿真"))
