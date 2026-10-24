# Traffic Pi 阶段1–3交付与验证记录

本次在已连接 Windows 上通过 Remote Desktop Commander 实施。起点为干净的 main，HEAD `ea066b0e04c01af69b681ae013530a2f2e1d91c1`；开发分支 `feat/traffic-workspace-stages-1-3`。保留原30141开发服务；未执行 build、push、真实 SUMO 计算，未修改 WASM/Rust、Python 算法、核心场景数据或依赖配置。

## 分阶段交付

| 阶段 | 提交 | 核心变更与主要文件 | 验证 |
| --- | --- | --- | --- |
| 1 | a091ec0 | AppShell、TrafficWorkspace、SessionSidebar、traffic.css：默认 A/B Street，唯一任务导航，聊天/结果按需展开，隐藏视图继续接收命令 | 类型与 lint 通过；37相关单测通过；桌面/移动导航通过 |
| 2 | a77d74e | traffic-scenarios、ScenarioSelector：重庆与后端 SUMO 元数据，高速禁用占位；simtrend-context、SimtrendPanel、ChatWindow：草稿隔离、jobs保留及切换保护 | 28相关单测通过；场景导航、草稿往返、后台轮询、不可用提示通过 |
| 3 | 本记录所在提交 | AbstreetPanel、TrafficWorkflow、MitigationPanel、TrafficResultsPanel：检测取消、来源标签、真实溯源入口、授权/比较口径；congestion与executor修正文案；AppShell修复定位收起结果栏；补齐回归测试与说明 | 最终检查见下表 |

当前交互为“仿真工作台 / 场景管理 / 仿真实验 / 分析与报告 / 设置”。GIS 属空间分析与图层，SimTrend 属 SUMO 实验工具链。文件、终端、模型、技能、MCP 与 worktree 保留原入口；A/B Street 为中央共享实例。详见 [使用说明](traffic-pi.md)、[场景切换规则](scenarios.md)、[架构与扩展建议](traffic-pi-architecture.md)。

## 最终验证

| 检查 | 命令与结果 | 覆盖/限制 |
| --- | --- | --- |
| 类型 | `npx tsc --noEmit`，exit 0 | 最终业务代码通过 |
| lint | `npm run lint`，exit 0 | 0错误、28条既有第三方警告 |
| 全量单测 | `npm test`，exit 1：1021 tests，1004通过、12失败、5跳过 | 基线为1016 tests，996通过、15失败、5跳过；无新增失败，补齐会话草稿测试夹具后原3个失败消失 |
| 交通专项 | `node --experimental-strip-types --test lib/congestion.test.mjs lib/mitigation.test.mjs lib/mitigation-scenario.test.mjs lib/mitigation-entry.test.mjs lib/traffic-results.test.mjs lib/traffic-workflow.test.mjs lib/traffic-scenarios.test.mjs lib/simtrend-context.test.mjs app/api/simulation-demo/route.test.mjs` | 52/52通过；授权复用拒绝、保留/恢复、取消、回滚失败、迟到事件、场景来源与隔离 |
| 会话/入口专项 | `node --experimental-strip-types --test components/AppShell.workspace-memory.test.mjs lib/traffic-scenarios.test.mjs lib/mitigation-entry.test.mjs` | 11/11通过 |
| 导航 | `E2E_BASE_URL=http://127.0.0.1:30142 node e2e/traffic-navigation.mjs` | 1440px与390px通过；默认主图、视口内入口、场景禁用、Agent忙保护、场景表单往返、后台job轮询、GIS/实验可达，无SUMO提交 |
| GIS工作区 | 同上环境变量，`node e2e/traffic-workspace.mjs`，exit 0 | 历史回看、去重、刷新/会话隔离、图层开关、相机/滚动/草稿、文件预览、键盘与小屏 |
| 拥堵工作区 | `TRAFFIC_PI_BASE_URL=http://127.0.0.1:30142 node e2e/congestion-workspace.mjs`，exit 0 | MCP→事件→高亮→定位→结果，失败/重试/取消、活动会话保护、深色/小屏截图 |
| 治理工作区 | 同上环境变量，`node e2e/mitigation-workspace.mjs` | exit 0，约60秒；受控桥覆盖用户授权、同检查点比较、恢复与取消、等待授权禁止切换引擎、隐藏页继续验证、预设不写仿真、显式真实不降级 |
| 真实重庆WASM | 再设 `TRAFFIC_PI_REAL_BRIDGE=1` 运行拥堵工作区脚本，exit 0 | 107秒；真实地图、指标、高亮、聚焦、跟随、原生界面切换与时间保持通过；未运行真实WASM完整配时试验 |
| diff | `git diff --check` | 无空白错误 |

表中的环境变量赋值为简写；Windows PowerShell 使用 `$env:E2E_BASE_URL='http://127.0.0.1:30142'` 等形式。MCP子进程显式继承测试地址；默认地址仍为30141，工具名称与参数协议保持兼容。

真实WASM在08:00、暂停、速度1×下，返回道路37（重庆长江大桥）排队372辆、历史行程平均速度约9.99km/h，以及道路314排队28辆、约9.93km/h。它们是合成需求种子42的仿真样本，非现场实测；未知道路名称保留为未提供，不编造名称。

## 既有失败与测试环境

剩余12个失败均为基线已存在的位置：ChatInput图片警告、ChatWindow通知布局、directory-browser符号链接权限、project-command-env四项bash相关、project-trust、subagent-input、terminal-manager两项、worktree。未为本次重构扩大修复范围。

测试在独立Git worktree `E:\The work of PHD\Code\traffic-pi-e2e-stages`、端口30142运行。node_modules为共享只读依赖 Junction；仅测试目录为Turbopack设置了父目录root，未带回正式仓库。使用临时 Agent 目录、模拟会话/API，不读取真实用户会话或原有jobs。测试期间不并行运行多个交通控制脚本。首次热更新时曾出现重复iframe请求；改为客户端挂载后初始化后，最终回归保留单实例断言并通过。

原始全量日志位于 `%TEMP%\traffic-pi-baseline-tests.log`、`traffic-pi-final-tests.log`；lint日志为 `traffic-pi-final-lint.log`，专项日志为 `traffic-pi-focused-tests.log`。截图与日志副本保留在测试目录 `validation-artifacts`，便于复核。

## 未实现、未验证及风险

- 阶段4高速建模、阶段5实时桥接、阶段6科研GIS/实验平台均未实施；高速卡片不能运行。未做道路ID转换、轨迹同步或MapLibre覆盖WASM。
- 未运行真实 SUMO：PATH未发现 sumo/sumo-gui，SUMO_HOME、SIMTREND_PYTHON、SUMO_BINARY 未配置。卡片标注后端已实现、运行环境未验证；打开场景不会启动计算。
- 真实WASM完整候选配时试验、真实LLM供应商/信任目录/MCP重新连接的人工端到端未验证；治理安全逻辑由单测与受控桥验证，不据此宣称交通改善。
- A/B Street是共享页面实例；刷新/关闭页面会丢失临时结果与表单，不能用刷新代替明确保留/恢复。恢复失败时须人工核查；切换保护不会伪装成恢复成功。
- 同会话多个接收窗口仍沿用既有拒绝机制；使用单一工作台执行交通任务。

后续第4/5/6阶段只给出了场景注册、运行身份/路网版本/道路映射、可追溯实验清单的接口建议，详见架构说明，未落地实现。
