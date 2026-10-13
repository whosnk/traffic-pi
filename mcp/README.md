# 交通治理 MCP

`traffic-demo.mjs` 连接当前唯一的仿真工作台，并把每次调用关联到右侧 A/B Street 画布。所有工具统一返回 `actionId`、`status`、`simulationTime`、`result` 和 `error`。

启动 Traffic Pi：`npm run dev`。打开侧边栏“仿真工作台”并保持一个前台工作台。项目已经通过 `.pi/mcp.json` 注册服务器；已有对话执行 `/reload` 后即可发现新增工具。

工具分为：

- 状态与指标：`get_simulation_state`、`get_road_metrics`、`get_intersection_metrics`
- 画面联动：`focus_on_road`、`highlight_roads`、`clear_highlights`
- 时间控制：`pause_current_simulation`、`resume_current_simulation`、`speed_up_current_simulation`、`run_until`、`run_for`
- 信号治理：`get_signal_plan`、`apply_signal_plan`、`restore_signal_plan`
- 同条件评估：`capture_metrics`、`compare_metrics`
- 演示重置：`start_rush_hour_demo`

`apply_signal_plan` 会在首次修改前保存原方案；`restore_signal_plan` 用它恢复基准。`capture_metrics` 的方案组通过 `baselineCaptureId` 回到基准检查点，在当前信号方案下使用相同场景、随机种子、起点和统计时长重跑。条件不一致或右侧执行失败时，MCP 返回失败，不生成替代数据。

推荐让 `traffic-governance` Skill 编排完整流程。第一版仅执行信号配时治理，默认根据真实拥堵指标自动选择道路和信号路口，也接受用户指定的目标。
