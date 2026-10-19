from __future__ import annotations

import re
from dataclasses import dataclass, field


CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


@dataclass
class IntentParseResult:
    current_intent: dict
    merged_intent: dict
    inherited_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    should_clarify: bool = False


def parse_intent(
    user_message: str,
    conversation_memory: list[dict] | None = None,
    *,
    is_follow_up: bool,
    task_route: dict | None = None,
) -> IntentParseResult:
    conversation_memory = conversation_memory or []
    current_intent = _extract_intent(user_message, task_route=task_route)
    historical_intents = [
        item.get("parsed_intent", {})
        for item in conversation_memory
        if item.get("parsed_intent")
    ]

    if is_follow_up and historical_intents:
        merged_intent = _merge_intents(historical_intents[-3:], current_intent)
    else:
        merged_intent = dict(current_intent)

    inherited_fields = [
        key
        for key, value in merged_intent.items()
        if not _is_empty(value) and _is_empty(current_intent.get(key))
    ]

    missing_fields = _build_missing_fields(merged_intent)
    clarification_questions = _build_clarification_questions(merged_intent, missing_fields)
    should_clarify = bool(clarification_questions)

    return IntentParseResult(
        current_intent=current_intent,
        merged_intent=merged_intent,
        inherited_fields=inherited_fields,
        missing_fields=missing_fields,
        clarification_questions=clarification_questions,
        should_clarify=should_clarify,
    )


def format_intent_markdown(result: IntentParseResult) -> str:
    intent = result.merged_intent
    if intent.get("task_type") == "demand_adjustment":
        lines = [
            f"- 任务类型：{intent.get('task_type_label', '交通需求调整仿真')}",
            f"- 调整对象：{intent.get('demand_target_label', '未明确')}",
            f"- 调整倍率：{intent.get('demand_multiplier', '未明确')}",
            f"- 仿真时长：{intent.get('simulation_duration_seconds') or 300} 秒",
        ]
        if intent.get("demand_profile_label"):
            lines.append(f"- 交通需求强度：{intent['demand_profile_label']}")
        if intent.get("demand_window_start_s") is not None and intent.get("demand_window_end_s") is not None:
            lines.append(f"- 调整时间窗：{intent['demand_window_start_s']}-{intent['demand_window_end_s']} 秒")
        if intent.get("demand_spatial_scope_label"):
            lines.append(f"- 空间范围：{intent['demand_spatial_scope_label']}")
        if result.inherited_fields:
            lines.append(f"- 继承字段：{'、'.join(result.inherited_fields)}")
        return "\n".join(lines)

    lines = [
        f"- 任务类型：{intent.get('task_type_label', '交通信号优化仿真')}",
        f"- 事故类型：{intent.get('incident_type_label', '未明确')}",
        f"- 事故位置：{intent.get('location_text', '未明确')}",
        f"- 仿真时长：{intent.get('simulation_duration_seconds', '未明确')} 秒"
        if intent.get("simulation_duration_seconds")
        else "- 仿真时长：未明确",
        f"- 事故持续时间：{intent.get('incident_duration_minutes', '未明确')} 分钟"
        if intent.get("incident_duration_minutes")
        else "- 事故持续时间：未明确",
        f"- 封闭车道数：{intent.get('lane_closure_count', '未明确')}"
        if intent.get("lane_closure_count")
        else "- 封闭车道数：未明确",
        f"- 优化目标：{intent.get('priority_objective_label', '未明确')}",
    ]

    compare_scope = intent.get("compare_scope") or []
    if compare_scope:
        lines.append(f"- 对比范围：{'、'.join(compare_scope)}")
    time_period = intent.get("time_period_label")
    if time_period:
        lines.append(f"- 时段特征：{time_period}")
    vehicle_priority = intent.get("vehicle_priority_label")
    if vehicle_priority:
        lines.append(f"- 优先对象：{vehicle_priority}")
    demand_profile = intent.get("demand_profile_label")
    if demand_profile:
        lines.append(f"- 交通需求强度：{demand_profile}")
    if result.inherited_fields:
        lines.append(f"- 继承字段：{'、'.join(result.inherited_fields)}")

    return "\n".join(lines)


