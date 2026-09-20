# A/B Street 本地副本

版本：v0.3.49。来源：https://github.com/a-b-street/abstreet/releases/tag/v0.3.49

- downloads/：官方 Windows 发布 ZIP 原件，未运行其中的 exe。
- web/0.3.49/：基于 A/B Street v0.3.49 构建的中文 JS、WASM、CSS 和离线数据。HTML 为 Traffic Pi 本地启动页。
- customization/：中文文案映射，以及包含 Traffic Pi 浏览器控制接口的可重放源码补丁。
- chongqing/yuzhong_core.geojson：重庆渝中半岛核心区导入边界（106.514–106.591°E，29.535–29.579°N）。
- web/ 跟随应用提交，用于部署；downloads/ 仅保留本地。

启动 Traffic Pi 后，选择侧边栏“仿真工作台”，或访问 http://127.0.0.1:30141/abstreet/abstreet.html 。不要双击 HTML，WASM 需要 HTTP 服务。

默认加载重庆渝中半岛工作日场景，推进到 08:00 后暂停，等待治理工具读取或继续运行。地图基于 2026-09-20 通过 Overpass Kumi 镜像获取的 OpenStreetMap 数据，© OpenStreetMap contributors，按 ODbL 提供；出行需求由 A/B Street `random-scenario` 使用固定随机种子 42 合成，不代表真实交通需求。

中文治理包复现：检出 A/B Street `v0.3.49`，使用 Rust `1.75.0` 和 `wasm32-unknown-unknown` 目标，执行 `git apply --unidiff-zero customization/v0.3.49-traffic-pi.patch`，将 `customization/zh_cn.rs` 复制到 `widgetry/src/zh_cn.rs`，然后在 `web/` 执行 `WASM_PACK_FLAGS=--release make abstreet`。生成的 `game.js` 与 `game_bg.wasm` 必须成对替换。

该 WASM 包暴露 Traffic Pi 命令桥，读取仿真状态、道路与路口指标，移动镜头和高亮道路，推进仿真，保存、修改及恢复信号方案，并按同一检查点和统计时段采集 A/B 指标。
