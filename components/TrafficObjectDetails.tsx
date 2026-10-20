"use client";

import type { ReactNode } from "react";
import styles from "./AbstreetPanel.module.css";

export function ObjectDetails({ title, subtitle, anchor, bounds, onClose, children, label = "对象详情", safeTop = 12 }: {
  title: string; subtitle: string; anchor: { x: number; y: number }; bounds: { width: number; height: number }; onClose: () => void; children: ReactNode; label?: string; safeTop?: number;
}) {
  const width = Math.min(270, bounds.width - 24);
  const left = Math.max(12, Math.min(bounds.width - width - 12, anchor.x + width + 36 < bounds.width ? anchor.x + 24 : anchor.x - width - 24));
  const maxHeight = Math.max(90, bounds.height - safeTop - 58);
  const top = Math.max(safeTop, Math.min(bounds.height - Math.min(270, maxHeight) - 58, anchor.y - 100));
  return <div className={styles.objectLayer}>
    <svg aria-hidden="true"><line x1={anchor.x} y1={anchor.y} x2={left + width / 2} y2={top + 80} /><circle cx={anchor.x} cy={anchor.y} r="5" /></svg>
    <section className={styles.objectDetails} aria-label={label} style={{ left, top, width, maxHeight }} onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
      <header><div><small>{subtitle}</small><strong>{title}</strong></div><button type="button" onClick={onClose} aria-label="关闭道路详情">×</button></header>
      {children}
    </section>
  </div>;
}
