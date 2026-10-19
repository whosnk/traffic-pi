from __future__ import annotations

import argparse
from typing import Any

from mcp.server import MCPServer

from simtrend_app.integration import MCPFacade, submit, read_job, public_job, map_data
from simtrend_app.incident_drafts import prepare_incident_draft


mcp = MCPServer(
    "SimTrend Traffic Simulation",
    instructions=(
        "SimTrend 提供交通路网查询、信号控制查询、事故信号优化、交通需求影响评估、"
        "参数化信号仿真和结果诊断能力。执行仿真前应先确认 scenario_id 和空间对象。"
        "长耗时仿真优先使用 submit_simtrend_task，再用 get_simtrend_task 查询；"
        "queued/running 不代表成功，不得编造指标。结果中的回放链接由 Traffic Pi 提供。"
        "在 Traffic Pi 中创建或修改事故任务时，先调用 prepare_incident_task_draft 生成可编辑草案，等待用户在任务面板确认运行。"
    ),
)
service = MCPFacade()


@mcp.tool()
def prepare_incident_task_draft(scenario_id: str, fields: dict[str, Any], base_revision: int = 0) -> dict[str, Any]:
    """生成或修改事故信号优化草案，不运行仿真。fields 仅允许 edge_id、lane_id、zone_id、incident_type（追尾事故/碰撞事故/车辆抛锚）、incident_duration_minutes（1-180整数）、lane_closure_count（1-8整数）、objective（优先缓解排队/优先降低等待时间）、duration_seconds（60-3600整数）。仅填写用户明确提供或当前定位/草案中已有的值，未知项为 null，不猜测道路、车道或默认时长。修改时将当前草案与明确修改合并后传入完整 fields；base_revision 使用本条消息空间上下文的 revision。返回后提醒用户在中间任务面板编辑和确认，不调用执行工具。"""
    return prepare_incident_draft(scenario_id, fields, base_revision)


@mcp.tool()
def submit_simtrend_task(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """提交长耗时仿真任务并立即返回任务编号。通过 get_simtrend_task 查询进度和结果，避免调用超时。"""
    return submit(tool, arguments)


@mcp.tool()
def get_simtrend_task(job_id: str) -> dict[str, Any]:
    """查询任务进度、澄清信息、结果和网页回放链接；queued/running 均不表示仿真完成。"""
    return public_job(read_job(job_id))


@mcp.tool()
def get_simtrend_map(scenario_id: str) -> dict[str, Any]:
    """获取场景道路、车道与上客区空间数据。四交叉口为示意坐标，南京南站为地理坐标。"""
    return map_data(scenario_id)


@mcp.tool()
def list_simtrend_scenarios() -> dict[str, Any]:
    """列出可供查询和仿真的 SimTrend 场景及其能力。"""
    return service.list_scenarios()


@mcp.tool()
def get_simtrend_capabilities(scenario_id: str = "") -> dict[str, Any]:
    """获取 SimTrend 业务工具、内部工具链和指定场景能力。"""
    return service.get_capabilities(scenario_id)


@mcp.tool()
def query_network_knowledge(scenario_id: str, query: str) -> dict[str, Any]:
    """查询场景中的路口、道路、车道、连接关系、上客区和最近仿真指标。"""
    return service.query_network_knowledge(scenario_id, query)


@mcp.tool()
def query_signal_control(
    scenario_id: str,
    query: str = "",
    controller_id: str = "",
    edge_id: str = "",
    lane_id: str = "",
    program_id: str = "0",
) -> dict[str, Any]:
    """查询信号控制器、相位时长、受控道路车道和放行连接。"""
    return service.query_signal_control(
        scenario_id,
        query=query,
        controller_id=controller_id,
        edge_id=edge_id,
        lane_id=lane_id,
        program_id=program_id,
    )


@mcp.tool()
def run_incident_signal_optimization(
    scenario_id: str,
    incident_text: str,
    duration_seconds: int = 600,
    strategy: str = "signal_optimization",
) -> dict[str, Any]:
    """运行事故识别、封道预检、基线与优化仿真、指标对比和报告生成工作流。"""
    return service.run_incident_signal_optimization(
        scenario_id,
        incident_text,
        duration_seconds=duration_seconds,
        strategy=strategy,
    )


@mcp.tool()
def run_demand_impact_evaluation(
    scenario_id: str,
    request_text: str,
    duration_seconds: int = 600,
) -> dict[str, Any]:
    """运行交通需求调整前后的两次仿真并评估需求变化影响。"""
    return service.run_demand_impact_evaluation(
        scenario_id,
        request_text,
        duration_seconds=duration_seconds,
    )


@mcp.tool()
def evaluate_parameterized_signal_plan(
    scenario_id: str,
    controller_id: str,
    phase_durations: list[float],
    duration_seconds: int = 600,
    random_seed: int = 42,
    program_id: str = "0",
    render_animation: bool = False,
    result_slot: str = "latest",
) -> dict[str, Any]:
    """校验并真实运行指定控制器和完整相位时长的单方案仿真。"""
    return service.evaluate_signal_plan(
        scenario_id,
        controller_id,
        phase_durations,
        duration_seconds=duration_seconds,
        random_seed=random_seed,
        program_id=program_id,
        render_animation=render_animation,
        result_slot=result_slot,
    )


@mcp.tool()
def diagnose_simulation_result(
    scenario_id: str,
    variant: str = "latest",
    top_n: int = 5,
) -> dict[str, Any]:
    """诊断指定场景最近一次仿真的瓶颈道路、异常证据和拥堵传播方向。"""
    return service.diagnose_simulation_result(scenario_id, variant=variant, top_n=top_n)


@mcp.tool()
def compare_simulation_runs(
    scenario_id: str,
    reference: str = "reference",
    candidate: str = "candidate",
    top_n: int = 5,
) -> dict[str, Any]:
    """检查两次仿真的可比性，并比较全网和重点道路指标。"""
    return service.compare_simulation_runs(
        scenario_id,
        reference=reference,
        candidate=candidate,
        top_n=top_n,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SimTrend MCP Server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport. Use stdio for a local host and streamable-http for integration testing.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
        return
    mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
