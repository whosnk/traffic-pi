# Traffic Pi 阶段 1–3：城市／高速交付与验证

本轮起点为 `e946945`，使用现有 30141 开发服务。未执行 `next build`，未恢复 stash，未提交或推送。部署中的 JS/WASM 未更换；新增地图与需求使用匹配 v0.3.49 的原生导入工具生成。

## 阶段 1：两套真实场景

| 验收项 | 实现与证据 |
| --- | --- |
| 城市已加载 | `yuzhong_core.bin / weekday`，08:00 暂停，种子 42；由真实控制桥核对身份 |
| 高速已加载 | 独立 `highway-demo.bin / motorway`，与重庆地图身份不同；资源读取和控制桥均成功后才显示就绪 |
| 高速车辆已运行 | 真实 WASM 返回东、西向主线及四条出入口匝道均有在途车辆；1× 下 6 秒实际推进约 6 仿真秒，道路指标发生变化 |
| 资源可重建 | `third-party/abstreet/highway/` 含 OSM、裁剪边界、1,530 条边界车辆需求、生成脚本和说明；生成物入库，不依赖临时源码目录 |

高速为 Traffic Pi 自建典型演示：双向分隔、每向三车道、出入口及立交连接匝道，主线无信号。需求从 07:58 供给至 08:32，初始 08:00 已有车辆；工作台在 08:35 暂停并提供重播。它是合成路网及需求，不代表现场交通。

## 阶段 2：一个工作台与运行隔离

顶部直接切换“城市交通 / 高速公路”；独立场景管理导航合入工作台。仅一个活动 iframe，切换经确认后重载初始状态，保留对话草稿与页面历史结果。GIS、SUMO 与对话视图往返保留当前实例。

每次加载生成新 `runId`，与 `scenarioId` 一起进入任务、浏览器命令和结果。旧批次只读，禁止从旧结果定位或启动治理；旧响应不能确认新批次命令。高速能力限制同时在技能入口、浏览器执行器和服务端检查。旧 `start_rush_hour_demo` 仍只加载城市，经同一保护和实际就绪确认返回。

资源缺失、地图身份不匹配或 180 秒未就绪显示具体错误，移除旧画面并提供重试与返回城市。正在检测、等待选择／决策、验证或恢复时阻止切换；恢复未确认独立保存，禁止新任务覆盖。明确重新初始化属于丢弃当前状态，不表示恢复成功。

## 阶段 3：城市真实治理入口

道路卡、技能卡、结果栏与对话默认 `presetScenario:false`，不自动退回预设。预设模型放入“其他方式”，须主动选择且保留来源标签。改选道路保留真实执行模式与原检测快照，并作废旧候选及授权。结果栏启动失败显示忙碌、加载或不支持的原因。

真实配时能力与实际改善分开验收：

- 部署 WASM 的真实重庆控制桥验证检查点同起点重跑、可见推进、行人约束、配时应用、基准结束状态恢复、任务锁和取消。
- 固定配时兼容试验在独立测试窗口临时建立条件，不修改交付地图；不能据此声称重庆既有需求已改善。
- 未改动的城市场景包含自适应相位。诊断遇到不支持条件时返回证据且不给可执行候选，不伪造改善结果。

## 回归检查

默认地址 `http://127.0.0.1:30141`；测试使用模拟会话／设置，不调用真实模型供应商。真实场景测试加载部署的 JS/WASM；加载故障注入及工作区交互测试另用受控响应。

| 检查 | 命令 | 覆盖 |
| --- | --- | --- |
| 真实场景与故障 | `node e2e/abstreet-scenes.mjs` | 城市→高速→城市、桥身份、车辆运动、单实例、播放、镜头不推进时间、旧启动工具、草稿、窄屏／键盘／减少动画；缺地图／需求、错误身份、就绪超时 |
| 真实配时桥 | `node e2e/abstreet-mitigation-bridge.mjs` | 未改动城市的诚实诊断，以及临时固定配时条件下的同起点重跑、应用、恢复和取消 |
| 治理交互 | `node e2e/mitigation-workspace.mjs` | MCP/SSE、六阶段、用户授权、改选保留真实模式／检测来源、比较／恢复／取消、预设不写真实仿真、窄屏 |
| 检测交互 | `node e2e/congestion-workspace.mjs` | 检测、失败／重试／取消、会话隔离、结果与草稿 |
| 导航 | `node e2e/traffic-navigation.mjs` | 桌面／390px，默认主图、GIS／实验入口、草稿、后台 jobs |
| GIS 工作区 | `node e2e/traffic-workspace.mjs` | 历史结果、去重、刷新／会话隔离、图层／镜头／草稿、文件预览与键盘 |
| 相关单测 | 下方命令 | 62 项通过，含迟到事件、旧批次、恢复锁与结果来源 |
| 类型 | `node node_modules/typescript/bin/tsc --noEmit` | 通过 |
| lint | `npm run lint` | 0 错误，28 条既有第三方生成文件警告 |

```powershell
node --experimental-strip-types --test lib/congestion.test.mjs lib/mitigation.test.mjs lib/mitigation-scenario.test.mjs lib/mitigation-entry.test.mjs lib/traffic-results.test.mjs lib/traffic-workflow.test.mjs lib/traffic-scenarios.test.mjs lib/simtrend-context.test.mjs app/api/simulation-demo/route.test.mjs components/AppShell.workspace-memory.test.mjs
```

真实画面截图在 `.next/abstreet-validation/`。本轮未重跑全仓测试；此前全仓记录中的 12 个环境／其他模块失败属于历史基线，不作为本轮通过证据。未运行真实模型供应商端到端、SUMO 计算或 SUMO/A/B Street 联动；未增加高速治理算法。普通查询速度口径仍为在途行程累计平均，不能解释为瞬时测速。
