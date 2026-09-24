"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentTrace, AgentTraceEvent, api, agentModePreference } from "@/lib/api";
import {
  DataTable,
  EmptyState,
  ErrorState,
  Kicker,
  MetricStrip,
  PageHeader,
  SkeletonRows,
  Status,
  TRow,
  TraceRow,
  fmtMs,
  fmtNum,
  fmtTime,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

// key 与后端 stage 值一致（不翻译）；name 为本地展示层文案。
const STAGES = [
  { key: "query_received", name: "接收查询" },
  { key: "query_rewrite", name: "查询改写" },
  { key: "acl_filter", name: "权限过滤" },
  { key: "vector_search", name: "向量检索" },
  { key: "bm25", name: "关键词检索（BM25）" },
  { key: "hybrid_fusion", name: "混合融合" },
  { key: "rerank", name: "重排序" },
  { key: "context_build", name: "上下文组装" },
  { key: "generation", name: "模型生成" },
  { key: "citation_verify", name: "引用核验" },
];

type StageRow = { key: string; name: string; ms: number | null; status: string | null; detail: string | null };

function deriveStages(trace: AgentTrace): StageRow[] {
  const events = trace.events || [];
  const stageEvents = events.filter((event) => (event as { type?: string }).type === "stage");
  return STAGES.map((stage) => {
    const match = stageEvents.find((event) => (event as { stage?: string }).stage === stage.key);
    if (match) {
      const raw = match as unknown as { elapsed_ms?: number; status?: string; detail?: string };
      return { ...stage, ms: raw.elapsed_ms ?? null, status: raw.status || "ok", detail: raw.detail || null };
    }
    // Legacy traces: best-effort derivation from tool/round events.
    if (stage.key === "query_received") return { ...stage, ms: 0, status: "ok", detail: "请求信封" };
    if (stage.key === "generation") {
      const rounds = events.filter((event) => /llm|generate|round/i.test(String(event.type)));
      const ms = rounds.reduce((sum, event) => sum + (event.latency_ms || 0), 0);
      return { ...stage, ms: ms || null, status: rounds.length ? "ok" : null, detail: rounds.length ? `${rounds.length} 轮模型调用` : "旧版追踪记录" };
    }
    if (stage.key === "vector_search" || stage.key === "bm25") {
      const tools = events.filter((event) => /search|retrieve|bm25|vector/i.test(String(event.tool || event.type || "")));
      const ms = tools.reduce((sum, event) => sum + (event.latency_ms || 0), 0);
      return { ...stage, ms: tools.length ? ms : null, status: tools.length ? "ok" : null, detail: tools.length ? `${fmtNum(tools.length)} 次工具调用` : "旧版追踪记录 — 无分阶段耗时" };
    }
    return { ...stage, ms: null, status: null, detail: "旧版追踪记录 — 无分阶段耗时" };
  });
}

export default function TraceView({ navigate, payload }: ViewProps) {
  const [traceId, setTraceId] = useState(payload?.traceId || agentModePreference.lastTraceId() || "");
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      setTrace(await api.agentTrace(id));
    } catch (e) {
      setTrace(null);
      setError(e instanceof Error ? e.message : "追踪记录加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (payload?.traceId) { setTraceId(payload.traceId); void load(payload.traceId); }
  }, [payload?.traceId, load]);

  const stages = useMemo(() => (trace ? deriveStages(trace) : []), [trace]);
  const maxMs = Math.max(1, ...stages.map((stage) => stage.ms || 0));
  const bottleneck = stages.reduce<StageRow | null>((worst, stage) => (stage.ms && (!worst || stage.ms > (worst.ms || 0)) ? stage : worst), null);

  return (
    <>
      <PageHeader
        kicker="06 请求追踪 · 十阶段全链路耗时"
        title="请求追踪"
        desc="每次 RAG 请求都可端到端复查：定位问题出在检索、重排序、上下文组装、模型生成还是引用核验阶段。"
        actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => navigate("ask")}>返回问答</button>}
      />

      <form className="actions-row mb-6" onSubmit={(e) => { e.preventDefault(); void load(traceId); }}>
        <input className="input" style={{ maxWidth: 420 }} value={traceId} onChange={(e) => setTraceId(e.target.value)} placeholder="追踪 ID（UUID）" aria-label="追踪 ID" />
        <button type="submit" className="btn btn--primary btn--sm" disabled={loading || !traceId.trim()}>加载追踪</button>
        {agentModePreference.lastTraceId() && traceId !== agentModePreference.lastTraceId() && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => { setTraceId(agentModePreference.lastTraceId()); void load(agentModePreference.lastTraceId()); }}>使用最近一次请求</button>
        )}
      </form>

      {loading && <SkeletonRows rows={8} />}
      {error && <ErrorState title="追踪记录不可用" what={error} cause="该追踪 ID 在本环境中不存在或已过期。" next="先提出一个问题 — 系统会自动保存最近一次请求的追踪 ID。" actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => void load(traceId)}>重试</button>} />}

      {!loading && !trace && !error && <EmptyState code="追踪 / 未加载记录" title="尚未选择追踪记录。" desc="在工作区提出一个问题后打开它的追踪记录，或在上方粘贴追踪 ID。" />}

      {trace && (
        <>
          <MetricStrip
            items={[
              ["模型", trace.model],
              ["模式", String(trace.mode || "auto")],
              ["Token", "—"],
              ["TTFT", "—"],
              ["来源数", fmtNum(trace.evidence_count)],
              ["总耗时", fmtMs(trace.elapsed_ms)],
            ]}
          />
          <section className="panel mt-6" aria-label="阶段时间轴">
            <div className="panel-head">
              <div><h3>阶段时间轴</h3><div className="sub">{trace.trace_id} · {trace.username} · {trace.role} · {fmtTime(trace.timestamp)}</div></div>
              {bottleneck && <Status label={`瓶颈 · ${bottleneck.name} ${fmtMs(bottleneck.ms)}`} tone="warn" />}
            </div>
            <div className="trace">
              {stages.map((stage, index) => (
                <div key={stage.key}>
                  <TraceRow index={index + 1} name={stage.name} ms={stage.ms ?? 0} maxMs={maxMs} />
                  {stage.detail && <div className="meta" style={{ padding: "0 var(--s6) 6px" }}>{stage.detail}</div>}
                </div>
              ))}
            </div>
            <div className="metrics">
              <Kicker>分阶段耗时 · 条形长度 = 占总耗时比例 · 高亮 = 最慢阶段</Kicker>
            </div>
          </section>

          <section className="section">
            <div className="section-head"><h2 className="sec-title">原始事件</h2><Kicker>{fmtNum(trace.events?.length || 0)} 条事件</Kicker></div>
            <DataTable cols="170px 60px 140px 1fr 90px 100px 90px" head={["时间戳", "轮次", "类型", "工具 / 详情", "状态", "耗时", "结果数"]}>
              {(trace.events || []).map((event: AgentTraceEvent, index) => (
                <TRow key={index} cols="170px 60px 140px 1fr 90px 100px 90px">
                  <span className="cell-mono">{fmtTime(event.timestamp)}</span>
                  <span className="cell-mono">{event.round ?? "—"}</span>
                  <span className="cell-mono">{event.type}</span>
                  <span>{event.tool || (event as any).stage || (event.question_preview ? String(event.question_preview).slice(0, 60) : "—")}</span>
                  <span>{event.status ? <Status label={String(event.status).toUpperCase()} /> : "—"}</span>
                  <span className="cell-mono">{fmtMs(event.latency_ms)}</span>
                  <span className="cell-mono">{event.result_count ?? "—"}</span>
                </TRow>
              ))}
            </DataTable>
          </section>
        </>
      )}
    </>
  );
}
