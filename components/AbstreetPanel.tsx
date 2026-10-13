"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./AbstreetPanel.module.css";
import { controlCurrentSimulation } from "@/lib/simulation-control";

const simulationUrl = "/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00";

export function AbstreetPanel({ open, receiving }: { open: boolean; receiving: boolean }) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState("");
  const viewer = useRef("");
  const pending = useRef("");
  useEffect(() => {
    if (!receiving || !started) return;
    viewer.current ||= crypto.randomUUID();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        if (document.visibilityState === "visible") {
          const response = await fetch(`/api/simulation-demo?viewer=${viewer.current}`);
          if (response.ok) {
            const { command } = await response.json();
            if (!stopped && command && pending.current !== command.id) {
              pending.current = command.id;
              if (command.action === "start") setDemo(command.id);
              else {
                let ok = false;
                let result: unknown;
                let message = "";
                try {
                  const doc = viewport.current?.querySelector("iframe")?.contentDocument;
                  if (!doc) throw new Error("当前仿真尚未加载。");
                  result = await controlCurrentSimulation(doc, command.action, command.params);
                  setError("");
                  ok = true;
                } catch (error) { message = error instanceof Error ? error.message : String(error); setError(message); }
                await fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: command.id, viewer: viewer.current, ok, result, error: message }) });
              }
            }
          }
        }
      } finally { if (!stopped) timer = setTimeout(() => { void poll().catch(() => {}); }, 1000); }
    }
    void poll().catch(() => {});
    return () => { stopped = true; clearTimeout(timer); };
  }, [receiving, started]);
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1500, height: 900 });
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    let resizeTimer: ReturnType<typeof setTimeout>;
    const observer = new ResizeObserver(([entry]) => {
      clearTimeout(resizeTimer);
      if (entry.contentRect.width && entry.contentRect.height) {
        const { width, height } = entry.contentRect;
        resizeTimer = setTimeout(() => setSize({ width, height }), 100);
      }
    });
    observer.observe(element);
    return () => { clearTimeout(resizeTimer); observer.disconnect(); };
  }, []);
  const scale = Math.min(1, size.width / 1500);
  if (open && !started) setStarted(true);

  return <>
    <section inert={!open} aria-hidden={!open} className={styles.workspace} aria-label="交通仿真工作台">
      <header className={styles.toolbar}>
        <div><small>方案验证</small><strong>本地仿真实例</strong><span className={styles.sceneChip}>重庆 · 渝中半岛 · 初始时间 08:00</span></div>
        <nav aria-label="仿真视图" className={styles.actions}>
        <span style={{ fontSize: 12, color: "var(--accent)" }}>自动接收 MCP 演示</span>
        <a href={simulationUrl} target="_blank" rel="noopener noreferrer">独立打开</a>
        <button type="button" onClick={async () => {
          try {
            setError("");
            if (document.fullscreenElement) await document.exitFullscreen();
            else await document.documentElement.requestFullscreen();
          } catch { setError("当前浏览器无法切换全屏，可使用独立打开。"); }
        }}>切换全屏</button>
        </nav>
      </header>
      {error && <p role="status">{error}</p>}
      <div ref={viewport} className={styles.viewport}>
        {started && <iframe key={demo} title="本地交通仿真" src={simulationUrl} allow="fullscreen" onLoad={() => {
          if (demo) void fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: demo, viewer: viewer.current, result: { message: "场景正在重新加载。", simulationTime: null } }) }).catch(() => setError("演示启动确认失败，请重试。"));
        }} style={{ width: size.width / scale, height: size.height / scale, transform: `scale(${scale})`, transformOrigin: "top left" }} />}
      </div>
      <footer className={styles.footer}><span>共享本地实例 · 切换会话保留进度</span><span>收起工作区不暂停仿真</span></footer>
    </section>
  </>;
}
