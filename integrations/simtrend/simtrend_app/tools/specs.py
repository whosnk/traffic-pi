from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JSON_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    display_name: str
    description: str
    category: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    required_artifacts: tuple[str, ...] = field(default_factory=tuple)
    produces_artifacts: tuple[str, ...] = field(default_factory=tuple)
    possible_errors: tuple[str, ...] = field(default_factory=tuple)
    read_only: bool = False
    side_effects: tuple[str, ...] = field(default_factory=tuple)

    def validate_input(self, tool_input: dict[str, Any]) -> list[str]:
        schema = self.input_schema or {"type": "object", "properties": {}}
        properties = schema.get("properties") or {}
        errors = []
        for name in schema.get("required") or []:
            if name not in tool_input or tool_input[name] is None:
                errors.append(f"缺少必填参数 `{name}`")
        for name, value in tool_input.items():
            field_schema = properties.get(name)
            if not field_schema or value is None:
                continue
            expected_type = field_schema.get("type")
            checker = JSON_TYPE_CHECKS.get(expected_type)
            if checker and not checker(value):
                errors.append(f"参数 `{name}` 应为 {expected_type}")
            enum_values = field_schema.get("enum")
            if enum_values and value not in enum_values:
                errors.append(f"参数 `{name}` 必须是 {enum_values} 之一")
            minimum = field_schema.get("minimum")
            maximum = field_schema.get("maximum")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if minimum is not None and value < minimum:
                    errors.append(f"参数 `{name}` 不能小于 {minimum}")
                if maximum is not None and value > maximum:
                    errors.append(f"参数 `{name}` 不能大于 {maximum}")
        return errors

    def unmet_preconditions(self, state: dict[str, Any] | None) -> list[str]:
        if state is None or not self.required_artifacts:
            return []
        return [artifact for artifact in self.required_artifacts if not state.get(artifact)]

    def as_dict(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        unmet = self.unmet_preconditions(state)
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "input_schema": self.input_schema,
            "required_artifacts": list(self.required_artifacts),
            "produces_artifacts": list(self.produces_artifacts),
            "possible_errors": list(self.possible_errors),
            "read_only": self.read_only,
            "side_effects": list(self.side_effects),
            "available": not unmet,
            "unmet_preconditions": unmet,
        }


def _object_schema(properties: dict[str, Any] | None = None, required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
    }


SIGNAL_OPTIMIZATION_TOOL_SPECS = {
    "detect_incident": ToolSpec(
        name="detect_incident",
        display_name="交通事件识别",
        description="解析事故、拥堵、位置、车道封闭和交通需求信息，生成结构化事件对象。",
        category="scenario_understanding",
        input_schema=_object_schema(
            {
                "incident_text": {"type": "string"},
                "scenario": {"type": "string"},
            },
            required=("incident_text",),
        ),
        produces_artifacts=("detection_json",),
        possible_errors=("INVALID_LOCATION", "OBJECT_NOT_FOUND", "TOOL_EXECUTION_FAILED"),
        read_only=True,
    ),
    "build_signal_plan": ToolSpec(
        name="build_signal_plan",
        display_name="信号控制策略生成",
        description="根据结构化事件和仿真时长生成基线与优化信号配时方案。",
        category="traffic_control",
        input_schema=_object_schema(
            {
                "strategy": {"type": "string"},
                "duration_seconds": {"type": "integer", "minimum": 60, "maximum": 3600},
            }
        ),
        required_artifacts=("detection_json",),
        produces_artifacts=("signal_plan_json",),
        possible_errors=("PRECONDITION_FAILED", "INVALID_SIGNAL_PLAN", "TOOL_EXECUTION_FAILED"),
        side_effects=("write_signal_plan",),
    ),
    "analyze_closure_impact": ToolSpec(
        name="analyze_closure_impact",
        display_name="封道影响预检",
        description="在运行仿真前检查封闭车道对既定路线和车辆的影响，并生成移除或延后处置计划。",
        category="scenario_analysis",
        input_schema=_object_schema(),
        required_artifacts=("signal_plan_json",),
        produces_artifacts=("closure_analysis_json",),
        possible_errors=("INVALID_CLOSURE", "NETWORK_PARSE_FAILED", "TOOL_EXECUTION_FAILED"),
        read_only=True,
        side_effects=("write_closure_precheck",),
    ),
    "run_baseline_simulation": ToolSpec(
        name="run_baseline_simulation",
        display_name="基线方案仿真",
        description="使用事件场景和基线控制方案执行一次可复现的交通仿真。",
        category="simulation",
        input_schema=_object_schema(),
        required_artifacts=("signal_plan_json", "closure_analysis_json"),
        produces_artifacts=("baseline_json",),
        possible_errors=("NO_PATH", "GRIDLOCK", "SIMULATION_FAILED", "TOOL_EXECUTION_FAILED"),
        side_effects=("run_simulator", "write_simulation_outputs"),
    ),
    "run_optimized_simulation": ToolSpec(
        name="run_optimized_simulation",
        display_name="优化方案仿真",
        description="使用优化控制方案执行仿真，生成与基线方案可比较的结果。",
        category="simulation",
        input_schema=_object_schema(),
        required_artifacts=("signal_plan_json", "baseline_json"),
        produces_artifacts=("optimized_json",),
        possible_errors=("NO_PATH", "GRIDLOCK", "SIMULATION_FAILED", "TOOL_EXECUTION_FAILED"),
        side_effects=("run_simulator", "write_simulation_outputs"),
    ),
    "compare_metrics": ToolSpec(
        name="compare_metrics",
        display_name="优化前后指标对比",
        description="读取基线和优化仿真结果，按目标道路、车道与全网范围计算对比指标。",
        category="analysis",
        input_schema=_object_schema(),
        required_artifacts=("detection_json", "signal_plan_json", "baseline_json", "optimized_json"),
        produces_artifacts=("comparison_json",),
        possible_errors=("MISSING_OUTPUT", "METRIC_PARSE_FAILED", "TOOL_EXECUTION_FAILED"),
        read_only=True,
        side_effects=("write_comparison",),
    ),
    "generate_report": ToolSpec(
        name="generate_report",
        display_name="结果报告生成",
        description="汇总场景、控制方案、仿真指标、回放文件和工具执行记录。",
        category="reporting",
        input_schema=_object_schema(
            {
                "strategy": {"type": "string"},
                "scenario": {"type": "string"},
            }
        ),
        required_artifacts=("comparison_json", "closure_analysis_json"),
        produces_artifacts=("report_json",),
        possible_errors=("MISSING_OUTPUT", "REPORT_GENERATION_FAILED", "TOOL_EXECUTION_FAILED"),
        read_only=True,
        side_effects=("write_report",),
    ),
}


