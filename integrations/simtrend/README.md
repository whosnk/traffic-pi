# SimTrend embedded integration

## 范围与边界

这是原 SimTrend 的独立迁入副本，不是指向原工程的软链接。Python 算法、工具链和两个场景位于本目录；Traffic Pi 的 React 工作台重建交互，不启动或嵌入 Streamlit。原工程不被修改，也不需要与本目录一起部署。

本轮迁入：场景切换、道路/车道/上客区地图选择、路网与信号查询、事件处置与信号优化、交通需求影响评估、参数化信号方案、结果诊断、公平对比、运行记录、指标表/条形图、GIF 和配置文件下载。

地图选中对象可用于表单，也会在左侧输入框上方显示可取消的定位标签。发送普通聊天消息时自动附加当前场景及道路/车道/上客区快照，无需复制定位；斜杠命令和 shell 命令不附加。切换场景清除旧对象，不同会话独立保存；刷新页面后需要重新选择，已发送消息保留当时的快照。未选择车道时不推断车道，文字与地图冲突时提示模型先澄清。这是模型上下文约束，不是服务端权限控制；选中地图本身不会启动仿真。首轮建议用“查询这条车道的详细信息，不运行仿真”验证。

查询/诊断返回的空间对象可点击定位。四交叉口是合成路网，不能把示意坐标解释为真实地理位置。南京南站底图访问 OpenStreetMap，断网时可用仿真道路与搜索，但底图可能不可用。

## 对话生成事故任务草案

在地图选择道路和具体车道后，可发送“这里发生追尾事故，封闭10分钟，帮我生成信号优化任务草案”。模型通过 `prepare_incident_task_draft` 把已知参数写入中间“创建仿真任务”面板；该工具只校验参数，不创建运行任务。封闭车道数、优化目标、仿真时长等未明确给出的字段保持空白，补齐前不能确认运行。

表单修改会同步到下一轮消息的草案快照。可以继续说“把仿真时长改为900秒，其他参数不变，更新草案”。每条消息携带版本号；如果模型返回期间位置或表单又发生变化，旧草案不会覆盖当前编辑。切换场景清空该场景草案；不同会话独立保存，刷新页面后需重新生成。草案中的封道从第0秒开始，沿用当前工作流的事故时段语义。

检查表单后点击“确认草案并运行仿真”，会再次校验道路/车道归属、封闭数量及数值范围，然后交给已有事故工作流。已有直接执行 MCP 工具保留兼容；草案优先是工具描述及对话上下文约定，不是对整个 Agent 的执行权限封锁。更新本模块后，在 Traffic Pi 重新加载当前会话或新建会话，使 MCP 客户端重新发现工具。

## 本地启动

在 Traffic Pi 根目录执行（Python 3.11+、Node 版本遵循根目录 package.json）：

```powershell
conda activate yolov8
python -m pip install -r integrations/simtrend/requirements.txt
npm install
npm run dev
```

打开 http://127.0.0.1:30141，信任当前项目，点击左侧“SimTrend 仿真”。必须配置正确的 `SUMO_HOME` 或让当前 PATH 能找到所需版本的仿真引擎。本次验证使用 SUMO 1.26.0。

如果启动 Node 的环境找不到正确的 Python，可在 **Traffic Pi 根目录**的本机 `.env.local` 中设置：

```dotenv
SIMTREND_PYTHON=E:/Code/anaconda3/envs/yolov8/python.exe
```

路径按本机安装修改，该文件不提交 Git。不要复制原工程的 API Key；对话模型由 Traffic Pi 管理，表单仿真不需要大模型 Key。可选的后端环境文件位置为 `integrations/simtrend/.env`，仅参考同目录 `.env.example` 设置引擎参数。

## MCP 与网页共用后端

```text
React 表单 -> Next /api/simtrend -> web_bridge.py --JSON-->
                                                     integration.py -> SimTrendMCPService -> 原工具链
Traffic Pi 对话 -> stdio MCP -> mcp_server.py -------->
```

`.pi/mcp.json` 中 `simtrend` 改为 `node bin/simtrend-mcp.mjs`。不再依赖另外启动的 8765 服务。修改配置后，应在 Traffic Pi 重新加载已有会话或新建会话，然后检查 MCP 工具列表。

原 9 个工具兼容保留，并增加 `get_simtrend_map`、`submit_simtrend_task`、`get_simtrend_task`、`prepare_incident_task_draft`，共 13 个。长仿真优先提交异步任务再查询，不将 queued/running 当作成功。任务返回的 `/api/simtrend/artifacts/...` 是当前 Traffic Pi 服务上的相对链接，独立 MCP 客户端不自带文件 HTTP 服务。

