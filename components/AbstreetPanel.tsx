"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./AbstreetPanel.module.css";

export function AbstreetPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState("");
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1500, height: 900 });
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width && entry.contentRect.height) {
        setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const scale = Math.min(1, size.width / 1500);
  if (open && !started) setStarted(true);

  return <>
    <section hidden={!open} className={styles.workspace} aria-label="A/B Street 仿真工作台">
      <header className={styles.toolbar}>
        <div><small>TRAFFIC PI / SIMULATION</small><strong>交通仿真工作台 <span> · A/B Street</span></strong></div>
        <nav aria-label="仿真视图" className={styles.actions}>
        <a href="/abstreet/abstreet.html" target="_blank" rel="noopener noreferrer">独立打开</a>
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
        {started && <iframe title="A/B Street 本地仿真" src="/abstreet/abstreet.html" allow="fullscreen" style={{ width: size.width / scale, height: size.height / scale, transform: `scale(${scale})`, transformOrigin: "top left" }} />}
      </div>
      <footer className={styles.footer}><span>本地仿真 · 手动操作</span><span>左侧对话 · 右侧场景</span></footer>
    </section>
  </>;
}
