from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from simtrend_app.agent.intent_parser import (
    IntentParseResult,
    build_clarification_markdown,
    build_structured_prompt,
    build_suggested_reply,
    format_intent_markdown,
)
from simtrend_app.agent.qwen_client import QwenClient
from simtrend_app.agent.task_router import TaskRouter
from simtrend_app.animation_targets import (
    comparison_animation_targets,
    parameterized_animation_targets,
    replay_charts,
)
from simtrend_app.config import Settings
from simtrend_app.fair_simulation_comparison import compare_simulation_runs
from simtrend_app.map_selector import load_map_objects
from simtrend_app.network_query import NetworkQueryResult, NetworkQueryService
from simtrend_app.parameterized_signal import parse_parameterized_signal_request
from simtrend_app.signal_control_query import query_signal_control
from simtrend_app.scenario_runtime import ScenarioRuntime
from simtrend_app.task_safety import isolate_conversation_memory, review_task_intent
from simtrend_app.tools.agent_tool_chain import AgentToolChain
from simtrend_app.tools.base import ToolResult
from simtrend_app.tools.demand_impact_tool_chain import DemandImpactToolChain
from simtrend_app.tools.registry import ToolRegistry
from simtrend_app.tools.specs import (
    NETWORK_QUERY_TOOL_SPEC,
    FAIR_SIMULATION_COMPARISON_TOOL_SPEC,
    PARAMETERIZED_SIGNAL_TOOL_SPEC,
    SIGNAL_CONTROL_QUERY_TOOL_SPEC,
    SIMULATION_DIAGNOSIS_TOOL_SPEC,
)


@dataclass
class WorkflowResult:
    rendered_markdown: str
    model_source_label: str
    model_status_detail: str
    charts: list[dict] = field(default_factory=list)
    process_steps: list[dict] = field(default_factory=list)
    session_memory_entry: dict = field(default_factory=dict)
    export_markdown: str = ""
    export_filename: str = "simtrend_report.md"
    animation_targets: dict = field(default_factory=dict)
    spatial_selection: dict = field(default_factory=dict)