DEMAND_IMPACT_TOOL_SPECS = {
    "prepare_demand_plan": ToolSpec(
        name="prepare_demand_plan",
        display_name="交通需求方案生成",
        description="把自然语言需求调整转换为原始需求与调整后需求两个可复现配置。",
        category="scenario_understanding",
        input_schema=_object_schema(
            {"duration_seconds": {"type": "integer", "minimum": 60, "maximum": 3600}}
        ),
        produces_artifacts=("demand_plan_json",),
        possible_errors=("INVALID_DEMAND_TARGET", "INVALID_MULTIPLIER", "TOOL_EXECUTION_FAILED"),
        side_effects=("write_demand_plan",),
    ),
    "run_reference_demand_simulation": ToolSpec(
        name="run_reference_demand_simulation",
        display_name="原始需求仿真",
        description="使用场景默认需求和原始控制条件执行参照仿真。",
        category="simulation",
        input_schema=_object_schema(),
        required_artifacts=("demand_plan_json",),
        produces_artifacts=("reference_json",),
        possible_errors=("NO_PATH", "GRIDLOCK", "SIMULATION_FAILED", "TOOL_EXECUTION_FAILED"),
        side_effects=("run_simulator", "write_simulation_outputs"),
    ),
    "run_adjusted_demand_simulation": ToolSpec(
        name="run_adjusted_demand_simulation",
        display_name="调整后需求仿真",
        description="只替换交通需求配置，保持路网和信号条件不变并执行第二次仿真。",
        category="simulation",
        input_schema=_object_schema(),
        required_artifacts=("demand_plan_json", "reference_json"),
        produces_artifacts=("adjusted_json",),
        possible_errors=("NO_PATH", "GRIDLOCK", "SIMULATION_FAILED", "TOOL_EXECUTION_FAILED"),
        side_effects=("run_simulator", "write_simulation_outputs"),
    ),
    "compare_demand_impact": ToolSpec(
        name="compare_demand_impact",
        display_name="交通需求影响对比",
        description="比较原始与调整后需求下的指定车辆组和全路网运行指标。",
        category="analysis",
        input_schema=_object_schema(),
        required_artifacts=("demand_plan_json", "reference_json", "adjusted_json"),
        produces_artifacts=("demand_comparison_json",),
        possible_errors=("MISSING_OUTPUT", "METRIC_PARSE_FAILED", "TOOL_EXECUTION_FAILED"),
        read_only=True,
        side_effects=("write_comparison",),
    ),
    "generate_demand_report": ToolSpec(
        name="generate_demand_report",
        display_name="需求影响报告生成",
        description="汇总需求配置、两次仿真、指标变化和回放文件，形成需求影响评估报告。",
        category="reporting",
        input_schema=_object_schema(),
        required_artifacts=("demand_comparison_json",),
        produces_artifacts=("demand_report_json",),
        possible_errors=("MISSING_OUTPUT", "REPORT_GENERATION_FAILED", "TOOL_EXECUTION_FAILED"),
        read_only=True,
        side_effects=("write_report",),
    ),
}


