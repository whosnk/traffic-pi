from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from simtrend_app.config import Settings


@dataclass
class ModelDecision:
    summary: str
    tool_name: str
    tool_input: dict
    raw_text: str
    source_label: str
    status_detail: str


class QwenClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(self, user_message: str) -> ModelDecision:
        return self.decide_next_step(
            user_message=user_message,
            effective_user_message=user_message,
            context_summary={"available_next_tools": ["run_sumo_demo"], "completed_tools": []},
            step_history=[],
            memory=[],
            conversation_memory=[],
            last_failure=None,
        )

    def decide_next_step(
        self,
        user_message: str,
        effective_user_message: str,
        context_summary: dict,
        step_history: list[dict],
        memory: list[dict],
        conversation_memory: list[dict],
        last_failure: dict | None,
    ) -> ModelDecision:
        if not self.settings.qwen_api_key:
            return self._mock_next_step(user_message, context_summary, last_failure)

        available_tools = context_summary.get("available_next_tools", [])
        available_tool_specs = context_summary.get("available_tool_specs", [])
        system_prompt = (
            "你是交通仿真智能体的工具调度器。"
            "你需要在一次任务中逐步决定下一步要调用哪个本地工具。"
            "请严格返回 JSON，包含 summary、tool_name、tool_input 三个键。"
            "tool_name 只能从当前可用工具列表中选择一个。"
            "必须遵守 available_tool_specs 中的输入结构、前置条件和参数范围。"
            "不要臆造工具、文件路径或未在 input_schema 中声明的参数。"
            "如果当前用户是在追问、补充约束或修改参数，请保留历史事故背景与优化目标。"
            "如果某一步失败，请结合错误信息、中间记忆和会话记忆判断是重试当前工具还是继续下一步。"
            "tool_input 只填写必要参数。"
            "summary 用中文简洁说明你的选择原因。"
        )

        payload = {
            "model": self.settings.qwen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_user_message": user_message,
                            "effective_user_message": effective_user_message,
                            "available_next_tools": available_tools,
                            "available_tool_specs": available_tool_specs,
                            "task_route": context_summary.get("task_route", {}),
                            "step_history": step_history,
                            "memory": memory,
                            "conversation_memory": conversation_memory,
                            "last_failure": last_failure,
                            "context_summary": context_summary,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        try:
            response = requests.post(
                f"{self.settings.qwen_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.qwen_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except Exception as exc:
            return self._fallback_next_step(
                user_message=user_message,
                context_summary=context_summary,
                last_failure=last_failure,
                detail=f"请求真实模型时出错：{exc}",
            )

        if not isinstance(parsed, dict):
            return self._fallback_next_step(
                user_message=user_message,
                context_summary=context_summary,
                last_failure=last_failure,
                detail="真实模型返回的 JSON 不是对象，已使用回退策略继续执行工具链。",
            )

        chosen_tool = parsed.get("tool_name", "")
        if chosen_tool not in available_tools and available_tools:
            chosen_tool = available_tools[0]

        tool_input = parsed.get("tool_input", {})
        if not isinstance(tool_input, dict):
            tool_input = {}
        if "incident_text" not in tool_input and chosen_tool == "detect_incident":
            tool_input["incident_text"] = effective_user_message

        summary = parsed.get("summary", "模型没有返回摘要。")
        if not isinstance(summary, str) or not summary.strip():
            summary = "模型已返回工具调用决策。"

        return ModelDecision(
            summary=summary,
            tool_name=chosen_tool,
            tool_input=tool_input,
            raw_text=content,
            source_label="真实模型",
            status_detail=f"本次已成功调用真实模型：{self.settings.qwen_model}",
        )

    def _mock_next_step(
        self,
        user_message: str,
        context_summary: dict,
        last_failure: dict | None,
    ) -> ModelDecision:
        available_tools = context_summary.get("available_next_tools", [])
        chosen_tool = available_tools[0] if available_tools else "generate_report"
        duration_seconds = self._infer_duration_seconds(user_message)

        if last_failure and last_failure.get("failed_tool") in available_tools:
            chosen_tool = last_failure["failed_tool"]

        default_inputs = {
            "detect_incident": {"incident_text": user_message},
            "build_signal_plan": {"strategy": "signal_optimization", "duration_seconds": duration_seconds},
            "analyze_closure_impact": {},
            "run_baseline_simulation": {},
            "run_optimized_simulation": {},
            "compare_metrics": {},
            "generate_report": {},
            "prepare_demand_plan": {"duration_seconds": duration_seconds},
            "run_reference_demand_simulation": {},
            "run_adjusted_demand_simulation": {},
            "compare_demand_impact": {},
            "generate_demand_report": {},
        }
        summaries = {
            "detect_incident": "先识别事故方向与影响范围，为后续配时生成提供目标对象。",
            "build_signal_plan": "已具备事故方向信息，下一步生成基线与优化配时。",
            "analyze_closure_impact": "在运行仿真前检查封闭车道是否阻断既定路径，并生成安全处置计划。",
            "run_baseline_simulation": "先运行基线方案，作为后续优化对比的参照。",
            "run_optimized_simulation": "再运行优化方案，便于与基线仿真比较效果。",
            "compare_metrics": "仿真已经完成，下一步提取并比较关键指标。",
            "generate_report": "关键指标已具备，最后生成汇总报告。",
            "prepare_demand_plan": "先生成原始需求与调整后需求配置，并锁定其他控制变量。",
            "run_reference_demand_simulation": "先运行原始需求仿真，建立可复现的参照组。",
            "run_adjusted_demand_simulation": "保持控制条件不变，运行调整后需求仿真。",
            "compare_demand_impact": "两组仿真已完成，开始比较需求变化产生的运行影响。",
            "generate_demand_report": "需求影响指标已具备，最后生成评估报告。",
        }

        if last_failure:
            summaries[chosen_tool] = (
                f"上一步 `{last_failure.get('failed_tool')}` 失败，先重试当前最关键的工具。"
            )

        return ModelDecision(
            summary=summaries.get(chosen_tool, "进入下一步工具执行。"),
            tool_name=chosen_tool,
            tool_input=default_inputs.get(chosen_tool, {}),
            raw_text="mock",
            source_label="模拟模式",
            status_detail="当前未配置大模型 API Key，系统正在使用本地模拟决策。",
        )

    def _fallback_next_step(
        self,
        user_message: str,
        context_summary: dict,
        last_failure: dict | None,
        detail: str,
    ) -> ModelDecision:
        fallback = self._mock_next_step(user_message, context_summary, last_failure)
        fallback.source_label = "模型调用失败"
        fallback.status_detail = detail
        fallback.summary = "大模型接口调用失败，系统已使用回退策略继续执行工具链。"
        return fallback

    @staticmethod
    def _infer_duration_seconds(message: str) -> int:
        patterns = [
            r"(\d{2,4})\s*秒",
            r"(\d{2,4})\s*sec(?:ond)?s?",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                duration_seconds = int(match.group(1))
                return max(60, min(duration_seconds, 3600))
        return 300
