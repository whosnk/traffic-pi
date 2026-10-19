# SUMO 最小强化学习信号灯项目骨架

这是一个**单路口、单信号灯、单智能体 PPO** 的最小可运行骨架。

## 目录

```text
sumo_min_rl_skeleton/
├─ cfg/
│  └─ intersection.sumocfg
├─ models/
├─ network/
│  ├─ intersection.edg.xml
│  ├─ intersection.nod.xml
│  └─ intersection.net.xml   # 运行 build_net.py 后生成
├─ outputs/
├─ routes/
│  └─ intersection.rou.xml
├─ scripts/
│  ├─ build_net.py
│  └─ common.py
├─ run_gui.py
├─ train.py
├─ requirements.txt
└─ README.md
```

## 你会得到什么

- 路：四进口单路口
- 车：东西向和南北向持续流量
- 信号灯：中心路口 `c` 为 `traffic_light`，由 `netconvert` 生成受控路口
- 强化学习：`sumo-rl` + `stable-baselines3(PPO)`

## 依赖

1. 先安装 SUMO，并设置环境变量 `SUMO_HOME`
2. 再安装 Python 依赖

Linux 常见安装方式：

```bash
sudo apt-get install sumo sumo-tools sumo-doc
export SUMO_HOME=/usr/share/sumo
pip install -r requirements.txt
```

Windows 常见方式：

- 安装 SUMO
- 把 `SUMO_HOME` 设为你的 SUMO 安装目录，例如 `C:\Program Files (x86)\Eclipse\Sumo`
- 再执行：

```bash
pip install -r requirements.txt
```

## 运行步骤

### 1) 生成路网

```bash
python scripts/build_net.py
```
这一步会把：

- `network/intersection.nod.xml`
- `network/intersection.edg.xml`

编译成：

- `network/intersection.net.xml`

### 2) 用 GUI 先看静态仿真

```bash
python run_gui.py
```

### 3) 训练 RL 信号灯

```bash
python train.py --timesteps 20000
```

训练结束后会生成：

- 模型：`models/ppo_intersection.zip`
- 训练输出：`outputs/ppo_train*`
- 评估输出：`outputs/ppo_eval*`

## 后续你最值得改的 3 个点

### 1. 车流
直接改 `routes/intersection.rou.xml` 里的 `flow` 即可。

### 2. 路网
把单路口扩成 2x2 / 4x4，或者换成 OSM 导入路网。

### 3. 奖励函数 / 观测
当前直接使用 `sumo-rl` 默认观测与奖励；你可以在后续替换成自己的队列长度、延误、通行量等指标。

## 常见报错

### 报错：未检测到 SUMO_HOME
说明你没有正确设置 SUMO 的环境变量。

### 报错：找不到 intersection.net.xml
说明你还没执行：

```bash
python scripts/build_net.py
```