def build_structured_prompt(user_message: str, result: IntentParseResult) -> str:
    intent = result.merged_intent
    if intent.get("task_type") == "demand_adjustment":
        lines = [
            f"用户原始请求：{user_message}",
            "结构化任务解析：",
            f"- 任务类型：{intent.get('task_type_label', '交通需求调整仿真')}",
            f"- 需求调整对象：{intent.get('demand_target')}",
            f"- 需求调整对象名称：{intent.get('demand_target_label')}",
            f"- 仿真时长：{intent.get('simulation_duration_seconds') or 300} 秒",
        ]
        if intent.get("demand_multiplier") is not None:
            lines.append(f"- 自定义需求倍率：{float(intent['demand_multiplier']):.4f}")
        elif intent.get("demand_profile_label"):
            lines.append(f"- 交通需求强度：{intent['demand_profile_label']}")
        if intent.get("demand_window_start_s") is not None and intent.get("demand_window_end_s") is not None:
            lines.append(f"- 需求调整时间窗：{intent['demand_window_start_s']}-{intent['demand_window_end_s']} 秒")
        if intent.get("demand_spatial_scope"):
            lines.append(f"- 需求调整空间范围：{intent['demand_spatial_scope']}")
            lines.append(f"- 需求调整空间名称：{intent['demand_spatial_scope_label']}")
        lines.append("请在调整后的交通需求下运行基线与优化仿真并进行指标对比。")
        return "\n".join(lines)

    lines = [
        f"用户原始请求：{user_message}",
        "结构化任务解析：",
        f"- 任务类型：{intent.get('task_type_label', '交通信号优化仿真')}",
        f"- 事故类型：{intent.get('incident_type_label', '未明确')}",
        f"- 事故位置：{intent.get('location_text', '未明确')}",
        f"- 仿真时长：{intent.get('simulation_duration_seconds', 300)} 秒",
        f"- 优化目标：{intent.get('priority_objective_label', '缓解排队与延误')}",
    ]
    if intent.get("incident_duration_minutes"):
        lines.append(f"- 事故持续时间：{intent['incident_duration_minutes']} 分钟")
    if intent.get("lane_closure_count"):
        lines.append(f"- 封闭车道数：{intent['lane_closure_count']}")
    if intent.get("compare_scope"):
        lines.append(f"- 对比范围：{'、'.join(intent['compare_scope'])}")
    if intent.get("time_period_label"):
        lines.append(f"- 时段特征：{intent['time_period_label']}")
    if intent.get("vehicle_priority_label"):
        lines.append(f"- 优先对象：{intent['vehicle_priority_label']}")
    if intent.get("demand_profile_label"):
        lines.append(f"- 交通需求强度：{intent['demand_profile_label']}")
    lines.append("请基于以上结构化信息继续完成交通信号优化仿真。")
    return "\n".join(lines)


def build_clarification_markdown(result: IntentParseResult) -> str:
    if not result.clarification_questions:
        return ""
    lines = ["- 当前信息不足以启动可信仿真，请先补充以下内容："]
    lines.extend(f"- {question}" for question in result.clarification_questions)
    return "\n".join(lines)


def build_suggested_reply(result: IntentParseResult) -> str:
    intent = result.merged_intent
    if intent.get("task_type") == "demand_adjustment":
        return "可以直接回复：`把南京南站网约车到站流量提高30%，仿真600秒并进行对比`"

    location = intent.get("location_text") or "东北路口东进口"
    if _is_ambiguous_approach_location(location):
        location = _suggest_precise_location(location)
    incident_type = intent.get("incident_type_label") or "追尾事故"
    return (
        f"可以直接回复：`{location}发生{incident_type}，持续10分钟，封闭1条车道，"
        "优先缓解排队，仿真600秒`"
    )


