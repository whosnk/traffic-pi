"use client";

import { scenarioSwitchReason } from "@/lib/traffic-scenarios";
import { useSimtrendContext } from "@/lib/simtrend-context";
import { mitigationStore } from "@/lib/mitigation-store";
import { congestionStore } from "@/lib/congestion-store";
import { AbstreetPanel } from "./AbstreetPanel";
import { SimtrendPanel } from "./SimtrendPanel";
import { GeoMapPanel } from "./GeoMapPanel";
import type { GeoScene } from "@/lib/geo-types";

export type TrafficView = "gis" | "abstreet" | "sumo";

type Props = {
  open: boolean;
  agentBusy: boolean;
  view: TrafficView;
  sessionId: string | null;
  contextKey: string;
  scene: GeoScene | null;
  unread: boolean;
  focusRequest: number;
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

export function TrafficWorkspace({ open, agentBusy, view, sessionId, contextKey, scene, unread, focusRequest, onViewResult, onClose, chatOpen, resultsOpen, onToggleChat, onToggleResults, historical, onLatest, resultCount }: Props) {
  const context = useSimtrendContext(contextKey);
  const switchReason = () => scenarioSwitchReason({ mitigationBusy: mitigationStore.switchBlocked(), detectionBusy: congestionStore.busy(), agentBusy });
  const title = { abstreet: "仿真工作台", sumo: "仿真实验", gis: "分析与报告" }[view];
  return <section id="traffic-workspace" className="traffic-workspace" data-open={open} data-view={view} inert={!open} aria-hidden={!open} aria-label="交通工作区">
    <header className="traffic-workspace-header">
      <div><small>TRAFFIC PI</small><strong>{title}</strong><span>{view === "gis" ? "空间分析与图层 · GIS" : view === "abstreet" ? "城市交通 / 高速公路 · A/B Street" : view === "sumo" ? `${context?.scenarioName ?? "选择实验场景"} · SUMO` : "按场景选择可视化与计算能力"}</span></div>
      <div className="traffic-workspace-actions"><button type="button" onClick={onToggleChat} aria-expanded={chatOpen}>对话</button><button type="button" onClick={onToggleResults} aria-expanded={resultsOpen}>分析结果<span className="traffic-new-count" style={{ visibility: resultCount ? "visible" : "hidden" }}>{resultCount} 条新结果</span></button><button type="button" onClick={onClose} aria-label="收起交通工作区">收起</button></div>
    </header>
    {unread && <div className="traffic-history-notice" role="status"><span>空间分析有新图层</span><button type="button" onClick={onViewResult}>查看结果</button></div>}
    {historical && view === "gis" && <div className="traffic-history-notice" role="status"><span>正在查看历史结果 · revision {scene?.revision}</span><button type="button" onClick={onLatest}>返回最新结果</button></div>}
    <div className="traffic-workspace-content">
      <div id="traffic-gis-view" className="traffic-workspace-pane" data-visible={view === "gis"} inert={!open || view !== "gis"} aria-hidden={!open || view !== "gis"}>
        <GeoMapPanel key={sessionId ?? "new"} scene={scene} active={open && view === "gis"} focusRequest={focusRequest} />
      </div>
      <div id="traffic-simulation-view" className="traffic-workspace-pane" data-visible={view === "abstreet"} inert={!open || view !== "abstreet"} aria-hidden={!open || view !== "abstreet"}>
        <AbstreetPanel agentBusy={agentBusy} open={open && view === "abstreet"} receiving={true} sessionId={sessionId} onViewResults={() => { if (!resultsOpen) onToggleResults(); }} />
      </div>
      <div id="traffic-sumo-view" className="traffic-workspace-pane" data-visible={view === "sumo"} inert={!open || view !== "sumo"} aria-hidden={!open || view !== "sumo"}><SimtrendPanel key={contextKey} contextKey={contextKey} active={open && view === "sumo"} sessionId={sessionId} switchReason={switchReason} /></div>
    </div>
  </section>;
}