NETWORK_QUERY_TOOL_SPEC = ToolSpec(
    name="query_network_knowledge",
    display_name="路网知识查询与语义定位",
    description="检索当前场景中的道路、车道、路口和上客区，并查询连接关系或最近仿真指标。",
    category="network_query",
    input_schema=_object_schema(
        {
            "query": {"type": "string"},
            "scenario_id": {"type": "string"},
        },
        required=("query",),
    ),
    produces_artifacts=("spatial_selection",),
    possible_errors=("OBJECT_NOT_FOUND", "AMBIGUOUS_OBJECT", "METRIC_OUTPUT_NOT_FOUND"),
    read_only=True,
    side_effects=("update_map_selection",),
)


SIMULATION_DIAGNOSIS_TOOL_SPEC = ToolSpec(
    name="diagnose_simulation_result",
    display_name="仿真结果诊断",
    description="读取最近一次仿真的道路与全局指标，识别瓶颈道路、异常证据和可能的拥堵传播方向。",
    category="analysis",
    input_schema=_object_schema(
        {
            "variant": {
                "type": "string",
                "enum": ["latest", "optimized", "baseline", "adjusted_demand", "reference_demand", "parameterized"],
            },
            "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
        }
    ),
    produces_artifacts=("diagnosis_json", "spatial_selection"),
    possible_errors=("DIAGNOSIS_INPUT_NOT_FOUND", "METRIC_PARSE_FAILED", "TOOL_EXECUTION_FAILED"),
    side_effects=("write_diagnosis", "update_map_selection"),
)


PARAMETERIZED_SIGNAL_TOOL_SPEC = ToolSpec(
    name="evaluate_signal_plan",
    display_name="可参数化信号方案仿真",
    description="校验指定信号控制器的完整相位时长，使用固定随机种子真实运行一次仿真并输出标准指标与瓶颈诊断。",
    category="simulation",
    input_schema=_object_schema(
        {
            "controller_id": {"type": "string"},
            "program_id": {"type": "string"},
            "phase_durations": {"type": "array", "items": {"type": "number"}},
            "duration_seconds": {"type": "integer", "minimum": 60, "maximum": 3600},
            "random_seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
            "render_animation": {"type": "boolean"},
            "result_slot": {"type": "string", "enum": ["latest", "reference", "candidate"]},
        },
        required=("controller_id", "phase_durations"),
    ),
    produces_artifacts=("parameterized_result_json", "diagnosis_json"),
    possible_errors=("INVALID_SIGNAL_PARAMETERS", "SIMULATION_FAILED", "TOOL_EXECUTION_FAILED"),
    side_effects=("write_signal_network", "run_simulator", "write_simulation_outputs"),
)


SIGNAL_CONTROL_QUERY_TOOL_SPEC = ToolSpec(
    name="query_signal_control",
    display_name="信号控制器与相位查询",
    description="只读查询当前路网的信号控制器、完整相位配置、受控道路车道及各相位放行连接。",
    category="network_query",
    input_schema=_object_schema(
        {
            "query": {"type": "string"},
            "controller_id": {"type": "string"},
            "edge_id": {"type": "string"},
            "lane_id": {"type": "string"},
            "program_id": {"type": "string"},
        }
    ),
    produces_artifacts=("signal_context", "spatial_selection"),
    possible_errors=("SIGNAL_CONTROLLER_NOT_FOUND", "SIGNAL_INDEX_FAILED", "TOOL_EXECUTION_FAILED"),
    read_only=True,
    side_effects=("update_map_selection",),
)


FAIR_SIMULATION_COMPARISON_TOOL_SPEC = ToolSpec(
    name="compare_simulation_runs",
    display_name="任意两次仿真结果公平对比",
    description="先检查场景、时长、随机种子、路网控制关系和车辆路线是否一致，再比较全局指标与道路影响。",
    category="analysis",
    input_schema=_object_schema(
        {
            "reference": {"type": "string"},
            "candidate": {"type": "string"},
            "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        required=("reference", "candidate"),
    ),
    produces_artifacts=("fair_comparison_json", "spatial_selection"),
    possible_errors=("COMPARISON_INPUT_INVALID", "METRIC_PARSE_FAILED", "TOOL_EXECUTION_FAILED"),
    read_only=True,
    side_effects=("write_comparison", "update_map_selection"),
)


DEFAULT_TOOL_SPECS = {
    "analyze_incident": ToolSpec(
        name="analyze_incident",
        display_name="事件分析",
        description="分析自然语言交通事件。",
        category="scenario_understanding",
        input_schema=_object_schema({"user_message": {"type": "string"}}),
        read_only=True,
    ),
    "run_sumo_demo": ToolSpec(
        name="run_sumo_demo",
        display_name="仿真演示",
        description="执行兼容模式的交通仿真演示。",
        category="simulation",
        input_schema=_object_schema(),
        side_effects=("run_simulator",),
    ),
    "generate_report": SIGNAL_OPTIMIZATION_TOOL_SPECS["generate_report"],
    "diagnose_simulation_result": SIMULATION_DIAGNOSIS_TOOL_SPEC,
    "evaluate_signal_plan": PARAMETERIZED_SIGNAL_TOOL_SPEC,
    "query_signal_control": SIGNAL_CONTROL_QUERY_TOOL_SPEC,
    "compare_simulation_runs": FAIR_SIMULATION_COMPARISON_TOOL_SPEC,
}
