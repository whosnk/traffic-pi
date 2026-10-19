"use client";

import { AbstreetPanel } from "./AbstreetPanel";
import { SimtrendPanel } from "./SimtrendPanel";
import { GeoMapPanel } from "./GeoMapPanel";
import type { GeoScene } from "@/lib/geo-types";

export type TrafficView = "gis" | "abstreet" | "sumo";

type Props = {
  open: boolean;
  view: TrafficView;
  sessionId: string | null;
  contextKey: string;
  scene: GeoScene | null;
  unread: boolean;
  focusRequest: number;
  onViewChange: (view: TrafficView) => void;
  onViewResult: () => void;
  onClose: () => void;
  chatOpen: boolean;
  resultsOpen: boolean;
  onToggleChat: () => void;
  onToggleResults: () => void;
  historical: boolean;
  onLatest: () => void;
  resultCount: number;
};

export function TrafficWorkspace({ open, view, sessionId, contextKey, scene, unread, focusRequest, onViewChange, onViewResult, onClose, chatOpen, resultsOpen, onToggleChat, onToggleResults, historical, onLatest, resultCount }: Props) {
  return <section id="traffic-workspace" className="traffic-workspace" data-open={open} data-view={view} inert={!open} aria-hidden={!open} aria-label="交通工作区">
    <header className="traffic-workspace-header">
      <div><small>TRAFFIC PI</small><strong>交通工作区</strong><span>{view === "gis" ? "路网观察与空间结果" : view === "abstreet" ? "本地仿真 · 方案验证" : "SimTrend · 交通仿真"}</span></div>
      <div className="traffic-workspace-actions"><button type="button" onClick={onToggleChat} aria-expanded={chatOpen}>对话</button><button type="button" onClick={onToggleResults} aria-expanded={resultsOpen}>分析结果<span className="traffic-new-count" style={{ visibility: resultCount ? "visible" : "hidden" }}>{resultCount} 条新结果</span></button><button type="button" onClick={onClose} aria-label="收起交通工作区">收起</button></div>
    </header>
    <nav className="traffic-workspace-views" aria-label="交通工具">
      <button type="button" aria-pressed={view === "gis"} aria-controls="traffic-gis-view" onClick={() => onViewChange("gis")}><span aria-hidden="true">▧</span> GIS · 路网观察{unread && <span className="traffic-result-badge">有新结果</span>}</button>
      <button type="button" aria-pressed={view === "abstreet"} aria-controls="traffic-simulation-view" onClick={() => onViewChange("abstreet")}><span aria-hidden="true">▷</span> A/B Street · 方案验证</button>
      <button type="button" aria-pressed={view === "sumo"} aria-controls="traffic-sumo-view" onClick={() => onViewChange("sumo")}>SimTrend · 交通仿真</button>
      {unread && <button type="button" className="traffic-view-result" onClick={onViewResult}>查看结果</button>}
    </nav>
    {historical && view === "gis" && <div className="traffic-history-notice" role="status"><span>正在查看历史结果 · revision {scene?.revision}</span><button type="button" onClick={onLatest}>返回最新结果</button></div>}
    <div className="traffic-workspace-content">
      <div id="traffic-gis-view" className="traffic-workspace-pane" data-visible={view === "gis"} inert={!open || view !== "gis"} aria-hidden={!open || view !== "gis"}>
        <GeoMapPanel key={sessionId ?? "new"} scene={scene} active={open && view === "gis"} focusRequest={focusRequest} />
      </div>
      <div id="traffic-simulation-view" className="traffic-workspace-pane" data-visible={view === "abstreet"} inert={!open || view !== "abstreet"} aria-hidden={!open || view !== "abstreet"}>
        <AbstreetPanel open={open && view === "abstreet"} receiving={open} />
      </div>
      <div id="traffic-sumo-view" className="traffic-workspace-pane" data-visible={view === "sumo"} inert={!open || view !== "sumo"} aria-hidden={!open || view !== "sumo"}><SimtrendPanel key={contextKey} contextKey={contextKey} active={open && view === "sumo"} sessionId={sessionId} /></div>
    </div>
  </section>;
}
