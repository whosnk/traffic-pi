import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../integrations/simtrend");
const child = spawn(process.env.SIMTREND_PYTHON || "python", [resolve(root, "mcp_server.py")], {
  cwd: root, stdio: "inherit", windowsHide: true,
  env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
});
child.on("error", error => { console.error("SimTrend Python startup:", error.message); process.exit(1); });
child.on("exit", code => process.exit(code ?? 1));
for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => child.kill(signal));
