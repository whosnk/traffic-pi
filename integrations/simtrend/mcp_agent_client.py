from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from simtrend_app.config import get_settings
from simtrend_app.mcp_agent_client import MCPAgentError, MCPToolAgent
from simtrend_app.task_safety import is_explicit_new_task


def _event(message: str) -> None:
    print(f"\n[{message}]", flush=True)


async def _run(
    server_url: str,
    query: str,
    max_tool_calls: int,
    *,
    transport: str = "stdio",
    list_tools_only: bool = False,
) -> None:
    try:
        from mcp import Client, StdioServerParameters
    except ImportError as exc:
        raise MCPAgentError("当前环境未安装 MCP SDK，请先执行 pip install -r requirements.txt。") from exc

    settings = get_settings()
    agent = MCPToolAgent(settings, max_tool_calls=max_tool_calls)
    history: list[dict[str, str]] = []

    if transport == "stdio":
        project_root = Path(__file__).resolve().parent
        server_target: Any = StdioServerParameters(
            command=sys.executable,
            args=[str(project_root / "mcp_server.py")],
            cwd=project_root,
            env=dict(os.environ),
        )
        print("正在启动本地 SimTrend MCP（stdio）……")
    else:
        server_target = server_url
        print(f"正在连接 SimTrend MCP：{server_url}")

    connection_attempts = 3
    for attempt in range(1, connection_attempts + 1):
        discovery_complete = False
        try:
            async with Client(server_target, read_timeout_seconds=3600) as client:
                tools = await client.list_tools()
                discovery_complete = True
                print(f"连接成功，发现 {len(tools.tools)} 个工具。当前模型：{settings.qwen_model}")
                if list_tools_only:
                    for tool in tools.tools:
                        print(f"- {tool.name}: {tool.description or ''}")
                    return

                if query:
                    await _run_one(agent, client, query, history)
                    return

                print("输入自然语言任务；输入 exit 或 quit 退出。")
                while True:
                    try:
                        user_message = input("\n你：").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n会话结束。")
                        return
                    if user_message.lower() in {"exit", "quit", "退出"}:
                        print("会话结束。")
                        return
                    if not user_message:
                        continue
                    if is_explicit_new_task(user_message) and history:
                        history.clear()
                        print("已识别为新任务，不继承上一轮场景和空间对象。")
                    answer = await _run_one(agent, client, user_message, history)
                    history.extend(
                        [
                            {"role": "user", "content": user_message},
                            {"role": "assistant", "content": answer},
                        ]
                    )
                    history[:] = history[-8:]
        except Exception as exc:
            if discovery_complete or attempt >= connection_attempts:
                raise
            print(
                f"MCP 连接握手失败（第 {attempt}/{connection_attempts} 次）："
                f"{_format_exception(exc)}"
            )
            print("1 秒后重新连接……")
            await asyncio.sleep(1)


async def _run_one(
    agent: MCPToolAgent,
    client: Any,
    user_message: str,
    history: list[dict[str, str]],
) -> str:
    answer = await agent.run_turn(user_message, client, history=history, on_event=_event)
    print(f"\n智能体：{answer.text}")
    if answer.tool_calls:
        names = "、".join(item["name"] for item in answer.tool_calls)
        print(f"\n本轮 MCP 调用：{names}")
    else:
        print("\n本轮未调用 MCP 工具。")
    return answer.text


def main() -> None:
    parser = argparse.ArgumentParser(description="SimTrend 大模型 MCP 客户端示例")
    parser.add_argument("query", nargs="*", help="可选：直接执行一条自然语言请求")
    parser.add_argument(
        "--server-url",
        default=os.getenv("SIMTREND_MCP_URL", "http://127.0.0.1:8765/mcp"),
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("SIMTREND_MCP_TRANSPORT", "stdio"),
        help="本地使用 stdio；连接独立服务时使用 streamable-http。",
    )
    parser.add_argument("--max-tool-calls", type=int, default=4)
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="只连接 MCP 服务并列出工具，不请求大模型。",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            _run(
                args.server_url,
                " ".join(args.query).strip(),
                args.max_tool_calls,
                transport=args.transport,
                list_tools_only=args.list_tools,
            )
        )
    except MCPAgentError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"连接或执行失败：{_format_exception(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc


def _format_exception(exc: BaseException) -> str:
    nested = getattr(exc, "exceptions", None)
    if nested:
        details = "; ".join(_format_exception(item) for item in nested)
        return f"{type(exc).__name__}: {details}"
    message = str(exc).strip()
    code = getattr(exc, "code", None)
    data = getattr(exc, "data", None)
    details = f"{type(exc).__name__}"
    if code is not None:
        details += f"(code={code})"
    if message:
        details += f": {message}"
    if data is not None:
        details += f"; data={data}"
    return details


if __name__ == "__main__":
    main()