## 运行与安全

- `.runtime/jobs/` 保存任务快照、进度和结果；刷新页面不终止仿真。
- `simtrend_scenarios/<场景>/outputs/agent_runs/` 保存独立仿真目录，不复用原项目 latest_run；参数化基准/候选别名指向最近对应运行。
- 所有入口共用跨进程仿真锁；已有仿真运行时，新仿真返回忙碌提示，不是排队系统。
- 文件下载只能读取任务清单内、场景输出目录下的文件；工具名有白名单，不提供任意 shell 执行。
- 文件收集只展开结果明确指定的本次运行目录，不递归扫描场景总输出目录。事故/需求对比通常有两个回放，参数化单方案有一个；已有错误清单在读取及网页展示时过滤，保留本次文件原有下载编号，历史文件不删除。
- 任务进程中断后在查询时标记失败，保留已生成文件；尚无取消、自动重试或自动清理功能。
- 历史按会话筛选只是界面隔离，不是用户权限隔离。该版本面向受信任本机/团队演示，不应将开发服务器直接当作多租户公网服务。
- 未创建对话时的表单任务保存在工作台历史；创建对话后使用该会话自己的历史，不自动迁移先前任务。
- 仿真、查询结果与底图都不是实测交通数据。算法沿用原工程，不声称是 Webster、全局最优或已标定的业务系统。

## 验证

```powershell
cd integrations/simtrend
python -m pip install pytest
python -m pytest tests -q
cd ../..
node --experimental-strip-types --test lib/traffic-results.test.mjs lib/simtrend-metrics.test.mjs lib/simtrend-artifacts.test.mjs lib/simtrend-context.test.mjs lib/simtrend-draft.test.mjs lib/traffic-mcp.test.mjs
node e2e/simtrend-mcp.mjs
node e2e/simtrend.mjs
node e2e/simtrend-context.mjs
node e2e/simtrend-draft.mjs
node e2e/simtrend-replays.mjs
node e2e/simtrend-backend.mjs
```

MCP 冒烟测试需要当前环境 `python` 可用，或设置 `SIMTREND_PYTHON`。浏览器测试需要正在运行的开发服务及 Edge；可通过 `PLAYWRIGHT_CHANNEL` 更换已安装浏览器。`simtrend-context.mjs` 拦截模型请求，检查聊天实际发送的场景和车道快照，不调用收费模型。`simtrend-draft.mjs` 使用真实后端校验草案、模拟模型工具事件，验证缺项、手动编辑、对话更新及确认提交参数；执行请求被拦截，不启动仿真。设置 `SIMTREND_E2E_SIMULATE=1` 后浏览器测试会真实运行南京南站 60 秒需求对比并检验 GIF 下载，不调用收费大模型。`simtrend-backend.mjs` 真实运行两次 60 秒参数化仿真，然后诊断并公平对比；会把基准/候选别名更新为这两次测试运行，旧文件保留。

本轮已真实验证四交叉口参数化仿真、事故基线/优化仿真、南京南站到站需求 +30% 对比。60 秒仅用于联通性测试，不能据此评估长期拥堵效果。需求车辆数、实际插入车辆数、已到达车辆数必须分开解释。

## 协作与后续部署

`simtrend-replays.mjs` 需要已有一次成功的事故仿真记录，复用其动画验证旧清单过滤及文件下载，不重新启动仿真。

迁入来源：原 SimTrend 工作区快照，来源仓库当时 HEAD 为 `bc9aec7`，包含该工作区已有的未提交内容，不等同于该提交的纯净导出。场景沿用原工程资源，南京南站路网含 OpenStreetMap 数据，继续保留来源说明及相应数据许可义务。

迁移适配包括：共享任务持久化、需求文本标准化、明确的事故位置澄清、独立输出目录、下载边界、进程中断状态、统一 60–3600 秒上限。原 Python Agent/UI 模块保留作为迁移参考，但新入口不加载 Streamlit 页面、不启用第二个大模型路由器。

当前支持 **源码检出方式**部署。Traffic Pi 现有 npm 发布清单尚未包含 Python/场景资源，不能假定 `npm publish` 后的包已具备此模块；正式打包需要另做资源包含、平台依赖与安装校验。先在功能分支测试和评审，再由维护者决定合并。