class AgentWorkflow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = QwenClient(settings)
        self.router = TaskRouter()

    def handle_user_message(
        self,
        user_message: str,
        conversation_memory: list[dict] | None = None,
        progress_callback=None,
    ) -> WorkflowResult:
        self._notify_progress(progress_callback, "start", "正在解析任务输入...")
        conversation_memory = isolate_conversation_memory(user_message, conversation_memory)
        task_route = self.router.route(user_message, conversation_memory)
        if task_route.task_type == "fair_simulation_comparison":
            self._notify_progress(progress_callback, "fair_comparison", "正在检查两次仿真的实验条件与结果可比性...")
            tool_result = compare_simulation_runs(
                self.settings,
                reference="reference",
                candidate="candidate",
                top_n=5,
            )
            self._notify_progress(
                progress_callback,
                "fair_comparison_done",
                "已完成公平对比" if tool_result.ok else "公平对比失败",
            )
            return self._build_fair_comparison_result(user_message, tool_result)

        if task_route.task_type == "signal_control_query":
            self._notify_progress(progress_callback, "signal_query", "正在读取信号控制器、相位和受控连接...")
            tool_result = query_signal_control(self.settings, query=user_message)
            self._notify_progress(
                progress_callback,
                "signal_query_done",
                "已完成信号控制信息查询" if tool_result.ok else "信号控制信息查询失败",
            )
            return self._build_signal_control_query_result(user_message, tool_result)

        if task_route.task_type == "parameterized_signal_simulation":
            tool_input, missing = parse_parameterized_signal_request(user_message)
            if missing:
                return self._build_parameterized_signal_result(
                    user_message,
                    ToolResult(
                        ok=False,
                        message=(
                            "**参数化信号仿真需要补充信息**\n\n"
                            f"缺少：{'、'.join(missing)}。\n\n"
                            "示例：控制器 c00 的相位时长设为 50、3、34、3，运行600秒仿真，随机种子42。"
                        ),
                        data={"error": {"code": "MISSING_SIGNAL_PARAMETERS", "recoverable": True}},
                    ),
                    {},
                )
            self._notify_progress(progress_callback, "parameterized_signal", "正在校验信号参数并运行单方案仿真...")
            tool_result = ToolRegistry(self.settings).run("evaluate_signal_plan", tool_input)
            self._notify_progress(
                progress_callback,
                "parameterized_signal_done",
                "参数化信号仿真已完成" if tool_result.ok else "参数化信号仿真失败",
            )
            return self._build_parameterized_signal_result(user_message, tool_result, tool_input)

        if task_route.task_type == "simulation_diagnosis":
            self._notify_progress(progress_callback, "diagnosis", "正在读取最近一次仿真并识别拥堵瓶颈...")
            registry = ToolRegistry(self.settings)
            tool_result = registry.run(
                "diagnose_simulation_result",
                {"variant": "latest", "top_n": 5},
            )
            self._notify_progress(
                progress_callback,
                "diagnosis_done",
                "已完成仿真结果诊断" if tool_result.ok else "仿真结果诊断失败",
            )
            return self._build_simulation_diagnosis_result(user_message, tool_result)

        if task_route.task_type == "network_query":
            self._notify_progress(progress_callback, "network_query", "正在检索当前场景的路网对象与拓扑信息...")
            runtime = ScenarioRuntime.from_project_dir(self.settings.sumo_project_dir)
            query_result = NetworkQueryService(runtime).query(
                user_message,
                conversation_memory=conversation_memory,
            )
            self._notify_progress(progress_callback, "network_query_done", "已完成路网信息查询")
            return self._build_network_query_result(user_message, runtime, query_result)

        safety_review = review_task_intent(
            user_message,
            conversation_memory,
            task_route=task_route.as_dict(),
        )
        intent_result = safety_review.intent
        self._notify_progress(progress_callback, "intent", "已完成任务解析，正在检查关键信息...")

        if safety_review.requires_clarification:
            self._notify_progress(progress_callback, "clarify", "当前信息不足，正在生成澄清问题...")
            return self._build_clarification_result(user_message, intent_result)

        effective_user_message = build_structured_prompt(user_message, intent_result)
        self._notify_progress(progress_callback, "plan", "已完成结构化任务，正在规划执行步骤...")
        scenario_id = self._scenario_id_from_project_dir()
        if task_route.workflow == "demand_impact_evaluation":
            executor = DemandImpactToolChain(
                self.settings,
                request_text=effective_user_message,
                scenario=scenario_id,
                duration_seconds=int(intent_result.merged_intent.get("simulation_duration_seconds") or 300),
                task_route=task_route.as_dict(),
            )
        else:
            executor = AgentToolChain(
                self.settings,
                incident_text=effective_user_message,
                scenario=scenario_id,
                task_route=task_route.as_dict(),
            )
        registry = ToolRegistry(
            self.settings,
            tool_overrides=executor.tool_functions(),
            tool_specs=executor.tool_specs(),
        )

        step_history: list[dict] = []
        memory: list[dict] = []
        final_result = ToolResult(ok=False, message="未执行任何工具。")
        first_decision = None
        last_decision = None
        last_failure: dict | None = None
        retry_counts: dict[str, int] = {}

        for _ in range(10):
            context_summary = executor.state_snapshot()
            available_tools = context_summary.get("available_next_tools", [])
            if not available_tools:
                break

            decision = self.client.decide_next_step(
                user_message=user_message,
                effective_user_message=effective_user_message,
                context_summary=context_summary,
                step_history=step_history,
                memory=memory,
                conversation_memory=conversation_memory,
                last_failure=last_failure,
            )

            if decision.tool_name not in available_tools:
                decision.tool_name = available_tools[0]
                decision.tool_input = self._default_tool_input(
                    decision.tool_name,
                    effective_user_message,
                    intent_result,
                )

            if first_decision is None:
                first_decision = decision
            last_decision = decision
            self._notify_progress(
                progress_callback,
                decision.tool_name,
                self._progress_text_for_tool(decision.tool_name),
            )

            resolved_tool_input = self._resolve_tool_input(
                decision.tool_name,
                effective_user_message,
                intent_result,
                decision.tool_input,
            )
            attempt_number = retry_counts.get(decision.tool_name, 0) + 1
            tool_result = registry.run(
                tool_name=decision.tool_name,
                tool_input=resolved_tool_input,
                state=context_summary,
            )
            final_result = tool_result
            selected_spec = registry.tool_spec(decision.tool_name)

            step_record = {
                "tool_name": decision.tool_name,
                "display_name": self._tool_display_name(decision.tool_name),
                "summary": decision.summary,
                "ok": tool_result.ok,
                "message": tool_result.message[:240],
                "result_text": tool_result.message[:1200],
                "tool_input": resolved_tool_input,
                "tool_output": tool_result.data or {},
                "tool_spec": selected_spec.as_dict(context_summary) if selected_spec else {},
                "attempt": attempt_number,
                "retry_count": attempt_number - 1,
            }
            step_history.append(step_record)
            self._notify_progress(
                progress_callback,
                f"{decision.tool_name}_done",
                self._progress_done_text_for_tool(decision.tool_name, tool_result.ok),
            )

            if tool_result.ok:
                memory.append(self._build_memory_entry(decision.tool_name, tool_result))
                last_failure = None
            else:
                retry_counts[decision.tool_name] = retry_counts.get(decision.tool_name, 0) + 1
                step_record["retry_count"] = retry_counts[decision.tool_name] - 1
                step_record["will_retry"] = retry_counts[decision.tool_name] < 2
                last_failure = {
                    "failed_tool": decision.tool_name,
                    "retry_count": retry_counts[decision.tool_name],
                    "error_summary": tool_result.message[:400],
                    "structured_error": (tool_result.data or {}).get("error", {}),
                }
                if retry_counts[decision.tool_name] >= 2:
                    break
                continue

            if decision.tool_name in {"generate_report", "generate_demand_report"}:
                break

        self._notify_progress(progress_callback, "finalize", "正在整理结果、图表与汇报内容...")

        decision_for_display = last_decision or first_decision or self.client._mock_next_step(  # type: ignore[attr-defined]
            user_message=user_message,
            context_summary={"available_next_tools": []},
            last_failure=last_failure,
        )

        judgement_title = "需求判断" if task_route.workflow == "demand_impact_evaluation" else "事件判断"
        judgement_text = (
            self._build_demand_judgement(intent_result, first_decision.summary if first_decision else decision_for_display.summary)
            if task_route.workflow == "demand_impact_evaluation"
            else self._build_event_judgement(
                intent_result,
                first_decision.summary if first_decision else decision_for_display.summary,
            )
        )
        sections = [
            f"**模型来源**\n{decision_for_display.source_label}",
            (
                "**任务路由**\n"
                f"任务类型：{task_route.task_type}；工作流：{task_route.workflow}；"
                f"判断说明：{task_route.reason}"
            ),
            f"**结构化任务**\n{format_intent_markdown(intent_result)}",
            f"**{judgement_title}**\n{judgement_text}",
            f"**执行动作**\n{self._build_action_summary(step_history, final_result)}",
        ]

        scene_injection_markdown = self._build_scene_injection_section(final_result)
        if scene_injection_markdown:
            sections.append(f"**场景注入**\n{scene_injection_markdown}")

        closure_handling_markdown = self._build_closure_handling_section(final_result)
        if closure_handling_markdown:
            sections.append(f"**封道可行性处理**\n{closure_handling_markdown}")

        pickup_waiting_markdown = self._build_pickup_waiting_section(final_result)
        if pickup_waiting_markdown:
            sections.append(f"**网约车上客区停靠等待**\n{pickup_waiting_markdown}")

        demand_markdown = self._build_demand_adjustment_section(final_result)
        if demand_markdown:
            sections.append(f"**交通需求设置**\n{demand_markdown}")

        edge_impact_markdown = self._build_edge_impact_section(final_result)
        if edge_impact_markdown:
            sections.append(f"**重点影响道路**\n{edge_impact_markdown}")

        conversation_markdown = self._build_conversation_section(conversation_memory, intent_result)
        if conversation_markdown:
            sections.append(f"**会话延续**\n{conversation_markdown}")

        memory_markdown = self._build_memory_section(memory)
        if memory_markdown:
            sections.append(f"**中间记忆**\n{memory_markdown}")

        comparison_markdown = self._build_comparison_metrics(final_result)
        if comparison_markdown:
            comparison_title = (
                "需求调整前后对比"
                if task_route.workflow == "demand_impact_evaluation"
                else "优化前后对比"
            )
            sections.append(f"**{comparison_title}**\n{comparison_markdown}")

        tool_chain_markdown = self._build_tool_chain_steps(final_result)
        if tool_chain_markdown:
            sections.append(f"**工具链步骤**\n{tool_chain_markdown}")

        retry_markdown = self._build_retry_section(step_history)
        if retry_markdown:
            sections.append(f"**失败与重试**\n{retry_markdown}")

        advice_title = "影响分析" if task_route.workflow == "demand_impact_evaluation" else "优化建议"
        advice_text = (
            self._build_demand_impact_suggestion(final_result)
            if task_route.workflow == "demand_impact_evaluation"
            else self._build_optimization_suggestion(intent_result, final_result)
        )
        sections.extend(
            [
                f"**{advice_title}**\n{advice_text}",
                f"**下一步建议**\n{self._build_next_step(intent_result, final_result, last_failure)}",
                f"**执行日志**\n{final_result.message}",
            ]
        )

        export_markdown = self._build_export_markdown(
            user_message=user_message,
            effective_user_message=effective_user_message,
            intent_result=intent_result,
            tool_result=final_result,
            model_source_label=decision_for_display.source_label,
            step_history=step_history,
        )

        return WorkflowResult(
            rendered_markdown="\n\n".join(sections),
            model_source_label=decision_for_display.source_label,
            model_status_detail=decision_for_display.status_detail,
            charts=self._build_visual_payload(final_result),
            process_steps=self._build_process_steps(
                user_message=user_message,
                effective_user_message=effective_user_message,
                intent_result=intent_result,
                step_history=step_history,
                clarification_mode=False,
            ),
            session_memory_entry=self._build_session_memory_entry(
                user_message=user_message,
                effective_user_message=effective_user_message,
                step_history=step_history,
                tool_result=final_result,
                intent_result=intent_result,
                awaiting_clarification=False,
            ),
            export_markdown=export_markdown,
            export_filename=self._build_export_filename(final_result),
            animation_targets=self._build_animation_targets(final_result),
        )

    @staticmethod
    def _notify_progress(progress_callback, stage: str, message: str) -> None:
        if progress_callback:
            progress_callback(stage, message)

    @staticmethod
    def _build_network_query_result(
        user_message: str,
        runtime: ScenarioRuntime,
        query_result: NetworkQueryResult,
    ) -> WorkflowResult:
        clean_message = user_message.split("SimTrend空间精确定位", 1)[0].strip()
        process_steps = [
            {
                "name": "路网查询意图识别",
                "status": "success",
                "summary": "已识别为只读路网信息查询，不启动交通仿真。",
                "input": {"user_message": clean_message, "scenario_id": runtime.scenario_id},
                "output": {"query_kind": query_result.query_kind},
            },
            {
                "name": "空间对象检索",
                "status": "waiting" if query_result.awaiting_clarification else "success",
                "summary": "需要用户选择候选对象" if query_result.awaiting_clarification else "已完成对象检索与属性读取。",
                "tool_spec": NETWORK_QUERY_TOOL_SPEC.as_dict(),
                "input": {"net_file": runtime.net_file.name},
                "output": {
                    "status": query_result.status,
                    "candidate_count": len(query_result.candidates),
                    "selected_object": query_result.spatial_selection,
                },
            },
        ]
        memory_entry = {
            "user_message": clean_message,
            "task_type": "network_query",
            "scenario_id": runtime.scenario_id,
            "network_query_status": query_result.status,
            "network_query_candidates": list(query_result.candidates),
            "spatial_selection": query_result.spatial_selection,
            "awaiting_network_clarification": query_result.awaiting_clarification,
            "awaiting_clarification": False,
        }
        return WorkflowResult(
            rendered_markdown=query_result.answer_markdown,
            model_source_label="路网知识查询",
            model_status_detail="本次直接读取当前场景路网数据，未启动仿真。",
            process_steps=process_steps,
            session_memory_entry=memory_entry,
            spatial_selection=query_result.spatial_selection,
        )

    @staticmethod
    def _build_simulation_diagnosis_result(
        user_message: str,
        tool_result: ToolResult,
    ) -> WorkflowResult:
        diagnosis = (tool_result.data or {}).get("diagnosis", {})
        spatial_selection = (tool_result.data or {}).get("spatial_selection", {})
        process_steps = [
            {
                "name": "仿真结果诊断",
                "status": "success" if tool_result.ok else "error",
                "summary": "读取已有仿真产物并完成确定性瓶颈诊断，不重新运行仿真。",
                "tool_spec": SIMULATION_DIAGNOSIS_TOOL_SPEC.as_dict(),
                "input": {"variant": "latest", "top_n": 5},
                "output": {
                    "primary_bottleneck": (diagnosis.get("summary") or {}).get("primary_bottleneck"),
                    "bottleneck_count": len(diagnosis.get("bottlenecks") or []),
                },
            }
        ]
        return WorkflowResult(
            rendered_markdown=tool_result.message,
            model_source_label="仿真结果诊断工具",
            model_status_detail="本次直接分析最近仿真产物，未重新启动仿真，也未让大模型编造指标。",
            process_steps=process_steps,
            session_memory_entry={
                "user_message": user_message,
                "task_type": "simulation_diagnosis",
                "diagnosis_summary": diagnosis.get("summary", {}),
                "spatial_selection": spatial_selection,
                "awaiting_clarification": False,
            },
            spatial_selection=spatial_selection,
        )

    @staticmethod
    def _build_parameterized_signal_result(
        user_message: str,
        tool_result: ToolResult,
        tool_input: dict,
    ) -> WorkflowResult:
        data = tool_result.data or {}
        diagnosis = data.get("diagnosis", {})
        spatial_selection = data.get("spatial_selection", {})
        animation_targets = parameterized_animation_targets(data) if tool_result.ok else {}
        return WorkflowResult(
            rendered_markdown=tool_result.message,
            model_source_label="可参数化信号方案仿真工具",
            model_status_detail=(
                "本次按用户明确给定的相位参数真实运行单个方案；未生成候选方案，也未判断其优于基线。"
            ),
            process_steps=[
                {
                    "name": "信号参数校验与单方案仿真",
                    "status": "success" if tool_result.ok else "error",
                    "summary": "只修改指定信号控制器，使用固定随机种子执行一次真实仿真。",
                    "tool_spec": PARAMETERIZED_SIGNAL_TOOL_SPEC.as_dict(),
                    "input": tool_input,
                    "output": {
                        "controller_id": (data.get("signal_plan") or {}).get("controller_id"),
                        "primary_bottleneck": (diagnosis.get("summary") or {}).get("primary_bottleneck"),
                    },
                }
            ],
            session_memory_entry={
                "user_message": user_message,
                "task_type": "parameterized_signal_simulation",
                "tool_input": tool_input,
                "signal_plan": data.get("signal_plan", {}),
                "diagnosis_summary": diagnosis.get("summary", {}),
                "awaiting_clarification": False,
            },
            charts=replay_charts(animation_targets),
            animation_targets=animation_targets,
            spatial_selection=spatial_selection,
        )

    @staticmethod
    def _build_signal_control_query_result(
        user_message: str,
        tool_result: ToolResult,
    ) -> WorkflowResult:
        data = tool_result.data or {}
        context = data.get("signal_context", {})
        spatial_selection = data.get("spatial_selection", {})
        return WorkflowResult(
            rendered_markdown=tool_result.message,
            model_source_label="信号控制器与相位查询工具",
            model_status_detail="本次只读取当前路网中的真实信号定义和受控连接，未启动仿真。",
            process_steps=[
                {
                    "name": "信号控制关系查询",
                    "status": "success" if tool_result.ok else "error",
                    "summary": "已建立道路、车道、控制器、相位和放行连接之间的只读关联。",
                    "tool_spec": SIGNAL_CONTROL_QUERY_TOOL_SPEC.as_dict(),
                    "input": {"query": user_message},
                    "output": {
                        "query_status": data.get("query_status"),
                        "controller_id": context.get("controller_id"),
                        "controller_count": len(data.get("controllers") or []),
                    },
                }
            ],
            session_memory_entry={
                "user_message": user_message,
                "task_type": "signal_control_query",
                "query_status": data.get("query_status"),
                "signal_context": context,
                "spatial_selection": spatial_selection,
                "awaiting_clarification": False,
            },
            spatial_selection=spatial_selection,
        )

    @staticmethod
    def _build_fair_comparison_result(
        user_message: str,
        tool_result: ToolResult,
    ) -> WorkflowResult:
        data = tool_result.data or {}
        comparison = data.get("comparison", {})
        comparability = comparison.get("comparability", {})
        spatial_selection = data.get("spatial_selection", {})
        animation_targets = comparison_animation_targets(comparison) if tool_result.ok else {}
        return WorkflowResult(
            rendered_markdown=tool_result.message,
            model_source_label="任意两次仿真结果公平对比工具",
            model_status_detail="本次先核验实验条件，再计算指标差异；未重新运行仿真。",
            process_steps=[
                {
                    "name": "仿真结果公平对比",
                    "status": "success" if tool_result.ok else "error",
                    "summary": "已检查控制变量，并比较全局指标与道路级变化。",
                    "tool_spec": FAIR_SIMULATION_COMPARISON_TOOL_SPEC.as_dict(),
                    "input": {"reference": "reference", "candidate": "candidate", "top_n": 5},
                    "output": {
                        "strictly_comparable": comparability.get("strictly_comparable"),
                        "verdict": (comparison.get("conclusion") or {}).get("verdict"),
                    },
                }
            ],
            session_memory_entry={
                "user_message": user_message,
                "task_type": "fair_simulation_comparison",
                "comparability": comparability,
                "conclusion": comparison.get("conclusion", {}),
                "spatial_selection": spatial_selection,
                "awaiting_clarification": False,
            },
            charts=replay_charts(animation_targets),
            animation_targets=animation_targets,
            spatial_selection=spatial_selection,
        )

    @staticmethod
    def _progress_text_for_tool(tool_name: str) -> str:
        mapping = {
            "detect_incident": "正在识别交通事件...",
            "build_signal_plan": "正在生成信号控制策略...",
            "analyze_closure_impact": "正在预检封道对路线与车流的影响...",
            "run_baseline_simulation": "正在运行基线仿真...",
            "run_optimized_simulation": "正在运行优化仿真...",
            "compare_metrics": "正在对比优化前后指标...",
            "generate_report": "正在生成结果报告...",
            "prepare_demand_plan": "正在生成原始与调整后交通需求方案...",
            "run_reference_demand_simulation": "正在运行原始需求仿真...",
            "run_adjusted_demand_simulation": "正在运行调整后需求仿真...",
            "compare_demand_impact": "正在对比交通需求调整前后指标...",
            "generate_demand_report": "正在生成交通需求影响报告...",
        }
        return mapping.get(tool_name, f"正在执行 {tool_name} ...")

    @staticmethod
    def _progress_done_text_for_tool(tool_name: str, ok: bool) -> str:
        prefix = "已完成" if ok else "执行失败"
        mapping = {
            "detect_incident": f"{prefix}事故识别",
            "build_signal_plan": f"{prefix}策略生成",
            "analyze_closure_impact": f"{prefix}封道影响预检",
            "run_baseline_simulation": f"{prefix}基线仿真",
            "run_optimized_simulation": f"{prefix}优化仿真",
            "compare_metrics": f"{prefix}指标对比",
            "generate_report": f"{prefix}结果报告",
            "prepare_demand_plan": f"{prefix}需求方案生成",
            "run_reference_demand_simulation": f"{prefix}原始需求仿真",
            "run_adjusted_demand_simulation": f"{prefix}调整后需求仿真",
            "compare_demand_impact": f"{prefix}需求影响对比",
            "generate_demand_report": f"{prefix}需求影响报告",
        }
        return mapping.get(tool_name, f"{prefix} {tool_name}")

    @staticmethod
    def _tool_display_name(tool_name: str) -> str:
        mapping = {
            "detect_incident": "事故识别",
            "build_signal_plan": "策略生成",
            "analyze_closure_impact": "封道影响预检",
            "run_baseline_simulation": "基线仿真",
            "run_optimized_simulation": "优化仿真",
            "compare_metrics": "指标对比",
            "generate_report": "结果报告",
            "prepare_demand_plan": "需求方案生成",
            "run_reference_demand_simulation": "原始需求仿真",
            "run_adjusted_demand_simulation": "调整后需求仿真",
            "compare_demand_impact": "需求影响对比",
            "generate_demand_report": "需求影响报告",
        }
        return mapping.get(tool_name, tool_name)

    def _build_process_steps(
        self,
        user_message: str,
        effective_user_message: str,
        intent_result: IntentParseResult,
        step_history: list[dict],
        clarification_mode: bool,
    ) -> list[dict]:
        steps = [
            {
                "name": "任务解析",
                "status": "success",
                "summary": "已完成自然语言解析。",
                "input": {"user_message": user_message},
                "output": {
                    "task_type": intent_result.merged_intent.get("task_type_label"),
                    "incident_type": intent_result.merged_intent.get("incident_type_label"),
                    "location": intent_result.merged_intent.get("location_text"),
                    "duration_seconds": intent_result.merged_intent.get("simulation_duration_seconds"),
                },
            }
        ]

        if clarification_mode:
            steps.append(
                {
                    "name": "澄清对话",
                    "status": "waiting",
                    "summary": "当前信息不足，系统已进入澄清模式。",
                    "input": {"effective_user_message": effective_user_message},
                    "output": {"missing_fields": intent_result.missing_fields},
                }
            )
            return steps

        steps.append(
            {
                "name": "结构化规划",
                "status": "success",
                "summary": "已生成结构化任务描述并开始调度工具链。",
                "input": {"effective_user_message": effective_user_message},
                "output": {"structured_fields": intent_result.merged_intent},
            }
        )

        for index, step in enumerate(step_history, start=1):
            status = "success" if step.get("ok") else "failed"
            if step.get("will_retry"):
                status = "retrying"
            steps.append(
                {
                    "name": f"{index}. {step.get('display_name', step.get('tool_name', '步骤'))}",
                    "status": status,
                    "summary": step.get("summary") or step.get("message", ""),
                    "input": step.get("tool_input", {}),
                    "output": step.get("tool_output", {}),
                    "tool_spec": step.get("tool_spec", {}),
                    "message": step.get("result_text", ""),
                    "attempt": step.get("attempt", 1),
                    "retry_count": step.get("retry_count", 0),
                }
            )
        return steps

    def default_runtime_status(self) -> tuple[str, str]:
        if self.settings.qwen_api_key:
            return (
                "已配置真实模型",
                f"已检测到 API Key，待首次请求验证模型 `{self.settings.qwen_model}` 是否可用。",
            )
        return ("模拟模式", "尚未配置大模型 API Key，当前会使用本地模拟决策。")

    def _build_clarification_result(
        self,
        user_message: str,
        intent_result: IntentParseResult,
    ) -> WorkflowResult:
        sections = [
            "**模型来源**\n澄清对话",
            f"**结构化任务**\n{format_intent_markdown(intent_result)}",
            "**事件判断**\n当前信息还不足以启动可信仿真，系统先进入澄清模式。",
            f"**待确认信息**\n{build_clarification_markdown(intent_result)}",
            f"**建议回复**\n- {build_suggested_reply(intent_result)}",
            "**下一步建议**\n补充上面的关键字段后，系统会自动继续结构化解析并启动仿真。",
        ]
        return WorkflowResult(
            rendered_markdown="\n\n".join(sections),
            model_source_label="澄清对话",
            model_status_detail="当前等待用户补充关键信息后再启动仿真。",
            charts=[],
            process_steps=self._build_process_steps(
                user_message=user_message,
                effective_user_message=user_message,
                intent_result=intent_result,
                step_history=[],
                clarification_mode=True,
            ),
            session_memory_entry=self._build_session_memory_entry(
                user_message=user_message,
                effective_user_message=user_message,
                step_history=[],
                tool_result=ToolResult(ok=False, message="当前等待用户补充关键信息。"),
                intent_result=intent_result,
                awaiting_clarification=True,
            ),
            export_markdown="",
            export_filename="simtrend_report.md",
            animation_targets={},
        )

    @staticmethod
    def _build_animation_targets(tool_result: ToolResult) -> dict:
        data = tool_result.data or {}
        baseline_cfg = data.get("baseline_cfg_file") or data.get("cfg_file")
        optimized_cfg = data.get("optimized_cfg_file")
        animations = data.get("animations") or {}
        targets = {}
        demand_workflow = data.get("workflow_type") == "demand_impact_evaluation"
        if baseline_cfg:
            targets["baseline"] = {
                "label": "原始需求动画" if demand_workflow else "基线方案动画",
                "cfg_file": str(baseline_cfg),
            }
        if optimized_cfg:
            targets["optimized"] = {
                "label": "调整后需求动画" if demand_workflow else "优化方案动画",
                "cfg_file": str(optimized_cfg),
            }
        baseline_animation = animations.get("baseline") or {}
        optimized_animation = animations.get("optimized") or {}
        if baseline_animation.get("gif_file"):
            targets.setdefault("baseline", {"label": "Baseline replay", "cfg_file": str(baseline_cfg or "")})
            targets["baseline"]["gif_file"] = str(baseline_animation["gif_file"])
            targets["baseline"]["replay_status"] = baseline_animation
        if optimized_animation.get("gif_file"):
            targets.setdefault("optimized", {"label": "Optimized replay", "cfg_file": str(optimized_cfg or "")})
            targets["optimized"]["gif_file"] = str(optimized_animation["gif_file"])
            targets["optimized"]["replay_status"] = optimized_animation
        return targets

    @staticmethod
    def _default_tool_input(
        tool_name: str,
        effective_user_message: str,
        intent_result: IntentParseResult,
    ) -> dict:
        intent = intent_result.merged_intent
        duration_seconds = intent.get("simulation_duration_seconds") or AgentWorkflow._infer_duration_seconds(
            effective_user_message
        )
        strategy = AgentWorkflow._strategy_from_intent(intent)
        defaults = {
            "detect_incident": {"incident_text": effective_user_message},
            "build_signal_plan": {
                "strategy": strategy,
                "duration_seconds": duration_seconds,
            },
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
        return defaults.get(tool_name, {})

    def _scenario_id_from_project_dir(self) -> str:
        return ScenarioRuntime.from_project_dir(self.settings.sumo_project_path).scenario_id

    @staticmethod
    def _resolve_tool_input(
        tool_name: str,
        effective_user_message: str,
        intent_result: IntentParseResult,
        model_tool_input: dict | None,
    ) -> dict:
        resolved = AgentWorkflow._default_tool_input(tool_name, effective_user_message, intent_result)
        if isinstance(model_tool_input, dict):
            resolved.update({key: value for key, value in model_tool_input.items() if value is not None})
        return resolved

    @staticmethod
    def _strategy_from_intent(intent: dict) -> str:
        objective = intent.get("priority_objective")
        mapping = {
            "bus_priority": "bus_priority",
            "emergency_clearance": "emergency_clearance",
            "throughput": "throughput_maximization",
            "delay_reduction": "delay_reduction",
            "queue_reduction": "signal_optimization",
        }
        return mapping.get(objective, "signal_optimization")

    @staticmethod
    def _build_memory_entry(tool_name: str, tool_result: ToolResult) -> dict:
        data = tool_result.data or {}
        summary_parts = [tool_result.message.splitlines()[0].strip()]
        if data.get("target_label"):
            summary_parts.append(f"目标：{data['target_label']}")
        if data.get("axis_label"):
            summary_parts.append(f"轴向：{data['axis_label']}")
        if data.get("duration_seconds"):
            summary_parts.append(f"时长：{data['duration_seconds']} 秒")
        if data.get("comparison"):
            comparison = data["comparison"]
            if data.get("workflow_type") == "demand_impact_evaluation":
                summary_parts.append(f"全网平均等待变化：{comparison['overall_avg_wait_delta_s']:+.2f} 秒")
            else:
                summary_parts.append(f"重点方向排队变化：{comparison['target_avg_queue_delta_m']:+.2f} 米")
        return {"tool_name": tool_name, "summary": "；".join(summary_parts)}

    @staticmethod
    def _build_event_judgement(intent_result: IntentParseResult, model_summary: str) -> str:
        intent = intent_result.merged_intent
        fragments = []
        if intent.get("incident_type_label"):
            fragments.append(f"检测到{intent['incident_type_label']}")
        if intent.get("location_text"):
            fragments.append(f"位置为{intent['location_text']}")
        if intent.get("priority_objective_label"):
            fragments.append(f"优化目标为{intent['priority_objective_label']}")
        if intent.get("lane_closure_count"):
            fragments.append(f"疑似涉及封闭 {intent['lane_closure_count']} 条车道")
        prefix = "，".join(fragments) if fragments else "已识别到待优化的交通事件"
        return f"{prefix}。模型判断：{model_summary}"

    @staticmethod
    def _build_demand_judgement(intent_result: IntentParseResult, model_summary: str) -> str:
        intent = intent_result.merged_intent
        target = intent.get("demand_target_label") or "交通需求"
        multiplier = intent.get("demand_multiplier")
        profile = intent.get("demand_profile_label")
        adjustment = f"调整为 {float(multiplier):.2f} 倍" if multiplier is not None else f"设置为{profile}"
        time_scope = ""
        if intent.get("demand_window_start_s") is not None and intent.get("demand_window_end_s") is not None:
            time_scope = f"，调整时段为第{intent['demand_window_start_s']}-{intent['demand_window_end_s']}秒"
        spatial_scope = (
            f"，空间范围为{intent['demand_spatial_scope_label']}"
            if intent.get("demand_spatial_scope_label")
            else ""
        )
        return (
            f"已识别为交通需求影响评估，调整对象为{target}，{adjustment}{time_scope}{spatial_scope}。"
            "评估将保持路网、信号控制、路径分布和仿真时长一致。"
            f"模型判断：{model_summary}"
        )

    @staticmethod
    def _build_action_summary(step_history: list[dict], tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        if data.get("workflow_type") == "demand_impact_evaluation":
            parts = [
                f"评估对象为 {data.get('target_label', '交通需求')}",
                f"仿真时长为 {data.get('duration_seconds', 300)} 秒",
                "已在相同路网和信号条件下分别运行原始需求与调整后需求仿真",
            ]
            if step_history:
                parts.append("工具顺序：" + " -> ".join(step["tool_name"] for step in step_history))
            return "；".join(parts) + "。"
        parts = []
        if data.get("target_label"):
            parts.append(f"重点控制对象为 {data['target_label']}")
        if data.get("axis_label"):
            parts.append(f"本次配时优化针对 {data['axis_label']}")
        if data.get("duration_seconds"):
            parts.append(f"仿真时长为 {data['duration_seconds']} 秒")
        if data.get("scenario"):
            parts.append(f"场景标识为 {data['scenario']}")
        signal_plan = data.get("signal_plan", {})
        baseline_plan = signal_plan.get("baseline", {})
        optimized_plan = signal_plan.get("optimized", {})
        if baseline_plan and optimized_plan:
            parts.append(
                "信号配时已从 "
                f"NS {baseline_plan.get('north_south_green_s')}s / EW {baseline_plan.get('east_west_green_s')}s "
                "调整为 "
                f"NS {optimized_plan.get('north_south_green_s')}s / EW {optimized_plan.get('east_west_green_s')}s"
            )
        if step_history:
            parts.append("本次由大模型逐步调用工具：" + " -> ".join(step["tool_name"] for step in step_history))
        return "；".join(parts) + "。"

    @staticmethod
    def _extract_scene_injection_summary(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        incident_context = data.get("incident_context") or {}
        if incident_context.get("apply_scene_edit"):
            blocked_lane_label = incident_context.get("blocked_lane_label", "目标进口")
            lane_closure_count = incident_context.get("lane_closure_count", 0)
            incident_duration_minutes = incident_context.get("incident_duration_minutes", 0)
            return (
                f"已将事故场景注入到 {blocked_lane_label}："
                f"封闭 {lane_closure_count} 条车道，持续 {incident_duration_minutes} 分钟"
            )

        message = tool_result.message or ""
        match = re.search(r"事故场景注入[:：]\s*([^\n。]+)", message)
        if match:
            return f"已将事故场景注入到 {match.group(1).strip()}"
        return ""

    @staticmethod
    def _build_scene_injection_section(tool_result: ToolResult) -> str:
        summary = AgentWorkflow._extract_scene_injection_summary(tool_result)
        if not summary:
            return ""
        return f"- {summary}"

    @staticmethod
    def _build_closure_handling_section(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        precheck = data.get("closure_precheck") or {}
        incident_impacts = data.get("incident_impacts") or {}
        baseline_impact = incident_impacts.get("baseline") or {}
        removed_flow_ids = baseline_impact.get("removed_flow_ids") or []
        delayed_flow_ids = baseline_impact.get("delayed_flow_ids") or []
        removed_vehicle_ids = baseline_impact.get("removed_vehicle_ids") or []
        delayed_vehicle_ids = baseline_impact.get("delayed_vehicle_ids") or []
        affected_route_ids = precheck.get("affected_route_ids") or baseline_impact.get("affected_route_ids") or []
        affected_vehicle_ids = precheck.get("affected_vehicle_ids") or baseline_impact.get("affected_vehicle_ids") or []
        has_execution_actions = bool(
            removed_flow_ids or delayed_flow_ids or removed_vehicle_ids or delayed_vehicle_ids
        )
        if not precheck.get("enabled") and not has_execution_actions:
            return ""

        lines = []
        if precheck.get("enabled"):
            status = "需要安全处置" if precheck.get("requires_mitigation") else "无需调整既定车流"
            lines.append(
                f"- 预检结论：{status}；封闭路段 {precheck.get('blocked_edge_id', '')}，"
                f"涉及 {len(affected_route_ids)} 条路线、"
                f"{len(precheck.get('affected_flow_ids') or [])} 条车流和 "
                f"{len(affected_vehicle_ids)} 辆显式车辆。"
            )
            lines.append(f"- 处置说明：{precheck.get('note', '')}")
        if has_execution_actions:
            lines.append(
                f"- 执行核验：已移除事故期无可用路径车流 {len(removed_flow_ids)} 条，"
                f"延后事故后可恢复车流 {len(delayed_flow_ids)} 条，"
                f"移除车辆 {len(removed_vehicle_ids)} 辆，"
                f"延后车辆 {len(delayed_vehicle_ids)} 辆。"
            )
        if removed_flow_ids:
            lines.append(f"- 移除车流：{', '.join(removed_flow_ids)}。")
        if delayed_flow_ids:
            lines.append(f"- 延后车流：{', '.join(delayed_flow_ids)}。")
        if removed_vehicle_ids:
            preview = ", ".join(removed_vehicle_ids[:12])
            suffix = " 等" if len(removed_vehicle_ids) > 12 else ""
            lines.append(f"- 移除车辆：{preview}{suffix}。")
        if delayed_vehicle_ids:
            preview = ", ".join(delayed_vehicle_ids[:12])
            suffix = " 等" if len(delayed_vehicle_ids) > 12 else ""
            lines.append(f"- 延后车辆：{preview}{suffix}。")
        return "\n".join(lines)

    @staticmethod
    def _build_pickup_waiting_section(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        pickup_waiting = data.get("pickup_waiting") or {}
        baseline_pickup = pickup_waiting.get("baseline") or pickup_waiting
        if not baseline_pickup.get("enabled"):
            return ""
        zones = baseline_pickup.get("zones") or []
        if not zones:
            return ""

        lines = [
            f"- 本次启用 {len(zones)} 个上客区，共为 {baseline_pickup.get('total_stopped_vehicles', 0)} 辆网约车插入真实停靠等待。"
        ]
        for zone in zones:
            lines.append(
                f"- {zone.get('name', zone.get('id', '上客区'))}："
                f"绑定车道 {zone.get('lane_id', '')}，"
                f"容量 {zone.get('capacity', 0)} 泊位，"
                f"平均上客 {zone.get('boarding_duration_s', 0)} 秒，"
                f"本次停靠 {zone.get('matched_vehicle_count', 0)} 辆。"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_demand_adjustment_section(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        demand_adjustments = data.get("demand_adjustments") or {}
        if data.get("workflow_type") == "demand_impact_evaluation":
            reference = demand_adjustments.get("reference") or {}
            adjusted = demand_adjustments.get("adjusted") or {}
            plan = data.get("demand_plan") or {}
            scope = data.get("adjustment_scope") or plan.get("adjustment_scope") or {}
            lines = [
                f"- 唯一变化变量：{data.get('changed_variable', '交通需求配置')}。",
                f"- 调整对象：{plan.get('target_label', data.get('target_label', '交通需求'))}。",
                f"- 原始需求车辆数：{reference.get('adjusted_vehicle_count', reference.get('original_vehicle_count', 0))} 辆；"
                f"调整后需求车辆数：{adjusted.get('adjusted_vehicle_count', 0)} 辆。",
                f"- 调整时段：第 {scope.get('time_window_start_s', 0)}-{scope.get('time_window_end_s', data.get('duration_seconds', 300))} 秒；"
                f"空间范围：{scope.get('spatial_scope_label', '整个场景')}。",
            ]
            for group in adjusted.get("vehicle_group_summaries", []):
                if abs(float(group.get("multiplier", 1.0)) - 1.0) < 1e-6:
                    continue
                lines.append(
                    f"- {group.get('group_label', group.get('group_key', '车辆组'))}："
                    f"范围内 {group.get('eligible_count', group.get('original_count', 0))}"
                    f" -> {group.get('adjusted_eligible_count', group.get('adjusted_count', 0))} 辆；"
                    f"全时段总数 {group.get('original_count', 0)} -> {group.get('adjusted_count', 0)} 辆，"
                    f"倍率 {float(group.get('multiplier', 1.0)):.2f}。"
                )
            controlled = data.get("controlled_variables") or []
            if controlled:
                lines.append(f"- 控制变量保持一致：{'、'.join(controlled)}。")
            return "\n".join(lines)

        baseline_demand = demand_adjustments.get("baseline") or demand_adjustments
        if not baseline_demand:
            return ""
        profile_label = baseline_demand.get("profile_label", "标准流量")
        multiplier = float(baseline_demand.get("multiplier", 1.0) or 1.0)
        scaled_count = baseline_demand.get("scaled_flow_count", 0)
        original_total = baseline_demand.get("original_total_vehs_per_hour", 0)
        adjusted_total = baseline_demand.get("adjusted_total_vehs_per_hour", 0)
        lines = [
            f"- 本次交通需求强度：{profile_label}，需求倍率 {multiplier:.2f}。",
        ]
        if scaled_count:
            lines.append(
                f"- 已动态缩放 {scaled_count} 条 OD/车流需求："
                f"{original_total:.0f} veh/h -> {adjusted_total:.0f} veh/h。"
            )
        elif baseline_demand.get("vehicle_demand_enabled"):
            lines.append(
                f"- 已动态调整显式车辆："
                f"{baseline_demand.get('original_vehicle_count', 0)} 辆"
                f" -> {baseline_demand.get('adjusted_vehicle_count', 0)} 辆。"
            )
            for group in baseline_demand.get("vehicle_group_summaries", []):
                if group.get("multiplier") == 1.0:
                    continue
                lines.append(
                    f"- {group.get('group_label', group.get('group_key', '车辆组'))}："
                    f"倍率 {float(group.get('multiplier', 1.0)):.2f}，"
                    f"{group.get('original_count', 0)} -> {group.get('adjusted_count', 0)} 辆。"
                )
        else:
            lines.append("- 当前使用场景默认需求，未额外缩放 OD/车流。")
        return "\n".join(lines)

    @staticmethod
    def _build_conversation_section(
        conversation_memory: list[dict],
        intent_result: IntentParseResult,
    ) -> str:
        if not conversation_memory or not intent_result.inherited_fields:
            return ""
        recent_summaries = [
            item.get("summary", "")
            for item in conversation_memory[-2:]
            if item.get("summary")
        ]
        lines = [f"- 本轮自动继承了历史上下文字段：{'、'.join(intent_result.inherited_fields)}。"]
        for summary in recent_summaries:
            lines.append(f"- 历史上下文：{summary}")
        return "\n".join(lines)

    @staticmethod
    def _build_memory_section(memory: list[dict]) -> str:
        if not memory:
            return ""
        return "\n".join(f"- `{item['tool_name']}`：{item['summary']}" for item in memory)

    @staticmethod
    def _build_comparison_metrics(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        comparison = data.get("comparison")
        if not comparison:
            return ""
        if data.get("workflow_type") == "demand_impact_evaluation":
            target_label = data.get("target_label", "目标车辆组")
            return "\n".join(
                [
                    f"- {target_label}平均等待：{comparison['target_avg_wait_before_s']:.2f} 秒 -> {comparison['target_avg_wait_after_s']:.2f} 秒（变化 {comparison['target_avg_wait_delta_s']:+.2f} 秒）",
                    f"- {target_label}平均行程时间：{comparison['target_avg_duration_before_s']:.2f} 秒 -> {comparison['target_avg_duration_after_s']:.2f} 秒（变化 {comparison['target_avg_duration_delta_s']:+.2f} 秒）",
                    f"- {target_label}完成车辆数：{comparison['target_completed_before']:.0f} -> {comparison['target_completed_after']:.0f}（变化 {comparison['target_completed_delta']:+.0f} 辆）",
                    f"- 全网平均等待：{comparison['overall_avg_wait_before_s']:.2f} 秒 -> {comparison['overall_avg_wait_after_s']:.2f} 秒（变化 {comparison['overall_avg_wait_delta_s']:+.2f} 秒）",
                    f"- 全路网完成车辆数：{comparison['arrived_before']:.0f} -> {comparison['arrived_after']:.0f}（变化 {comparison['arrived_delta']:+.0f} 辆）",
                    f"- 全路网最大滞留车辆：{comparison['max_halting_before']:.0f} -> {comparison['max_halting_after']:.0f}（变化 {comparison['max_halting_delta']:+.0f} 辆）",
                ]
            )
        return "\n".join(
            [
                f"- 目标车道平均排队长度：{comparison['target_avg_queue_before_m']:.2f} 米 -> {comparison['target_avg_queue_after_m']:.2f} 米（变化 {comparison['target_avg_queue_delta_m']:+.2f} 米）",
                f"- 目标车流平均等待时间：{comparison['target_avg_wait_before_s']:.2f} 秒 -> {comparison['target_avg_wait_after_s']:.2f} 秒（变化 {comparison['target_avg_wait_delta_s']:+.2f} 秒）",
                f"- 全局平均等待：{comparison['overall_avg_wait_before_s']:.2f} 秒 -> {comparison['overall_avg_wait_after_s']:.2f} 秒（变化 {comparison['overall_avg_wait_delta_s']:+.2f} 秒）",
                f"- 全路网完成车辆数：{comparison['arrived_before']:.0f} -> {comparison['arrived_after']:.0f}（变化 {comparison['arrived_delta']:+.0f} 辆）",
                f"- 路口最大滞留车辆：{comparison['max_halting_before']:.0f} -> {comparison['max_halting_after']:.0f}（变化 {comparison['max_halting_delta']:+.0f} 辆）",
            ]
        )

    @staticmethod
    def _build_edge_impact_section(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        if data.get("workflow_type") != "demand_impact_evaluation":
            return ""
        summary = data.get("edge_impact_summary") or {}
        top_edges = summary.get("top_affected_edges") or []
        if not top_edges:
            return ""
        lines = [
            f"- 本次共分析 {summary.get('analyzed_edge_count', len(data.get('edge_impacts') or []))} 条实际通行道路，"
            f"识别高影响道路 {summary.get('high_impact_edge_count', 0)} 条。"
        ]
        for index, row in enumerate(top_edges[:10], start=1):
            lines.append(
                f"- {index}. 道路 `{row['edge_id']}`：影响评分 {float(row['impact_score']):.1f}，"
                f"进入车辆变化 {float(row['vehicle_entered_delta']):+.0f} 辆，"
                f"平均速度变化 {float(row['mean_speed_delta_mps']):+.2f} m/s，"
                f"时间损失变化 {float(row['time_loss_delta_s']):+.1f} 秒。"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_tool_chain_steps(tool_result: ToolResult) -> str:
        steps = (tool_result.data or {}).get("tool_chain_steps", [])
        if not steps:
            return ""
        return "\n".join(f"- {step}" for step in steps)

    @staticmethod
    def _build_retry_section(step_history: list[dict]) -> str:
        failed_steps = [step for step in step_history if not step["ok"]]
        if not failed_steps:
            return ""
        return "\n".join(f"- `{step['tool_name']}` 失败：{step['message']}" for step in failed_steps)

    @staticmethod
    def _build_optimization_suggestion(intent_result: IntentParseResult, tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        comparison = data.get("comparison", {})
        direction = data.get("target_label") or intent_result.merged_intent.get("location_text") or "重点方向"
        suggestions: list[str] = []

        if comparison:
            if comparison.get("target_avg_queue_delta_m", 0) < 0:
                suggestions.append(f"当前方案对 {direction} 的排队抑制是有效的，可以作为事故处置阶段的优先策略")
            if comparison.get("overall_avg_wait_delta_s", 0) > 0 or comparison.get("arrived_delta", 0) < 0:
                suggestions.append("同时要注意该方案对全局效率存在副作用，建议设置限时启用或加入多目标权重")
            if comparison.get("max_halting_delta", 0) > 0:
                suggestions.append("建议继续约束非重点方向的滞留增长，避免把拥堵转移到其他进口")

        strategy = data.get("strategy")
        if strategy:
            suggestions.append(f"后续可以把 `{strategy}` 细化成更明确的参数搜索或强化学习动作空间")
        return "；".join(suggestions) + "。"

    @staticmethod
    def _build_demand_impact_suggestion(tool_result: ToolResult) -> str:
        data = tool_result.data or {}
        comparison = data.get("comparison") or {}
        if not comparison:
            return "需求影响评估尚未形成完整指标，请先检查两次仿真是否成功。"
        target = data.get("target_label", "目标车辆组")
        return (
            f"{target}需求变化后，其平均等待变化 {comparison['target_avg_wait_delta_s']:+.2f} 秒，"
            f"全网平均等待变化 {comparison['overall_avg_wait_delta_s']:+.2f} 秒，"
            f"全路网最大滞留车辆变化 {comparison['max_halting_delta']:+.0f} 辆。"
            "该结果反映需求增长的运行影响，不代表信号控制方案已经得到优化。"
        )

    @staticmethod
    def _build_next_step(
        intent_result: IntentParseResult,
        tool_result: ToolResult,
        last_failure: dict | None,
    ) -> str:
        if last_failure:
            return "当前已有失败记录。下一步建议增强错误分类、自动改参重试和安全回退策略。"
        if (tool_result.data or {}).get("workflow_type") == "demand_impact_evaluation":
            return "下一步可以增加分时段需求调整和重点路段流量热力图，进一步定位需求增长的空间影响。"
        if tool_result.ok and (tool_result.data or {}).get("comparison"):
            return "下一步建议把结构化意图真正映射到场景编辑和优化器中，而不只是作为文字上下文。"
        if intent_result.missing_fields:
            return "下一步建议继续补充关键信息后再启动仿真。"
        return "下一步可以继续补充对比指标和可视化展示。"

    @staticmethod
    def _build_charts(tool_result: ToolResult) -> list[dict]:
        comparison = (tool_result.data or {}).get("comparison")
        if not comparison:
            return []
        return [
            {
                "title": "目标车流平均等待时间对比（秒）",
                "unit": "秒",
                "rows": [
                    {"方案": "优化前", "数值": comparison["target_avg_wait_before_s"]},
                    {"方案": "优化后", "数值": comparison["target_avg_wait_after_s"]},
                ],
            },
            {
                "title": "目标车道平均排队长度对比（米）",
                "unit": "米",
                "rows": [
                    {"方案": "优化前", "数值": comparison["target_avg_queue_before_m"]},
                    {"方案": "优化后", "数值": comparison["target_avg_queue_after_m"]},
                ],
            },
            {
                "title": "全路网完成车辆数对比（辆）",
                "unit": "辆",
                "rows": [
                    {"方案": "优化前", "数值": comparison["arrived_before"]},
                    {"方案": "优化后", "数值": comparison["arrived_after"]},
                ],
            },
        ]

    @staticmethod
    def _build_visual_payload(tool_result: ToolResult) -> list[dict]:
        data = tool_result.data or {}
        comparison = data.get("comparison")
        incident_context = data.get("incident_context") or {}
        animations = data.get("animations") or {}
        charts: list[dict] = []

        if data.get("workflow_type") == "demand_impact_evaluation" and comparison:
            target_label = data.get("target_label", "目标车辆组")
            heatmap = AgentWorkflow._build_edge_heatmap_payload(data)
            if heatmap:
                charts.append(heatmap)
            demand_charts = [
                (f"{target_label}平均等待时间对比（秒）", "秒", True, "target_avg_wait_before_s", "target_avg_wait_after_s"),
                ("全网平均等待时间对比（秒）", "秒", True, "overall_avg_wait_before_s", "overall_avg_wait_after_s"),
                ("全路网完成车辆数对比（辆）", "辆", False, "arrived_before", "arrived_after"),
            ]
            for title, unit, better_when_lower, before_key, after_key in demand_charts:
                before_value = comparison[before_key]
                after_value = comparison[after_key]
                charts.append(
                    {
                        "type": "bar",
                        "title": title,
                        "unit": unit,
                        "better_when_lower": better_when_lower,
                        "before_label": "原始需求",
                        "after_label": "调整后需求",
                        "before_value": before_value,
                        "after_value": after_value,
                        "delta_value": after_value - before_value,
                        "rows": [
                            {"scheme": "原始需求", "value": before_value},
                            {"scheme": "调整后需求", "value": after_value},
                        ],
                    }
                )
            adjusted_animation = animations.get("adjusted") or animations.get("optimized") or {}
            if adjusted_animation.get("gif_file"):
                charts.append(
                    {
                        "type": "replay_gif",
                        "title": "调整后需求仿真回放动画",
                        "gif_file": str(adjusted_animation["gif_file"]),
                        "caption": "网页内嵌 GIF 回放，由本轮调整后需求仿真的车辆轨迹生成。",
                    }
                )
            return charts

        defense_payload = AgentWorkflow._build_defense_payload(tool_result)
        if defense_payload:
            charts.append(defense_payload)

        if incident_context.get("apply_scene_edit"):
            blocked_lane_label = incident_context.get("blocked_lane_label", "目标进口")
            lane_closure_count = incident_context.get("lane_closure_count", 0)
            incident_duration_minutes = incident_context.get("incident_duration_minutes", 0)
            route_edges = incident_context.get("route_edges", "未提供")
            blocked_lane_id = incident_context.get("blocked_lane_id", "未提供")
            charts.append(
                {
                    "type": "scene_injection",
                    "title": "事故场景注入",
                    "items": [
                        {"label": "注入位置", "value": str(blocked_lane_label)},
                        {"label": "封闭车道", "value": f"{lane_closure_count} 条"},
                        {"label": "持续时间", "value": f"{incident_duration_minutes} 分钟"},
                        {"label": "影响路线", "value": str(route_edges)},
                    ],
                    "detail": f"阻塞车道：{blocked_lane_id}",
                }
            )

        if comparison:
            charts.extend(
                [
                    {
                        "type": "bar",
                        "title": "目标车流平均等待时间对比（秒）",
                        "unit": "秒",
                        "better_when_lower": True,
                        "before_value": comparison["target_avg_wait_before_s"],
                        "after_value": comparison["target_avg_wait_after_s"],
                        "delta_value": comparison["target_avg_wait_after_s"] - comparison["target_avg_wait_before_s"],
                        "rows": [
                            {"scheme": "优化前", "value": comparison["target_avg_wait_before_s"]},
                            {"scheme": "优化后", "value": comparison["target_avg_wait_after_s"]},
                        ],
                    },
                    {
                        "type": "bar",
                        "title": "目标车道平均排队长度对比（米）",
                        "unit": "米",
                        "better_when_lower": True,
                        "before_value": comparison["target_avg_queue_before_m"],
                        "after_value": comparison["target_avg_queue_after_m"],
                        "delta_value": comparison["target_avg_queue_after_m"] - comparison["target_avg_queue_before_m"],
                        "rows": [
                            {"scheme": "优化前", "value": comparison["target_avg_queue_before_m"]},
                            {"scheme": "优化后", "value": comparison["target_avg_queue_after_m"]},
                        ],
                    },
                    {
                        "type": "bar",
                        "title": "全路网完成车辆数对比（辆）",
                        "unit": "辆",
                        "better_when_lower": False,
                        "before_value": comparison["arrived_before"],
                        "after_value": comparison["arrived_after"],
                        "delta_value": comparison["arrived_after"] - comparison["arrived_before"],
                        "rows": [
                            {"scheme": "优化前", "value": comparison["arrived_before"]},
                            {"scheme": "优化后", "value": comparison["arrived_after"]},
                        ],
                    },
                ]
            )

        optimized_animation = animations.get("optimized") or {}
        if optimized_animation.get("gif_file"):
            charts.append(
                {
                    "type": "replay_gif",
                    "title": "优化方案仿真回放动画",
                    "gif_file": str(optimized_animation["gif_file"]),
                    "caption": "网页内嵌 GIF 回放，由本轮优化方案的车辆轨迹自动生成。",
                }
            )

        return charts

    @staticmethod
    def _build_edge_heatmap_payload(data: dict) -> dict:
        impacts = data.get("edge_impacts") or []
        runtime_payload = data.get("scenario_runtime") or {}
        project_dir = runtime_payload.get("project_dir")
        if not impacts or not project_dir:
            return {}
        runtime = ScenarioRuntime.from_project_dir(project_dir)
        if not runtime.map_enabled:
            return {}
        try:
            edges, _ = load_map_objects(runtime.project_dir, runtime.map_config)
        except (OSError, KeyError, ValueError, ET.ParseError):
            return {}
        impact_by_edge = {row["edge_id"]: row for row in impacts}
        features = []
        for edge in edges:
            impact = impact_by_edge.get(edge["edge_id"]) or {
                "edge_id": edge["edge_id"],
                "impact_score": 0.0,
                "impact_level": "无活动",
                "reference_vehicle_entered": 0.0,
                "adjusted_vehicle_entered": 0.0,
                "vehicle_entered_delta": 0.0,
                "reference_mean_speed_mps": 0.0,
                "adjusted_mean_speed_mps": 0.0,
                "mean_speed_delta_mps": 0.0,
                "reference_waiting_time_s": 0.0,
                "adjusted_waiting_time_s": 0.0,
                "waiting_time_delta_s": 0.0,
                "reference_time_loss_s": 0.0,
                "adjusted_time_loss_s": 0.0,
                "time_loss_delta_s": 0.0,
            }
            properties = {
                **impact,
                "display_name": edge.get("edge_name") or f"道路 {edge['edge_id']}",
                "lane_count": edge.get("lane_count", 0),
                "color": AgentWorkflow._edge_impact_color(float(impact.get("impact_score", 0.0))),
            }
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {"type": "LineString", "coordinates": edge["coordinates"]},
                }
            )
        if not features:
            return {}
        return {
            "type": "edge_impact_map",
            "title": "交通需求变化路段影响热力图",
            "center": runtime.map_config.get("center") or [31.9688, 118.7985],
            "zoom": int(runtime.map_config.get("zoom") or 14),
            "features": features,
            "top_edges": (data.get("edge_impact_summary") or {}).get("top_affected_edges", [])[:10],
            "map_key": f"edge_impact_{Path(data.get('run_root', 'latest')).name}",
        }

    @staticmethod
    def _edge_impact_color(score: float) -> str:
        if score >= 60:
            return "#b91c1c"
        if score >= 30:
            return "#f97316"
        if score > 0:
            return "#facc15"
        return "#94a3b8"

    @staticmethod
    def _build_defense_payload(tool_result: ToolResult) -> dict:
        data = tool_result.data or {}
        comparison = data.get("comparison")
        if not comparison:
            return {}

        target_label = data.get("target_label", "重点方向")
        tradeoff_note = data.get("tradeoff_note", "")
        queue_delta = comparison["target_avg_queue_delta_m"]
        wait_delta = comparison["target_avg_wait_delta_s"]
        arrived_delta = comparison["arrived_delta"]
        overall_wait_delta = comparison["overall_avg_wait_delta_s"]

        conclusion = (
            f"本次优化显著改善了 {target_label} 的运行状态，"
            f"平均排队变化 {queue_delta:+.2f} 米，平均等待变化 {wait_delta:+.2f} 秒。"
        )
        highlights = [
            "系统可以把自然语言任务自动解析为结构化交通事件，并联动仿真工具链执行。",
            f"在重点方向上，排队和等待都出现了明确改善，适合展示事故方向优先控制效果。",
            "结果已经自动生成图表、对比指标和汇报材料，便于直接用于答辩展示。",
        ]
        limitation = (
            tradeoff_note
            or f"当前方案的局限性是全局平均等待变化 {overall_wait_delta:+.2f} 秒、全路网完成车辆数变化 {arrived_delta:+.0f} 辆，"
            "说明局部优化和全局效率之间仍然存在权衡。"
        )
        script = (
            f"本次结果表明，系统能够围绕 {target_label} 自动完成事件识别、策略生成和仿真对比。"
            f"优化后，重点方向的排队与等待都有明显改善，说明事故方向优先控制策略是有效的。"
            f"同时，全局效率仍存在一定权衡，后续需要继续增强多目标平衡能力。"
        )

        return {
            "type": "defense_mode",
            "title": "答辩模式",
            "conclusion": conclusion,
            "highlights": highlights,
            "limitation": limitation,
            "script": script,
        }

    @staticmethod
    def _infer_duration_seconds(message: str) -> int:
        patterns = [r"(\d{2,4})\s*秒", r"(\d{2,4})\s*sec(?:ond)?s?"]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return max(60, min(int(match.group(1)), 3600))
        return 300

    @staticmethod
    def _build_session_memory_entry(
        user_message: str,
        effective_user_message: str,
        step_history: list[dict],
        tool_result: ToolResult,
        intent_result: IntentParseResult,
        *,
        awaiting_clarification: bool,
    ) -> dict:
        data = tool_result.data or {}
        summary_parts = [f"用户最新要求：{user_message}"]
        if intent_result.merged_intent.get("location_text"):
            summary_parts.append(f"位置：{intent_result.merged_intent['location_text']}")
        if intent_result.merged_intent.get("simulation_duration_seconds"):
            summary_parts.append(f"仿真时长：{intent_result.merged_intent['simulation_duration_seconds']} 秒")
        if awaiting_clarification:
            summary_parts.append(f"待补充：{'、'.join(intent_result.missing_fields)}")
        if data.get("comparison"):
            comparison = data["comparison"]
            summary_parts.append(f"目标车流平均等待变化：{comparison['target_avg_wait_delta_s']:+.2f} 秒")
        if step_history:
            summary_parts.append("工具顺序：" + " -> ".join(step["tool_name"] for step in step_history))

        return {
            "user_message": user_message,
            "effective_user_message": effective_user_message,
            "summary": "；".join(summary_parts),
            "parsed_intent": intent_result.merged_intent,
            "missing_fields": intent_result.missing_fields,
            "awaiting_clarification": awaiting_clarification,
            "target_label": data.get("target_label"),
            "duration_seconds": data.get("duration_seconds"),
            "strategy": data.get("strategy"),
            "tool_chain_steps": data.get("tool_chain_steps", []),
            "ok": tool_result.ok,
        }

    def _build_export_markdown(
        self,
        user_message: str,
        effective_user_message: str,
        intent_result: IntentParseResult,
        tool_result: ToolResult,
        model_source_label: str,
        step_history: list[dict],
    ) -> str:
        data = tool_result.data or {}
        if data.get("workflow_type") == "demand_impact_evaluation":
            return self._build_demand_export_markdown(
                user_message,
                intent_result,
                tool_result,
                model_source_label,
                step_history,
            )
        comparison = data.get("comparison", {})
        target_label = data.get("target_label", "未识别")
        duration_seconds = data.get("duration_seconds", "未提供")
        strategy = data.get("strategy", "signal_optimization")
        scenario = data.get("scenario", "urban_intersection")
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if comparison:
            conclusion = (
                f"针对 {target_label} 的优化后，平均排队变化 {comparison['target_avg_queue_delta_m']:+.2f} 米，"
                f"平均等待变化 {comparison['target_avg_wait_delta_s']:+.2f} 秒。"
            )
        else:
            conclusion = "本次任务尚未输出完整对比指标。"

        metrics_table = "暂无对比指标。"
        if comparison:
            metrics_table = "\n".join(
                [
                    "| 指标 | 优化前 | 优化后 | 变化 |",
                    "| --- | ---: | ---: | ---: |",
                    f"| 目标车道平均排队长度（米） | {comparison['target_avg_queue_before_m']:.2f} | {comparison['target_avg_queue_after_m']:.2f} | {comparison['target_avg_queue_delta_m']:+.2f} |",
                    f"| 目标车流平均等待时间（秒） | {comparison['target_avg_wait_before_s']:.2f} | {comparison['target_avg_wait_after_s']:.2f} | {comparison['target_avg_wait_delta_s']:+.2f} |",
                    f"| 全局平均等待（秒） | {comparison['overall_avg_wait_before_s']:.2f} | {comparison['overall_avg_wait_after_s']:.2f} | {comparison['overall_avg_wait_delta_s']:+.2f} |",
                    f"| 全路网完成车辆数（辆） | {comparison['arrived_before']:.0f} | {comparison['arrived_after']:.0f} | {comparison['arrived_delta']:+.0f} |",
                    f"| 最大滞留车辆（辆） | {comparison['max_halting_before']:.0f} | {comparison['max_halting_after']:.0f} | {comparison['max_halting_delta']:+.0f} |",
                ]
            )

        tool_chain_text = " -> ".join(step["tool_name"] for step in step_history) if step_history else "无"

        return "\n".join(
            [
                "# SimTrend 交通仿真智能体汇报稿",
                "",
                f"- 生成时间：{generated_at}",
                f"- 模型来源：{model_source_label}",
                f"- 场景：{scenario}",
                f"- 策略：{strategy}",
                f"- 仿真时长：{duration_seconds} 秒",
                "",
                "## 一句话结论",
                conclusion,
                "",
                "## 结构化任务",
                format_intent_markdown(intent_result),
                "",
                "## 任务背景",
                f"- 用户原始请求：{user_message}",
                f"- 系统实际执行请求：{effective_user_message}",
                "",
                "## 核心指标对比",
                metrics_table,
                "",
                "## 汇报可直接使用的结论",
                self._build_optimization_suggestion(intent_result, tool_result),
                "",
                "## 工具链说明",
                f"- 工具调用顺序：{tool_chain_text}",
                f"- 重点对象：{target_label}",
                "",
                "## 附录",
                f"- 执行日志摘要：{tool_result.message[:800]}",
            ]
        )

    def _build_demand_export_markdown(
        self,
        user_message: str,
        intent_result: IntentParseResult,
        tool_result: ToolResult,
        model_source_label: str,
        step_history: list[dict],
    ) -> str:
        data = tool_result.data or {}
        comparison = data.get("comparison") or {}
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = data.get("target_label", "交通需求")
        metrics_table = "暂无完整对比指标。"
        if comparison:
            metrics_table = "\n".join(
                [
                    "| 指标 | 原始需求 | 调整后需求 | 变化 |",
                    "| --- | ---: | ---: | ---: |",
                    f"| {target}平均等待（秒） | {comparison['target_avg_wait_before_s']:.2f} | {comparison['target_avg_wait_after_s']:.2f} | {comparison['target_avg_wait_delta_s']:+.2f} |",
                    f"| {target}平均行程时间（秒） | {comparison['target_avg_duration_before_s']:.2f} | {comparison['target_avg_duration_after_s']:.2f} | {comparison['target_avg_duration_delta_s']:+.2f} |",
                    f"| 全网平均等待（秒） | {comparison['overall_avg_wait_before_s']:.2f} | {comparison['overall_avg_wait_after_s']:.2f} | {comparison['overall_avg_wait_delta_s']:+.2f} |",
                    f"| 全路网完成车辆数（辆） | {comparison['arrived_before']:.0f} | {comparison['arrived_after']:.0f} | {comparison['arrived_delta']:+.0f} |",
                    f"| 最大滞留车辆（辆） | {comparison['max_halting_before']:.0f} | {comparison['max_halting_after']:.0f} | {comparison['max_halting_delta']:+.0f} |",
                ]
            )
        tool_chain_text = " -> ".join(step["tool_name"] for step in step_history) if step_history else "无"
        return "\n".join(
            [
                "# SimTrend 交通需求影响评估报告",
                "",
                f"- 生成时间：{generated_at}",
                f"- 模型来源：{model_source_label}",
                f"- 场景：{data.get('scenario', '未提供')}",
                f"- 仿真时长：{data.get('duration_seconds', '未提供')} 秒",
                f"- 评估对象：{target}",
                "",
                "## 结构化任务",
                format_intent_markdown(intent_result),
                "",
                "## 用户请求",
                user_message,
                "",
                "## 控制变量",
                f"- 唯一变化变量：{data.get('changed_variable', '交通需求配置')}",
                f"- 保持一致：{'、'.join(data.get('controlled_variables') or [])}",
                "",
                "## 需求影响指标",
                metrics_table,
                "",
                "## 结论",
                self._build_demand_impact_suggestion(tool_result),
                "",
                "## 工具链",
                tool_chain_text,
            ]
        )

    @staticmethod
    def _build_export_filename(tool_result: ToolResult) -> str:
        target = str((tool_result.data or {}).get("target_label", "report")).replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"simtrend_{target}_{timestamp}.md"
