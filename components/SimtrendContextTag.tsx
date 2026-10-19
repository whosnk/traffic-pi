"use client";

import { simtrendContextStore, useSimtrendContext } from "@/lib/simtrend-context";

export function SimtrendContextTag({ contextKey }: { contextKey: string }) {
  const context = useSimtrendContext(contextKey);
  if (!context) return null;
  return <section aria-label="当前对话空间定位" className="simtrend-context-tag">
    <div><strong>当前场景：{context.scenarioName}</strong>
      {context.selection ? <span>
        {context.selection.label} · 道路 <code>{context.selection.edge_id}</code>
        {context.selection.lane_id ? <> · 车道 <code>{context.selection.lane_id}</code></> : " · 未选具体车道"}
        {context.selection.zone_id && <> · 上客区 <code>{context.selection.zone_id}</code></>}
      </span> : <span>未选择道路或车道，不自动沿用历史定位。</span>}
      <small>随本条消息发送，不会因选中对象自动运行仿真。</small>
      {context.incidentDraft && <small>事件任务草案已关联，可继续用对话修改参数。</small>}
    </div>
    {context.selection && <button type="button" aria-label="取消空间定位" onClick={() => simtrendContextStore.select(contextKey, context.scenarioId, null)}>取消定位</button>}
  </section>;
}
