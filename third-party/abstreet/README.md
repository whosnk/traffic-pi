# A/B Street 本地副本

版本：v0.3.49。来源：https://github.com/a-b-street/abstreet/releases/tag/v0.3.49

- downloads/：官方 Windows 发布 ZIP 原件，未运行其中的 exe。
- web/0.3.49/：基于 A/B Street v0.3.49 构建的中文 JS、WASM、CSS 和离线数据。HTML 为 Traffic Pi 本地启动页。
- customization/：中文文案映射，以及包含 Traffic Pi 浏览器控制接口的可重放源码补丁。
- chongqing/yuzhong_core.geojson：重庆渝中半岛核心区导入边界（106.514–106.591°E，29.535–29.579°N）。
- web/ 跟随应用提交，用于部署；downloads/ 仅保留本地。

启动 Traffic Pi 后，选择侧边栏“仿真工作台”，或访问 http://127.0.0.1:30141/abstreet/abstreet.html 。不要双击 HTML，WASM 需要 HTTP 服务。

默认加载重庆渝中半岛工作日场景，推进到 08:00 后暂停，等待治理工具读取或继续运行。地图基于 2026-09-20 通过 Overpass Kumi 镜像获取的 OpenStreetMap 数据，© OpenStreetMap contributors，按 ODbL 提供；出行需求由 A/B Street `random-scenario` 使用固定随机种子 42 合成，不代表真实交通需求。

中文治理包复现：使用独立的 A/B Street `v0.3.49` 源码检出、Rust `1.75.0`、`wasm32-unknown-unknown` 目标和 `wasm-bindgen-cli 0.2.88`。`customization/v0.3.49-traffic-pi.patch` 包含中文化及完整控制桥源码，不能再叠加旧的中文化补丁。Windows 可在 Traffic Pi 根目录执行：

```powershell
rustup target add wasm32-unknown-unknown --toolchain 1.75.0
cargo install wasm-bindgen-cli --version 0.2.88 --locked --root .next/wasm-tools
./third-party/abstreet/customization/build.ps1 -SourceRoot <独立的v0.3.49源码目录>
```

构建脚本只生成 `.next/abstreet-candidate` 候选包，不替换部署文件。手工构建可应用完整补丁、复制 `zh_cn.rs`，然后执行与脚本相同的 Cargo/wasm-bindgen 命令。临时源码目录不属于交付依赖；持久源码以补丁为准。

替换前保留部署中的 `game.js` 与 `game_bg.wasm`。先用 `node e2e/abstreet-workflow-bridge.mjs` 采集旧版对照，再设置 `TRAFFIC_PI_CANDIDATE=1` 运行同一测试，验证指标、信号、采集对比及镜头接口。通过后成对替换生成文件，并运行 `e2e/congestion-bridge.mjs` 与 `TRAFFIC_PI_REAL_BRIDGE=1` 的工作区测试。不要单独替换其中一个文件。

该 WASM 包暴露 Traffic Pi 命令桥，读取仿真状态、道路与路口指标，移动镜头和高亮道路，推进仿真，保存、修改及恢复信号方案，并按同一检查点和统计时段采集 A/B 指标。

新版桥在状态中声明 `traffic-pi-ui-v1`，增加 `set_native_ui`、`set_speed`、`get_view_state`、`fit_roads`、`global_view`、`zoom_view`、`cancel_camera`；`focus_on_road` 可接收 `smooth`。这些接口操作画布与面板，不改变仿真时间控制。统一界面关闭被替代原生面板的绘制和事件；“更多”恢复原生操作。暂停时仍处理桥命令及镜头动画，不推进仿真。

道路速度沿用旧桥的在途车辆行程累计距离／累计时间平均值，并非路侧瞬时测速；道路查询默认仅返回排队排名前 20 条机动车道路。指标中的缺失值及采集范围需要在解释结果时保留。常驻流程接通拥堵检测及拥堵溯源与配时验证，其他技能保持原行为。

`focus_on_road`、`fit_roads` 和 `global_view` 支持可选 `padding: { left, top, right, bottom }`，单位为仿真画布内的 CSS 像素。省略时保持居中行为；传入时在剩余可视区域内居中及适配范围。Traffic Pi 根据悬浮控件尺寸及 iframe 缩放换算留白，避免目标道路被流程或详情面板遮挡。留白不得为负或占满画布。

配时验证桥声明 `traffic-pi-mitigation-v1`，源码位于补丁中的 `traffic_mitigation.rs`。`mitigation_context` 返回道路端点、进口车道、转向／相位、当前等待、下游占用和累计通过数；`mitigation_begin/checkpoint/restore/cancel/finish/heartbeat` 使用任务租约保存及恢复本轮状态。检查点使用仿真器二进制 savestate 保存调度、车辆、需求、随机及信号控制状态，避免多个完整对象副本耗尽 WASM 内存。30 秒失去心跳时尝试恢复起点；页面销毁后不能承诺恢复已销毁实例。

任务锁阻止普通时间／配时写入，地图与查询仍可用。`run_for` 的 `displaySpeed: 5` 按实际经过时间定速推进并保持显示，结束后暂停。候选只支持固定配时，保持周期、offset 与转向权限，并经过行人约束校验。含自适应阶段（包括自适应行人阶段）的路口不会被自动转换。

新桥兼容测试：`TRAFFIC_PI_CANDIDATE=1` 和 `TRAFFIC_PI_CANDIDATE_DIR=.next/abstreet-mitigation-candidate` 运行 `e2e/abstreet-workflow-bridge.mjs`；`node e2e/abstreet-mitigation-bridge.mjs` 检查真实重庆桥的同起点重跑、可见推进、锁与取消恢复。后者在独立测试窗口临时构造固定配时，不修改交付场景。`node e2e/mitigation-workspace.mjs` 使用真实 MCP/SSE 接收链与仿真替身验证选择授权、六阶段流程、方案弹窗、结果及窄屏交互。
