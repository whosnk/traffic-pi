# 交通治理 MCP

`traffic-demo.mjs` 连接当前唯一的仿真工作台，并把每次调用关联到右侧 A/B Street 画布。所有工具统一返回 `actionId`、`status`、`simulationTime`、`result` 和 `error`。

启动 Traffic Pi：`npm run dev`。打开侧边栏“仿真工作台”并保持一个前台工作台。项目已经通过 `.pi/mcp.json` 注册服务器；已有对话执行 `/reload` 后即可发现新增工具。

在受信任项目的对话中输入“检测当前拥堵点”，Agent 使用 `detect_congestion` 自动打开 A/B Street，无需先手动进入仿真。扩展通过 MCP `_meta.trafficPi` 注入 sessionId 和 toolCallId，不暴露模型参数；仅匹配该会话的接收窗口，多个窗口时报错。准备最多 180 秒，总任务最多 300 秒；停止 Agent、离开会话或关闭接收窗口会中止。普通控制工具仍要求唯一已打开的接收窗口。

检测保留当前场景、时间控制及速度，读取当前状态和接口返回的道路指标，按“排队不少于 5 辆且平均车速不高于 10 km/h”筛选，按排队降序、速度升序取前 5 处。黄色表示疑似拥堵，橙色为排队 ≥10 且速度 ≤5，红色为排队 ≥20 且速度 ≤3。规则为瞬时筛选，未经交通评价标定；接口返回道路范围不等于全路网。空数据或缺失必要指标会失败，不作无拥堵结论。结果携带原始指标和分次采集时刻；运行时不宣称所有数据来自同一瞬间。

工具分为：

- 状态与指标：`get_simulation_state`、`get_road_metrics`、`get_intersection_metrics`
- 画面联动：`focus_on_road`、`highlight_roads`、`clear_highlights`
- 时间控制：`pause_current_simulation`、`resume_current_simulation`、`speed_up_current_simulation`、`run_until`、`run_for`
- 信号治理：`get_signal_plan`、`apply_signal_plan`、`restore_signal_plan`
- 同条件评估：`capture_metrics`、`compare_metrics`
- 演示重置：`start_rush_hour_demo`

工作台顶部可切换城市／高速。`start_rush_hour_demo` 经用户确认和任务保护重新加载城市初始暂停状态，等待实际控制桥确认后返回。其他基础控制作用于当前场景；高速仅提供播放、时间、指标及镜头操作，不支持城市拥堵检测和信号治理。命令与结果由运行时附带场景和加载批次，旧批次历史结果不能用于当前地图操作。

`apply_signal_plan` 会在首次修改前保存原方案；`restore_signal_plan` 用它恢复基准。`capture_metrics` 的方案组通过 `baselineCaptureId` 回到基准检查点，在当前信号方案下使用相同场景、随机种子、起点和统计时长重跑。条件不一致或右侧执行失败时，MCP 返回失败，不生成替代数据。

推荐让 `traffic-governance` Skill 编排完整流程。第一版仅执行信号配时治理，默认根据真实拥堵指标自动选择道路和信号路口，也接受用户指定的目标。

交互式缓解入口：输入“分析并缓解当前拥堵”，或道路卡片点击“分析缓解方案”。`traffic-mitigation` 技能先调用 `analyze_congestion_cause` 观察道路等待、路口相位及下游占用，显示可能原因。只为固定配时路口生成周期不变、满足行人最短通行时间的候选；自适应、下游阻塞或证据不足时返回原因，不强行生成方案。

用户在面板选定后产生一次性 `taskId / approvalToken / version`，Agent 原样传给 `evaluate_signal_plan`，执行端核对该次实际选择。基准和候选从同一检查点分别推进 300 秒，按 5× 展示，每 5 秒采集一次。等待选择期间 MCP 调用已返回，不持有长请求；执行时锁定普通时间和配时操作，地图仍可拖动缩放。

结果同时展示目标进口和其他进口的平均／最大／结束排队、采样积分估计的等待车辆秒及通过车辆数。用户最后在面板保留或恢复，再用新授权调用 `finalize_signal_trial`；保留候选轮结束状态或恢复基准轮结束状态，并恢复任务前时间控制。停止、取消、会话切换和失败恢复任务起点；恢复失败明确提示。任务与选择只存在当前页面，刷新不恢复任务。