def _extract_intent(user_message: str, *, task_route: dict | None = None) -> dict:
    lowered = user_message.lower()

    routed_task_type = (task_route or {}).get("task_type")
    if routed_task_type == "demand_adjustment":
        task_type = "demand_adjustment"
        task_type_label = "交通需求调整仿真"
    else:
        task_type = "signal_optimization_simulation"
        task_type_label = "交通信号优化仿真"

    incident_type, incident_type_label = _extract_incident_type(user_message, lowered)
    location_text = _extract_location(user_message)
    compare_scope = _extract_compare_scope(user_message)
    simulation_duration_seconds = _extract_simulation_duration_seconds(user_message)
    incident_duration_minutes = _extract_incident_duration_minutes(user_message)
    lane_closure_count = _extract_lane_closure_count(user_message)
    priority_objective, priority_objective_label = _extract_priority_objective(user_message, lowered)
    time_period, time_period_label = _extract_time_period(user_message, lowered)
    vehicle_priority, vehicle_priority_label = _extract_vehicle_priority(user_message, lowered)
    demand_profile, demand_profile_label = _extract_demand_profile(user_message, lowered)
    demand_target, demand_target_label = _extract_demand_target(user_message, lowered)
    demand_multiplier = _extract_demand_multiplier(user_message, lowered)
    demand_window_start_s, demand_window_end_s = _extract_demand_time_window(user_message)
    demand_spatial_scope, demand_spatial_scope_label = _extract_demand_spatial_scope(user_message)
    if demand_window_end_s is not None:
        simulation_duration_seconds = max(simulation_duration_seconds or 300, demand_window_end_s)
    if task_type == "demand_adjustment" and demand_target is None and demand_profile is not None:
        demand_target, demand_target_label = "all", "全部交通流量"

    return {
        "task_type": task_type,
        "task_type_label": task_type_label,
        "incident_type": incident_type,
        "incident_type_label": incident_type_label,
        "location_text": location_text,
        "compare_scope": compare_scope,
        "simulation_duration_seconds": simulation_duration_seconds,
        "incident_duration_minutes": incident_duration_minutes,
        "lane_closure_count": lane_closure_count,
        "priority_objective": priority_objective,
        "priority_objective_label": priority_objective_label,
        "time_period": time_period,
        "time_period_label": time_period_label,
        "vehicle_priority": vehicle_priority,
        "vehicle_priority_label": vehicle_priority_label,
        "demand_profile": demand_profile,
        "demand_profile_label": demand_profile_label,
        "demand_target": demand_target,
        "demand_target_label": demand_target_label,
        "demand_multiplier": demand_multiplier,
        "demand_window_start_s": demand_window_start_s,
        "demand_window_end_s": demand_window_end_s,
        "demand_spatial_scope": demand_spatial_scope,
        "demand_spatial_scope_label": demand_spatial_scope_label,
    }


def _merge_intents(history: list[dict], current: dict) -> dict:
    merged: dict = {}
    for intent in history:
        for key, value in intent.items():
            if not _is_empty(value):
                merged[key] = value
    for key, value in current.items():
        if not _is_empty(value):
            merged[key] = value
    return merged


def _build_missing_fields(intent: dict) -> list[str]:
    missing_fields: list[str] = []
    if intent.get("task_type") == "demand_adjustment":
        if _is_empty(intent.get("demand_target")):
            missing_fields.append("需求调整对象")
        if _is_empty(intent.get("demand_multiplier")) and _is_empty(intent.get("demand_profile")):
            missing_fields.append("需求调整幅度")
        return missing_fields

    if _is_empty(intent.get("incident_type")):
        missing_fields.append("事故类型")
    if _is_empty(intent.get("location_text")):
        missing_fields.append("事故位置/受影响进口")
    elif _is_ambiguous_approach_location(intent.get("location_text")):
        missing_fields.append("具体路口位置")

    is_capacity_reduction_incident = intent.get("incident_type") in {"rear_end", "collision", "breakdown"}
    if is_capacity_reduction_incident and _is_empty(intent.get("incident_duration_minutes")):
        missing_fields.append("事故持续时间")
    if is_capacity_reduction_incident and _is_empty(intent.get("lane_closure_count")):
        missing_fields.append("封闭车道数量")
    return missing_fields


