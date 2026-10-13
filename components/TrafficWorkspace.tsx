"use client";

import { AbstreetPanel } from "./AbstreetPanel";
import { GeoMapPanel } from "./GeoMapPanel";
import type { GeoScene } from "@/lib/geo-types";

export type TrafficView = "gis" | "simulation";

type Props = {
  open: boolean;
  view: TrafficView;
  sessionId: string | null;
  scene: GeoScene | null;
  unread: boolean;
  focusRequest: number;
  onViewChange: (view: TrafficView) => void;
  onViewResult: () => void;
  onClose: () => void;
};

export function TrafficWorkspace({ open, view, sessionId, scene, unread, focusRequest, onViewChange, onViewResult, onClose }: Props) {
  return <section id="traffic-workspace" className="traffic-workspace" data-open={open} data-view={view} inert={!open} aria-hidden={!open} aria-label="交通工作区">
    <header className="traffic-workspace-header">
      <div><small>TRAFFIC PI</small><strong>交通工作区</strong><span>与左侧交通智能体协同分析</span></div>
      <button type="button" onClick={onClose} aria-label="收起交通工作区">收起</button>
    </header>
    <nav className="traffic-workspace-views" aria-label="交通工具">
      <button type="button" aria-pressed={view === "gis"} aria-controls="traffic-gis-view" onClick={() => onViewChange("gis")}><span aria-hidden="true">▧</span> GIS · 路网观察{unread && <span className="traffic-result-badge">有新结果</span>}</button>
      <button type="button" aria-pressed={view === "simulation"} aria-controls="traffic-simulation-view" onClick={() => onViewChange("simulation")}><span aria-hidden="true">▷</span> 仿真 · 方案验证</button>
      {unread && <button type="button" className="traffic-view-result" onClick={onViewResult}>查看结果</button>}
    </nav>
    <div className="traffic-workspace-content">
      <div id="traffic-gis-view" className="traffic-workspace-pane" data-visible={view === "gis"} inert={!open || view !== "gis"} aria-hidden={!open || view !== "gis"}>
        <GeoMapPanel key={sessionId ?? "new"} scene={scene} active={open && view === "gis"} focusRequest={focusRequest} />
      </div>
      <div id="traffic-simulation-view" className="traffic-workspace-pane" data-visible={view === "simulation"} inert={!open || view !== "simulation"} aria-hidden={!open || view !== "simulation"}>
        <AbstreetPanel open={open && view === "simulation"} receiving={open} />
      </div>
    </div>
  </section>;
}
