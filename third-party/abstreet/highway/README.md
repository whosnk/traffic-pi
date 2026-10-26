# 典型高速演示资源

Traffic Pi 自建的合成路网与需求，不代表重庆或其他地区的真实高速。
地图为约 2 km 的双向分隔主线，每方向 3 条机动车道，具有东、西向出入口匝道和两端立交连接匝道；主线上没有信号交叉口。
立交连接线与主线仅几何跨越，不共享节点。坐标用于 A/B Street 投影，不表示现场道路。

生成物：

- `highway-demo.osm`：路网源文件；`boundary.geojson`：裁剪边界。
- `demand.json`：1,530 条确定性边界到边界机动车出行，07:58–08:32，每 4 秒双向主线供给，每 8 秒增加汇入需求，包含驶出需求。
- `../web/0.3.49/data/system/cn/chongqing/maps/highway-demo.bin`。
- `../web/0.3.49/data/system/cn/chongqing/scenarios/highway-demo/motorway.bin`。

沿用现有补丁的导入命名空间 `cn/chongqing`，以启用中文字体；场景地图身份是独立的 `highway-demo`，不借用重庆二进制。

## 重建

使用独立 A/B Street `v0.3.49`（`c0d3b73`）源码、Rust 1.75.0，按上级 README 应用 `customization/v0.3.49-traffic-pi.patch` 并复制 `zh_cn.rs`。不需要临时源码目录；以下示例路径可替换为任意独立源码检出：

```powershell
cargo +1.75.0 build --manifest-path 'D:/abstreet-v0.3.49/Cargo.toml' -p cli --release --locked
node third-party/abstreet/highway/generate.mjs 'D:/abstreet-v0.3.49/target/release/cli.exe'
```

脚本调用原生 `oneshot-import` 和 `import-scenario`，校验双向路网未被丢弃、主线车道数及无信号，再复制成对的地图与需求文件。中间文件写入 `.next/highway-build`。需求起终点在裁剪边界外，导入器匹配为明确边界，不使用住宅需求生成器。时刻按 v0.3.49 的万分之一秒整数序列化。运行种子为 42。

启动 `npm run dev` 后，执行 `node e2e/abstreet-scenes.mjs`，实际加载部署中的 JS/WASM，验证地图身份、两个方向及出入口上实际车辆、1× 时间推进、城市往返切换及基础控件。脚本不使用仿真替身；仅对话会话和设置 API 使用测试夹具。

需求供给结束于 08:32；工作台在 08:35 停止本轮演示并提供重新播放。1× 的完整供给时长为 32 分钟，不用前端动画或视频替代车辆。
