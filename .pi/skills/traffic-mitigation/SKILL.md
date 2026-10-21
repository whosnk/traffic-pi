---
name: traffic-mitigation
description: 基于 A/B Street 的道路与信号证据分析拥堵原因，由用户选择配时方案后进行同起点验证，并决定保留或恢复。
---

# 拥堵溯源与缓解

用户要求分析并缓解当前拥堵时，调用 `analyze_congestion_cause`，可传入用户选择的 roadId；未指定时由工具选取当前首位疑似拥堵道路。

用户明确要求“展示完整拥堵治理闭环”“预设场景”或“拥堵治理推演”时，调用同一工具并传 `presetScenario:true`。该模式以当前道路作为地图载体，采用预设信控与需求模型，不要求实际路口存在信号灯。返回 `preset:true` 后，提示用户在页面选择方案，后续两轮推演和保留／恢复在页面完成，不调用 evaluate_signal_plan、finalize_signal_trial 或真实配时写工具。解释结果时保留预设参数推演这一来源，不称为实测或声称已修改真实信号灯。

工具自动观察真实等待、信号及下游状态，并返回候选方案。解释“可能原因”、依据和不足，不把相关关系表述为已证明的因果关系。

返回 awaiting_selection 时，告知用户在方案面板选择。不要自行调用 apply_signal_plan、run_for 或其他写工具。

只有面板发出的选择消息包含 taskId、approvalToken 和 version 时，才原样调用 evaluate_signal_plan。两轮验证结束后解释目标及交叉方向指标；用户仍需在结果面板决定保留或恢复。

只有面板授权最终决定后，原样调用 finalize_signal_trial。不要构造、复用或猜测授权信息。没有候选方案、数据不足、执行或恢复失败时说明实际原因，不宣称成功缓解。
