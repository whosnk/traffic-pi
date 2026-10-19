from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simtrend_app.agent.intent_parser import (
    IntentParseResult,
    build_clarification_markdown,
    build_suggested_reply,
    parse_intent,
)


_EXPLICIT_NEW_TASK_MARKERS = (
    "开始一个新任务",
    "开始新任务",
    "新任务：",
    "新任务:",
    "另外一个任务",
    "另一个任务",
    "重新开始",
    "忽略之前",
)

_FOLLOW_UP_PREFIXES = (
    "那",
    "那就",
    "那再",
    "再",
    "改成",
    "改为",
    "调整",
    "只看",
    "只比较",
    "只保留",
    "继续",
    "然后",
    "补充",
    "重新",
    "汇报",
    "总结",
    "生成",
)


@dataclass(frozen=True)
class TaskSafetyReview:
    intent: IntentParseResult
    explicit_new_task: bool

    @property
    def requires_clarification(self) -> bool:
        return self.intent.should_clarify

    def clarification_payload(self, scenario_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "clarification_required",
            "scenario_id": scenario_id,
            "message": "\n\n".join(
                [
                    build_clarification_markdown(self.intent),
                    build_suggested_reply(self.intent),
                ]
            ),
            "missing_fields": list(self.intent.missing_fields),
            "questions": list(self.intent.clarification_questions),
            "simulation_started": False,
        }


def is_explicit_new_task(message: str) -> bool:
    normalized = "".join(str(message or "").lower().split())
    return any(marker in normalized for marker in _EXPLICIT_NEW_TASK_MARKERS)


def isolate_conversation_memory(
    message: str,
    conversation_memory: list[dict] | None,
) -> list[dict]:
    if is_explicit_new_task(message):
        return []
    return list(conversation_memory or [])


def looks_like_new_task(message: str) -> bool:
    if is_explicit_new_task(message):
        return True

    lowered = message.lower()
    stripped = message.strip()
    if any(stripped.startswith(prefix) for prefix in _FOLLOW_UP_PREFIXES):
        return False

    follow_up_markers = (*_FOLLOW_UP_PREFIXES, "duration", "compare", "report")
    strong_new_task_markers = ("事故", "追尾", "碰撞", "intersection", "incident")
    has_follow_up = any(marker in stripped or marker in lowered for marker in follow_up_markers)
    has_strong_new_task = any(marker in stripped or marker in lowered for marker in strong_new_task_markers)
    if has_follow_up and not has_strong_new_task:
        return False
    return True


def review_task_intent(
    message: str,
    conversation_memory: list[dict] | None = None,
    *,
    task_route: dict | None = None,
    is_follow_up: bool | None = None,
) -> TaskSafetyReview:
    memory = isolate_conversation_memory(message, conversation_memory)
    if is_follow_up is None:
        pending_clarification = any(item.get("awaiting_clarification") for item in memory[-3:])
        is_follow_up = pending_clarification or (not looks_like_new_task(message) and bool(memory))

    intent = parse_intent(
        message,
        memory,
        is_follow_up=is_follow_up,
        task_route=task_route,
    )
    return TaskSafetyReview(
        intent=intent,
        explicit_new_task=is_explicit_new_task(message),
    )
