# A/B Street 本地副本

版本：v0.3.49。来源：https://github.com/a-b-street/abstreet/releases/tag/v0.3.49

- downloads/：官方 Windows 发布 ZIP 原件，未运行其中的 exe。
- web/0.3.49/：来自 https://play.abstreet.org/0.3.49/ 的 JS、WASM、CSS；data/ 从同版本官方 ZIP 提取。HTML 为 Traffic Pi 本地启动页。
- 这些大文件仅保留本地，已从 Git 排除，不混入应用源码。

启动 Traffic Pi 后，选择侧边栏“仿真工作台”，或访问 http://127.0.0.1:30141/abstreet/abstreet.html 。不要双击 HTML，WASM 需要 HTTP 服务。

第一阶段仅提供手动仿真画面，不提供 MCP 控制。工作台左侧保留交通任务对话，右侧显示仿真，小屏幕上下排列；可切换全屏。“收起”后再次打开会保留同一个仿真实例（隐藏不代表暂停，刷新页面会重置）。仅包含发布包随附地图，其他城市不保证离线可用。
