from __future__ import annotations

import inspect
from typing import Callable

from simtrend_app.config import Settings
from simtrend_app.fair_simulation_comparison import compare_simulation_runs
from simtrend_app.parameterized_signal import evaluate_signal_plan
from simtrend_app.signal_control_query import query_signal_control
from simtrend_app.simulation_diagnostics import diagnose_simulation_result
from simtrend_app.tools.base import ToolResult
from simtrend_app.tools.incident_tools import analyze_incident
from simtrend_app.tools.report_tools import generate_report
from simtrend_app.tools.specs import DEFAULT_TOOL_SPECS, ToolSpec
from simtrend_app.tools.sumo_tools import run_sumo_demo


class ToolRegistry:
    def __init__(
        self,
        settings: Settings,
        tool_overrides: dict[str, Callable[..., ToolResult]] | None = None,
        tool_specs: dict[str, ToolSpec] | None = None,
    ) -> None:
        self.settings = settings
        self._tools: dict[str, Callable[..., ToolResult]] = {
            "analyze_incident": analyze_incident,
            "run_sumo_demo": lambda **kwargs: run_sumo_demo(settings, **kwargs),
            "generate_report": generate_report,
            "diagnose_simulation_result": lambda **kwargs: diagnose_simulation_result(settings, **kwargs),
            "evaluate_signal_plan": lambda **kwargs: evaluate_signal_plan(settings, **kwargs),
            "query_signal_control": lambda **kwargs: query_signal_control(settings, **kwargs),
            "compare_simulation_runs": lambda **kwargs: compare_simulation_runs(settings, **kwargs),
        }
        if tool_overrides:
            self._tools.update(tool_overrides)
        self._specs = dict(DEFAULT_TOOL_SPECS)
        if tool_specs:
            self._specs.update(tool_specs)

    def available_tools(self) -> list[str]:
        return sorted(self._tools)

    def tool_spec(self, tool_name: str) -> ToolSpec | None:
        return self._specs.get(tool_name)

    def available_tool_specs(
        self,
        tool_names: list[str] | None = None,
        state: dict | None = None,
    ) -> list[dict]:
        names = tool_names if tool_names is not None else self.available_tools()
        return [
            self._specs[name].as_dict(state)
            for name in names
            if name in self._tools and name in self._specs
        ]

    def run(self, tool_name: str, tool_input: dict, state: dict | None = None) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            available = ", ".join(self.available_tools())
            return ToolResult(
                ok=False,
                message=f"未找到工具 `{tool_name}`。当前可用工具有：{available}。",
                data={
                    "error": {
                        "code": "TOOL_NOT_FOUND",
                        "message": f"工具 {tool_name} 未注册",
                        "recoverable": False,
                    }
                },
            )

        spec = self._specs.get(tool_name)
        if spec:
            unmet = spec.unmet_preconditions(state)
            if unmet:
                return ToolResult(
                    ok=False,
                    message=f"工具 `{tool_name}` 的前置条件尚未满足：{', '.join(unmet)}。",
                    data={
                        "error": {
                            "code": "PRECONDITION_FAILED",
                            "message": "缺少前置产物",
                            "missing_artifacts": unmet,
                            "recoverable": True,
                        }
                    },
                )

        try:
            filtered_input, dropped_keys = self._filter_tool_input(tool, tool_input or {})
            if spec:
                validation_errors = spec.validate_input(filtered_input)
                if validation_errors:
                    return ToolResult(
                        ok=False,
                        message=f"工具 `{tool_name}` 输入参数无效：{'；'.join(validation_errors)}。",
                        data={
                            "tool_input": filtered_input,
                            "error": {
                                "code": "INVALID_TOOL_INPUT",
                                "message": "；".join(validation_errors),
                                "recoverable": True,
                            },
                        },
                    )
            result = tool(**filtered_input)
        except Exception as exc:
            return ToolResult(
                ok=False,
                message=f"工具 `{tool_name}` 执行失败：{exc}",
                data={
                    "tool_input": tool_input,
                    "error": {
                        "code": "TOOL_EXECUTION_FAILED",
                        "message": str(exc),
                        "recoverable": True,
                    },
                },
            )

        if not isinstance(result, ToolResult):
            return ToolResult(
                ok=False,
                message=f"工具 `{tool_name}` 返回了无效结果。",
                data={
                    "error": {
                        "code": "INVALID_TOOL_RESULT",
                        "message": "工具必须返回 ToolResult",
                        "recoverable": False,
                    }
                },
            )

        if dropped_keys:
            result.message += f"\n\n附加说明：已忽略模型返回的额外参数 {', '.join(dropped_keys)}。"
            result.data["dropped_keys"] = dropped_keys
        if not result.ok and "error" not in result.data:
            result.data["error"] = {
                "code": "TOOL_EXECUTION_FAILED",
                "message": result.message[:400],
                "recoverable": True,
            }
        return result

    @staticmethod
    def _filter_tool_input(tool: Callable[..., ToolResult], tool_input: dict) -> tuple[dict, list[str]]:
        signature = inspect.signature(tool)
        parameters = signature.parameters
        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if accepts_var_kwargs:
            return dict(tool_input), []

        allowed_keys = {
            name
            for name, parameter in parameters.items()
            if parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        filtered_input = {key: value for key, value in tool_input.items() if key in allowed_keys}
        dropped_keys = [key for key in tool_input if key not in allowed_keys]
        return filtered_input, dropped_keys
