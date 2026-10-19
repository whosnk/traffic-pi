import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { getProjectTrustStatus } from "./project-trust";

export const simtrendRoot = () => resolve(process.cwd(), "integrations/simtrend");

export async function simtrendCall(input: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (!getProjectTrustStatus(process.cwd(), getAgentDir()).trusted) {
    throw new Error("请先在 Traffic Pi 的项目提示中信任当前项目，然后重新打开仿真面板。");
  }
  return new Promise((done, reject) => {
    const root = simtrendRoot();
    const child = spawn(process.env.SIMTREND_PYTHON || "python", [resolve(root, "web_bridge.py")], {
      cwd: root, windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
    });
    let output = "", error = "";
    const timer = setTimeout(() => { child.kill(); reject(new Error("SimTrend 请求超时，请检查 Python 环境。")); }, 30000);
    child.stdout.setEncoding("utf8").on("data", chunk => {
      output += chunk;
      if (output.length > 16 * 1024 * 1024) { child.kill(); reject(new Error("返回数据过大。")); }
    });
    child.stderr.setEncoding("utf8").on("data", chunk => { error = (error + chunk).slice(-2000); });
    child.once("error", () => { clearTimeout(timer); reject(new Error("无法启动 SimTrend。请配置 SIMTREND_PYTHON 并安装 integrations/simtrend/requirements.txt。")); });
    child.once("close", code => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error("SimTrend Python 启动失败，请检查依赖。" + (error.includes("ModuleNotFoundError") ? " 缺少 Python 模块。" : "")));
      try { done(JSON.parse(output)); } catch { reject(new Error("SimTrend 返回了无效数据。")); }
    });
    child.stdin.on("error", () => {});
    child.stdin.end(JSON.stringify(input));
  });
}
