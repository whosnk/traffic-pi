from __future__ import annotations

import argparse
import os
from pathlib import Path

import gymnasium as gym
from stable_baselines3 import PPO

# 必须先确保 SUMO_HOME 存在，再导入 sumo_rl
from scripts.common import project_root, sumo_home

sumo_home()
import sumo_rl  # noqa: E402,F401


def build_env(use_gui: bool, out_csv_name: str):
    root = project_root()
    net_file = root / "network" / "intersection.net.xml"
    route_file = root / "routes" / "intersection.rou.xml"

    if not net_file.exists():
        raise FileNotFoundError(
            "未找到 network/intersection.net.xml，请先运行 python scripts/build_net.py"
        )

    env = gym.make(
        "sumo-rl-v0",
        net_file=str(net_file),
        route_file=str(route_file),
        out_csv_name=out_csv_name,
        use_gui=use_gui,
        num_seconds=3600,
        delta_time=5,
        yellow_time=2,
        min_green=5,
        max_green=60,
        single_agent=True,
    )
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a PPO traffic light controller on a minimal SUMO intersection.")
    parser.add_argument("--timesteps", type=int, default=20000, help="Total PPO training timesteps.")
    parser.add_argument("--gui", action="store_true", help="Run training with SUMO GUI.")
    args = parser.parse_args()

    root = project_root()
    os.makedirs(root / "models", exist_ok=True)
    os.makedirs(root / "outputs", exist_ok=True)

    train_env = build_env(use_gui=args.gui, out_csv_name=str(root / "outputs" / "ppo_train"))

    print("observation_space:", train_env.observation_space)
    print("action_space:", train_env.action_space)

    model = PPO(
        policy="MlpPolicy",
        env=train_env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        gamma=0.99,
        tensorboard_log=str(root / "outputs" / "tb"),
    )
    model.learn(total_timesteps=args.timesteps, progress_bar=True)

    model_path = root / "models" / "ppo_intersection"
    model.save(str(model_path))
    train_env.close()
    print(f"[OK] model saved to {model_path}.zip")

    eval_env = build_env(use_gui=args.gui, out_csv_name=str(root / "outputs" / "ppo_eval"))
    obs, info = eval_env.reset()
    terminated = False
    truncated = False
    total_reward = 0.0

    while not (terminated or truncated):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = eval_env.step(action)
        total_reward += float(reward)

    eval_env.close()
    print(f"[OK] eval total_reward = {total_reward:.3f}")


if __name__ == "__main__":
    main()
