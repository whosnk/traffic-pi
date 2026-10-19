# SimTrend 场景库

每个子文件夹代表一个可切换仿真场景，至少需要包含：

- `scenario.json`：场景名称、说明、默认示例语句、交叉口提示和支持能力。
- `network/intersection.net.xml`：路网文件。
- `routes/intersection.rou.xml`：交通需求与路线文件。
- `cfg/intersection.sumocfg`：基础仿真配置。
- `scripts/build_net.py`、`run_gui.py`、`train.py`：当前工具链校验所需文件。

新增场景时，可以复制 `four_intersections`，修改 `scenario.json`、路网和路线文件后重启 Streamlit。

当前已注册场景：

- `four_intersections`：四交叉口标准流量场景。
- `four_intersections_light`：四交叉口轻流量场景。
- `nanjing_south_ride_hailing`：南京南站网约车停车管理核心区真实路网场景。