def _build_clarification_questions(intent: dict, missing_fields: list[str]) -> list[str]:
    questions: list[str] = []
    if "需求调整对象" in missing_fields:
        questions.append("请问要调整哪类交通需求？例如网约车到站、网约车离站、背景社会车辆或全部流量。")
    if "需求调整幅度" in missing_fields:
        questions.append("请问流量需要提高或降低多少？例如提高30%、降低20%，也可以选择轻流量或高流量。")
    if "事故类型" in missing_fields:
        questions.append("请问是什么类型的交通事件？例如追尾、碰撞、抛锚或单纯拥堵。")
    if "事故位置/受影响进口" in missing_fields:
        questions.append("请问事故发生在哪个具体路口和进口？例如东北路口东进口、西南路口北进口。")
    if "具体路口位置" in missing_fields:
        location = intent.get("location_text", "该进口")
        questions.append(
            f"当前路网包含四个交叉口，`{location}` 还不够明确。"
            f"请补充具体路口，例如：{_candidate_precise_locations(location)}。"
        )
    if "事故持续时间" in missing_fields:
        questions.append("请问事故预计持续多久？例如 10 分钟、15 分钟。")
    if "封闭车道数量" in missing_fields:
        questions.append("请问是否封闭车道？如果有，封闭了几条车道？")
    return questions


def _extract_location(user_message: str) -> str | None:
    candidates = ["东进口", "西进口", "南进口", "北进口", "东向", "西向", "南向", "北向", "路口中央"]
    for candidate in candidates:
        if candidate in user_message:
            return candidate

    lowered = user_message.lower()
    english_map = {
        "east": "东进口",
        "west": "西进口",
        "south": "南进口",
        "north": "北进口",
    }
    for key, value in english_map.items():
        if key in lowered:
            return value
    return None


def _extract_compare_scope(user_message: str) -> list[str]:
    if not any(keyword in user_message for keyword in ["对比", "比较", "只看", "只比较"]):
        return []
    directions = []
    for direction in ["东进口", "西进口", "南进口", "北进口"]:
        if direction in user_message:
            directions.append(direction)
    return directions


_JUNCTION_LABELS = ["西北路口", "东北路口", "西南路口", "东南路口"]
_APPROACH_LABELS = ["东进口", "西进口", "南进口", "北进口"]
_LANE_LABELS = ["左转车道", "直行车道", "右转车道", "左转", "直行", "右转"]


def _normalize_lane_phrase(text: str) -> str:
    if text.endswith("左转"):
        return f"{text}车道"
    if text.endswith("直行"):
        return f"{text}车道"
    if text.endswith("右转"):
        return f"{text}车道"
    return text


def _extract_location(user_message: str) -> str | None:
    normalized = user_message.replace("的", "")
    for junction in _JUNCTION_LABELS:
        for approach in _APPROACH_LABELS:
            for lane in _LANE_LABELS:
                candidate = f"{junction}{approach}{lane}"
                if candidate in normalized:
                    return _normalize_lane_phrase(candidate)
            candidate = f"{junction}{approach}"
            if candidate in normalized:
                return candidate

    for approach in _APPROACH_LABELS:
        for lane in _LANE_LABELS:
            candidate = f"{approach}{lane}"
            if candidate in normalized:
                return _normalize_lane_phrase(candidate)
        if approach in normalized:
            return approach

    lowered = user_message.lower()
    english_map = {
        "east left lane": "东进口左转车道",
        "east through lane": "东进口直行车道",
        "east straight lane": "东进口直行车道",
        "east right lane": "东进口右转车道",
        "west left lane": "西进口左转车道",
        "west through lane": "西进口直行车道",
        "west straight lane": "西进口直行车道",
        "west right lane": "西进口右转车道",
        "south left lane": "南进口左转车道",
        "south through lane": "南进口直行车道",
        "south straight lane": "南进口直行车道",
        "south right lane": "南进口右转车道",
        "north left lane": "北进口左转车道",
        "north through lane": "北进口直行车道",
        "north straight lane": "北进口直行车道",
        "north right lane": "北进口右转车道",
        "east": "东进口",
        "west": "西进口",
        "south": "南进口",
        "north": "北进口",
    }
    for key, value in english_map.items():
        if key in lowered:
            return value
    return None


