import asyncio
import json
from dataclasses import dataclass

from simtrend_app.config import Settings
from simtrend_app.mcp_agent_client import (
    MCPToolAgent,
    _parse_arguments,
    _tool_definition,
)
from simtrend_app.task_safety import is_explicit_new_task
from mcp_agent_client import _format_exception


@dataclass
class FakeTool:
    name: str = "query_network_knowledge"
    description: str = "查询路网"
    input_schema: dict | None = None

    def __post_init__(self) -> None:
        if self.input_schema is None:
            self.input_schema = {
                "type": "object",
                "properties": {"scenario_id": {"type": "string"}},
                "required": ["scenario_id"],
            }


class FakeListResult:
    tools = [FakeTool()]


class FakeCallResult:
    structured_content = {"ok": True, "intersections": ["西北路口"]}


class FakeMCPClient:
    def __init__(self) -> None:
        self.calls = []

    async def list_tools(self):
        return FakeListResult()

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return FakeCallResult()


class FakeResponse:
    def __init__(self, message):
        self.message = message

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": self.message}]}


def _settings() -> Settings:
    return Settings("secret", "https://model.example", "demo-model", ".", False, False, False, 1800)


def test_tool_definition_uses_mcp_json_schema() -> None:
    definition = _tool_definition(FakeTool())

    assert definition["function"]["name"] == "query_network_knowledge"
    assert definition["function"]["parameters"]["required"] == ["scenario_id"]


def test_parse_arguments_rejects_non_object_json() -> None:
    arguments, error = _parse_arguments("[]")

    assert arguments == {}
    assert "JSON 对象" in error


def test_agent_discovers_calls_and_summarizes_mcp_tool(monkeypatch) -> None:
    responses = iter(
        [
            FakeResponse(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "query_network_knowledge",
                                "arguments": json.dumps({"scenario_id": "four_intersections"}),
                            },
                        }
                    ],
                }
            ),
            FakeResponse({"content": "场景包含西北路口。"}),
        ]
    )
    payloads = []

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return next(responses)

    monkeypatch.setattr("simtrend_app.mcp_agent_client.requests.post", fake_post)
    client = FakeMCPClient()
    agent = MCPToolAgent(_settings())

    answer = asyncio.run(agent.run_turn("有哪些路口？", client))

    assert answer.text == "场景包含西北路口。"
    assert client.calls == [("query_network_knowledge", {"scenario_id": "four_intersections"})]
    assert answer.tool_calls[0]["result"]["ok"]
    assert payloads[0]["tools"][0]["function"]["name"] == "query_network_knowledge"
    assert payloads[1]["messages"][-1]["role"] == "tool"


def test_information_request_can_finish_without_calling_tool(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return FakeResponse({"content": "请先说明要查询哪个场景。"})

    monkeypatch.setattr("simtrend_app.mcp_agent_client.requests.post", fake_post)
    client = FakeMCPClient()

    answer = asyncio.run(MCPToolAgent(_settings()).run_turn("查一下路网", client))

    assert answer.tool_calls == []
    assert client.calls == []


def test_nested_connection_error_is_readable() -> None:
    error = ExceptionGroup("connection failed", [ConnectionRefusedError("拒绝连接")])

    rendered = _format_exception(error)

    assert "ConnectionRefusedError" in rendered
    assert "拒绝连接" in rendered


def test_mcp_error_code_is_included_when_available() -> None:
    error = RuntimeError("server response")
    error.code = -32600

    rendered = _format_exception(error)

    assert "code=-32600" in rendered


def test_explicit_new_task_marker_is_detected() -> None:
    assert is_explicit_new_task("开始一个新任务：东进口发生事故")
    assert not is_explicit_new_task("继续查询东北路口")


def test_new_task_does_not_send_previous_conversation_to_model(monkeypatch) -> None:
    payloads = []

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return FakeResponse({"content": "请先说明具体路口。"})

    monkeypatch.setattr("simtrend_app.mcp_agent_client.requests.post", fake_post)
    client = FakeMCPClient()
    history = [
        {"role": "user", "content": "查询东北路口"},
        {"role": "assistant", "content": "东北路口编号是 c10"},
    ]

    asyncio.run(
        MCPToolAgent(_settings()).run_turn(
            "开始一个新任务：东进口发生事故，请优化",
            client,
            history=history,
        )
    )

    contents = [item.get("content") for item in payloads[0]["messages"]]
    assert "东北路口编号是 c10" not in contents
