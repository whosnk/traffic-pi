"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./AbstreetPanel.module.css";
import { controlCurrentSimulation } from "@/lib/simulation-control";

const simulationUrl = "/abstreet/abstreet.html?../data/system/cn/chongqing/scenarios/yuzhong_core/weekday.bin&--time=08:00:00";

export function AbstreetPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState("");
  const [demo, setDemo] = useState("");
  const viewer = useRef("");
  const pending = useRef("");
  useEffect(() => {
    if (!open) return;
    viewer.current ||= crypto.randomUUID();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        if (document.visibilityState === "visible") {
          const response = await fetch(`/api/simulation-demo?viewer=${viewer.current}`);
          if (response.ok) {
            const { command, action } = await response.json();
            if (!stopped && command && pending.current !== command) {
              pending.current = command;
              if (action === "start") setDemo(command);
              else {
                let ok = false;
                try {
                  const doc = viewport.current?.querySelector("iframe")?.contentDocument;
                  if (!doc) throw new Error("当前仿真尚未加载。");
                  await controlCurrentSimulation(doc, action);
                  setError("");
                  ok = true;
                } catch (error) { setError(String(error)); }
                await fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: command, viewer: viewer.current, ok }) });
              }
            }
          }
        }
      } finally { if (!stopped) timer = setTimeout(() => { void poll().catch(() => {}); }, 1000); }
    }
    void poll().catch(() => {});
    return () => { stopped = true; clearTimeout(timer); };
  }, [open]);
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
    <section data-open={open} inert={!open} aria-hidden={!open} className={styles.workspace} aria-label="交通仿真工作台">
      <header className={styles.toolbar}>
        <div><small>TRAFFIC PI / 交通仿真</small><strong>交通仿真工作台</strong></div>
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
        <button type="button" onClick={onClose} aria-label="收起仿真">收起</button>
        </nav>
      </header>
      {error && <p role="status">{error}</p>}
      <div ref={viewport} className={styles.viewport}>
        {started && <iframe key={demo} title="本地交通仿真" src={simulationUrl} allow="fullscreen" onLoad={() => {
          if (demo) void fetch("/api/simulation-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "ack", id: demo, viewer: viewer.current }) }).catch(() => setError("演示启动确认失败，请重试。"));
        }} style={{ width: size.width / scale, height: size.height / scale, transform: `scale(${scale})`, transformOrigin: "top left" }} />}
      </div>
      <footer className={styles.footer}><span>本地仿真 · 手动操作</span><span>左侧对话 · 右侧场景</span></footer>
    </section>
  </>;
}