def _extract_simulation_duration_seconds(user_message: str) -> int | None:
    patterns = [
        r"仿真(?:时长)?(?:改成|改为|设置为)?\s*(\d{2,4})\s*秒",
        r"(\d{2,4})\s*秒",
        r"(\d{2,4})\s*sec(?:ond)?s?",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_message, flags=re.IGNORECASE)
        if match:
            return max(60, min(int(match.group(1)), 3600))
    return None


def _extract_location(user_message: str) -> str | None:
    precise_candidates = [
        "\u897f\u5317\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u897f\u5317\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u897f\u5317\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u897f\u5317\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u4e1c\u8fdb\u53e3",
    ]
    for candidate in precise_candidates:
        if candidate in user_message:
            return candidate

    coarse_candidates = [
        "\u4e1c\u8fdb\u53e3",
        "\u897f\u8fdb\u53e3",
        "\u5357\u8fdb\u53e3",
        "\u5317\u8fdb\u53e3",
        "\u4e1c\u5411",
        "\u897f\u5411",
        "\u5357\u5411",
        "\u5317\u5411",
    ]
    for candidate in coarse_candidates:
        if candidate in user_message:
            return candidate

    lowered = user_message.lower()
    english_map = {
        "east": "\u4e1c\u8fdb\u53e3",
        "west": "\u897f\u8fdb\u53e3",
        "south": "\u5357\u8fdb\u53e3",
        "north": "\u5317\u8fdb\u53e3",
    }
    for key, value in english_map.items():
        if key in lowered:
            return value
    return None


def _extract_compare_scope(user_message: str) -> list[str]:
    if not any(keyword in user_message for keyword in ["\u5bf9\u6bd4", "\u6bd4\u8f83", "\u53ea\u770b", "\u53ea\u6bd4\u8f83"]):
        return []
    candidates = [
        "\u897f\u5317\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u897f\u5317\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u897f\u5317\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u897f\u5317\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u4e1c\u5317\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u897f\u5357\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u5317\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u5357\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u897f\u8fdb\u53e3",
        "\u4e1c\u5357\u8def\u53e3\u4e1c\u8fdb\u53e3",
        "\u4e1c\u8fdb\u53e3",
        "\u897f\u8fdb\u53e3",
        "\u5357\u8fdb\u53e3",
        "\u5317\u8fdb\u53e3",
    ]
    return [candidate for candidate in candidates if candidate in user_message]


def _extract_incident_duration_minutes(user_message: str) -> int | None:
    patterns = [
        r"事故持续(?:约)?\s*(\d{1,3})\s*分钟",
        r"持续(?:约)?\s*(\d{1,3})\s*分钟",
        r"(\d{1,3})\s*分钟",
    ]
    for pattern in patterns:
        match = re.search(pattern, user_message)
        if match:
            return max(1, min(int(match.group(1)), 240))
    return None


def _extract_lane_closure_count(user_message: str) -> int | None:
    digit_match = re.search(r"封闭\s*(\d+)\s*条", user_message)
    if digit_match:
        return max(1, min(int(digit_match.group(1)), 8))

    cn_match = re.search(r"封闭\s*([一二两三四五六七八九十])\s*条", user_message)
    if cn_match:
        return CHINESE_NUMBERS.get(cn_match.group(1))
    return None


