# Traffic Pi 阶段1–3架构

## 任务入口与职责

| 一级入口 | 现有能力 | 状态所有者 |
| --- | --- | --- |
| 仿真工作台 | 城市／高速 A/B Street 共享画布、控制 HUD、道路详情、拥堵检测与治理 | AbstreetPanel、congestionStore、mitigationStore |
| 仿真实验 | SimTrend 场景、任务、草稿与历史 jobs | SimtrendPanel、simtrendContextStore、Python service |
| 分析与报告 | MapLibre 图层、GIS 历史与交通工具结果 | GeoMapPanel、TrafficResultsPanel、既有结果 store |
| 设置 | 模型、MCP、技能等现有配置 | AppShell 既有设置区域 |

AppShell 复用原工作区状态，增加单一任务导航；TrafficWorkspace 保持各视图挂载，以显示开关切换，不新建平行路由。桌面为左侧对话、中央地图、按需展开的右侧结果。小屏保留任务入口、对话/结果切换；开发工具仍可打开文件、终端和 worktree。

## 场景元数据与隔离

`lib/traffic-scenarios.ts` 将类别、计算引擎、可视化和入口分开。重庆条目来自固定 WASM 场景；SUMO 条目由现有后端 scenario.json 元数据投影，避免前端维护第二份场景名称/能力。`abstreetScenarios` 集中定义城市／高速的地图、需求、身份、时刻、播放状态与结束时刻；`abstreet-runtime` 保存本次加载的 scenarioId、runId、就绪与错误状态。高速已交付独立合成路网和边界需求；重建见 third-party/abstreet/highway/README.md。

场景切换保护使用原检测/治理 store 和 Agent 忙闲状态。真实治理等待选择、等待决策、恢复中，以及恢复失败状态均阻止切换。SimTrend 已提交 jobs 不取消；访问过的场景保留独立表单，空间选择与草稿通过场景 ID/revision 校验，跨引擎消息不附带旧 SUMO 定位。

A/B Street 仍是每个页面一个共享仿真实例，并非每会话独立仿真。城市／高速切换只销毁旧 iframe 并加载新初始状态，不保留车辆进度。桥返回的 map、scene、randomSeed 必须匹配配置；onLoad 不作为就绪依据。结果按会话隔离并记录 scenarioId/runId；旧运行批次只允许查阅，不允许定位或治理；结果与草稿在页面刷新后的持久化范围见 [场景说明](scenarios.md)。浏览器关闭/刷新不能代替保留/恢复决策。

## 检测、推演与验证

MCP 的原工具名和参数协议保持兼容。`detect_congestion` 经原控制桥查询、筛选、高亮和聚焦；明确标注有限道路覆盖及历史平均车速。`analyze_congestion_cause` 默认进入真实执行器；仅显式 `presetScenario:true` 选择预设模型。改选目标保留检测快照和执行模式，作废旧候选及授权。恢复未确认通过独立状态锁定，不允许新任务覆盖；恢复验证成功或用户明确重新初始化后解除。

真实治理继续使用原 MitigationExecutor：检查点、一次性 taskId/approvalToken/version、各300秒且5秒采样、保留/恢复与失败回滚。预设 MitigationScenario 使用独立模型，面板、记录、结果及最终按钮均标注推演来源。隐藏视图继续接收命令，只有用户取消或会话生命周期触发既有恢复逻辑。

## 后续接口建议（未实施）

- 后续高速治理：当前只运行典型高速演示和基础地图／时间操作；UI 与命令执行端均拒绝城市检测和信号治理。新增算法需另行验证，不复用城市信号流程。
- 阶段5：桥接前定义 engineRunId、scenarioId/networkVersion、时间单位/时钟、道路 ID 映射、样本口径和中断恢复协议；分别验证 SUMO 输出与可视化输入，再讨论实时同步。当前未做轨迹同步、ID转换或 MapLibre 覆盖 WASM。
- 阶段6：实验结果需要稳定的 run manifest（引擎版本、网络/需求校验、种子、参数、来源、指标定义）和持久化仓库；科研 GIS 与批量实验应在现有结果来源边界之外独立设计，不把页面内临时结果当作科研数据库。