def _extract_incident_type(user_message: str, lowered: str) -> tuple[str | None, str | None]:
    mapping = [
        (["追尾", "rear-end"], ("rear_end", "追尾事故")),
        (["碰撞", "collision"], ("collision", "碰撞事故")),
        (["抛锚", "breakdown"], ("breakdown", "车辆故障")),
        (["拥堵", "排队", "queue", "congestion"], ("congestion", "拥堵/排队")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message or keyword in lowered for keyword in keywords):
            return result
    return None, None


def _extract_priority_objective(user_message: str, lowered: str) -> tuple[str, str]:
    mapping = [
        (["公交", "bus"], ("bus_priority", "优先保障公交通行")),
        (["应急", "emergency"], ("emergency_clearance", "优先保障应急车辆")),
        (["通行量", "throughput"], ("throughput", "提升通行量")),
        (["延误", "等待", "delay"], ("delay_reduction", "降低延误与等待")),
        (["排队", "queue"], ("queue_reduction", "缓解排队积压")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message or keyword in lowered for keyword in keywords):
            return result
    return "queue_reduction", "缓解排队与延误"


def _extract_time_period(user_message: str, lowered: str) -> tuple[str | None, str | None]:
    mapping = [
        (["早高峰", "morning peak"], ("morning_peak", "早高峰")),
        (["晚高峰", "evening peak"], ("evening_peak", "晚高峰")),
        (["夜间", "night"], ("night", "夜间")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message or keyword in lowered for keyword in keywords):
            return result
    return None, None


def _extract_vehicle_priority(user_message: str, lowered: str) -> tuple[str | None, str | None]:
    mapping = [
        (["公交", "bus"], ("bus", "公交车辆")),
        (["应急", "emergency"], ("emergency", "应急车辆")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message or keyword in lowered for keyword in keywords):
            return result
    return None, None


def _extract_demand_profile(user_message: str, lowered: str) -> tuple[str | None, str | None]:
    mapping = [
        (["轻流量", "低流量", "低需求", "小流量", "light demand", "light traffic", "low demand"], ("light", "轻流量")),
        (["标准流量", "正常流量", "默认流量", "标准需求", "standard demand", "normal traffic"], ("standard", "标准流量")),
        (["高流量", "大流量", "高需求", "重流量", "heavy demand", "heavy traffic", "high demand"], ("heavy", "高流量")),
        (["早高峰", "晚高峰", "高峰", "峰值", "peak"], ("peak", "峰值流量")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message or keyword in lowered for keyword in keywords):
            return result
    return None, None


def _extract_demand_target(user_message: str, lowered: str) -> tuple[str | None, str | None]:
    mapping = [
        (("网约车到站", "网约车进站", "网约车到达", "ride-hailing arrival"), ("ride_hailing_in", "网约车到站流量")),
        (("网约车离站", "网约车出站", "网约车驶离", "ride-hailing departure"), ("ride_hailing_out", "网约车离站流量")),
        (("背景车辆", "社会车辆", "背景交通", "background traffic"), ("background", "背景社会车辆流量")),
        (("全部流量", "整体流量", "总流量", "所有车辆", "all traffic"), ("all", "全部交通流量")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message or keyword in lowered for keyword in keywords):
            return result
    if "网约车" in user_message and any(word in user_message for word in ("流量", "需求")):
        return "ride_hailing_all", "全部网约车流量"
    return None, None


def _extract_demand_multiplier(user_message: str, lowered: str) -> float | None:
    percent_match = re.search(
        r"(?:提高|增加|提升|上调|增长)\s*(\d+(?:\.\d+)?)\s*[%％]",
        user_message,
    )
    if percent_match:
        return round(1.0 + float(percent_match.group(1)) / 100.0, 4)

    percent_match = re.search(
        r"(?:降低|减少|下降|下调|削减)\s*(\d+(?:\.\d+)?)\s*[%％]",
        user_message,
    )
    if percent_match:
        return round(max(0.0, 1.0 - float(percent_match.group(1)) / 100.0), 4)

    target_match = re.search(
        r"(?:调整为|设为|变为)\s*(\d+(?:\.\d+)?)\s*[%％]",
        user_message,
    )
    if target_match:
        return round(float(target_match.group(1)) / 100.0, 4)
    if "翻倍" in user_message or "double" in lowered:
        return 2.0
    return None


def _extract_demand_time_window(user_message: str) -> tuple[int | None, int | None]:
    patterns = [
        (r"(?:仿真)?第?\s*(\d{1,4})\s*(?:到|至|[-—~～])\s*(\d{1,4})\s*秒", 1),
        (r"从\s*(\d{1,4})\s*秒?\s*(?:到|至)\s*(\d{1,4})\s*秒", 1),
        (r"(?:仿真)?第?\s*(\d{1,3})\s*(?:到|至|[-—~～])\s*(\d{1,3})\s*分钟", 60),
    ]
    for pattern, unit_multiplier in patterns:
        match = re.search(pattern, user_message)
        if not match:
            continue
        start = int(match.group(1)) * unit_multiplier
        end = int(match.group(2)) * unit_multiplier
        if end > start:
            return max(start, 0), min(end, 3600)
    return None, None


def _extract_demand_spatial_scope(user_message: str) -> tuple[str | None, str | None]:
    mapping = [
        (("南京南站北广场", "南站北广场", "北广场"), ("north_plaza", "南京南站北广场区域")),
        (("南京南站南广场", "南站南广场", "南广场"), ("south_plaza", "南京南站南广场区域")),
    ]
    for keywords, result in mapping:
        if any(keyword in user_message for keyword in keywords):
            return result
    return None, None


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if value == []:
        return True
    return False


def _is_ambiguous_approach_location(location: object) -> bool:
    if not isinstance(location, str):
        return False
    if any(junction in location for junction in ["西北路口", "东北路口", "西南路口", "东南路口"]):
        return False
    return any(approach in location for approach in ["东进口", "西进口", "南进口", "北进口"])


def _candidate_precise_locations(location: object) -> str:
    location_text = str(location)
    if "东进口" in location_text:
        return "东北路口东进口或东南路口东进口"
    if "西进口" in location_text:
        return "西北路口西进口或西南路口西进口"
    if "北进口" in location_text:
        return "西北路口北进口或东北路口北进口"
    if "南进口" in location_text:
        return "西南路口南进口或东南路口南进口"
    return "东北路口东进口或西南路口北进口"


def _suggest_precise_location(location: object) -> str:
    candidates = _candidate_precise_locations(location)
    return candidates.split("或", 1)[0]


def _normalize_lane_phrase(text: str) -> str:
    if text.endswith("左转") or text.endswith("直行") or text.endswith("右转"):
        return f"{text}车道"
    return text


def _extract_location(user_message: str) -> str | None:
    normalized = user_message.replace("的", "")
    map_name_match = re.search(r"地图对象名称：([^\r\n]+)", user_message)
    map_edge_match = re.search(r"地图道路ID：([^\s]+)", user_message)
    if map_edge_match:
        return map_name_match.group(1).strip() if map_name_match else f"地图选定道路 {map_edge_match.group(1)}"

    station_location_candidates = [
        "南京南站网约车上客区",
        "南京南站网约车停车区",
        "南京南站南广场落客通道",
        "南京南站北广场网约车上客区",
        "南京南站北广场",
        "南京南站南广场",
        "网约车上客区",
        "网约车停车区",
        "落客通道",
        "南京南站",
    ]
    for candidate in station_location_candidates:
        if candidate in normalized:
            return candidate

    junction_labels = ["西北路口", "东北路口", "西南路口", "东南路口"]
    approach_labels = ["东进口", "西进口", "南进口", "北进口"]
    lane_labels = ["左转车道", "直行车道", "右转车道", "左转", "直行", "右转"]

    for junction in junction_labels:
        for approach in approach_labels:
            for lane in lane_labels:
                candidate = f"{junction}{approach}{lane}"
                if candidate in normalized:
                    return _normalize_lane_phrase(candidate)
            candidate = f"{junction}{approach}"
            if candidate in normalized:
                return candidate

    for approach in approach_labels:
        for lane in lane_labels:
            candidate = f"{approach}{lane}"
            if candidate in normalized:
                return _normalize_lane_phrase(candidate)
        if approach in normalized:
            return approach

    lowered = user_message.lower()
    english_map = {
        "east left lane": "东进口左转车道",
        "east through lane": "东进口直行车道",
        "east straight lane": "东进口直行车道",
        "east right lane": "东进口右转车道",
        "west left lane": "西进口左转车道",
        "west through lane": "西进口直行车道",
        "west straight lane": "西进口直行车道",
        "west right lane": "西进口右转车道",
        "south left lane": "南进口左转车道",
        "south through lane": "南进口直行车道",
        "south straight lane": "南进口直行车道",
        "south right lane": "南进口右转车道",
        "north left lane": "北进口左转车道",
        "north through lane": "北进口直行车道",
        "north straight lane": "北进口直行车道",
        "north right lane": "北进口右转车道",
        "east": "东进口",
        "west": "西进口",
        "south": "南进口",
        "north": "北进口",
    }
    for key, value in english_map.items():
        if key in lowered:
            return value
    return None
