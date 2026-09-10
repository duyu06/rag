"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentTrace, agentModePreference, api, User } from "@/lib/api";

const labels: Record<string, string> = {
  user: "User",
  fast_path: "Local Fast Path",
  model_decision: "Model Decision",
  tool_start: "Tool Start",
  tool_end: "Tool Result",
  limit: "Round Limit",
  final: "Final Answer",
};

type TimingMap = Record<string, unknown>;

function ms(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value)} ms` : "—";
}

function boolLabel(value: unknown) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "—";
}

export default function AgentDebuggerPage() {
  const [user, setUser] = useState<User | null>(null);
  const [traceId, setTraceId] = useState("");
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (id?: string) => {
    const target = (id || traceId || agentModePreference.lastTraceId()).trim();
    if (!target) {
      setError("还没有 Agent Trace。先在 AI 知识助手中提问一次。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.agentTrace(target);
      setTrace(data);
      setTraceId(data.trace_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Trace 加载失败");
    } finally {
      setLoading(false);
    }
  }, [traceId]);

  useEffect(() => {
    api.me().then(setUser).catch(() => setError("请先登录"));
    const id = agentModePreference.lastTraceId();
    if (id) {
      setTraceId(id);
      void load(id);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (user && user.role !== "ADMIN") {
    return <main style={shell}><section style={card}><h1>Agent Debugger</h1><p>管理员演示页面。普通用户仍可通过后端权限读取自己的 Trace，但此 UI 不开放。</p><a href="/">返回工作台</a></section></main>;
  }

  const timings = (((trace as unknown as { timings?: TimingMap } | null)?.timings) || {}) as TimingMap;

  return (
    <main style={shell}>
      <section style={{ ...card, maxWidth: 1120 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 12, color: "#1570ef", fontWeight: 800 }}>yaoke / P1.5</div>
            <h1 style={{ margin: "8px 0" }}>Agent Debugger</h1>
            <p style={{ margin: 0, color: "#667085" }}>展示 Tool、Citation 与性能阶段，不展示 Ornith hidden reasoning / chain-of-thought。</p>
          </div>
          <a href="/" style={linkButton}>返回工作台</a>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 24, flexWrap: "wrap" }}>
          <input
            value={traceId}
            onChange={(event) => setTraceId(event.target.value)}
            placeholder="trace_id"
            style={{ flex: "1 1 360px", minWidth: 0, padding: "10px 12px", border: "1px solid #d0d5dd", borderRadius: 8 }}
          />
          <button onClick={() => void load()} disabled={loading} style={primaryButton}>{loading ? "加载中" : "加载 Trace"}</button>
        </div>
        {error && <p style={{ color: "#b42318" }}>{error}</p>}

        {trace && (
          <>
            <div style={metrics}>
              <Metric label="Mode" value={trace.mode.toUpperCase()} />
              <Metric label="Model" value={trace.model} />
              <Metric label="Evidence" value={String(trace.evidence_count)} />
              <Metric label="Elapsed" value={`${Math.round(trace.elapsed_ms)} ms`} />
              <Metric label="Max rounds" value={String(trace.max_tool_rounds)} />
              <Metric label="Fast path" value={boolLabel(timings.fast_path)} />
            </div>

            {Object.keys(timings).length > 0 && (
              <section style={{ marginTop: 20, padding: 16, border: "1px solid #dbe7ff", borderRadius: 12, background: "#f8fbff" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div><strong>性能分解</strong><p style={{ margin: "4px 0 0", color: "#667085", fontSize: 12 }}>Local Fast Path 可直接定位 Retrieval 与 LLM 瓶颈。</p></div>
                  <span style={{ color: "#475467", fontSize: 12 }}>BM25 cache: {boolLabel(timings.bm25_cache_hit)} · Parallel hybrid: {boolLabel(timings.parallel_hybrid)}</span>
                </div>
                <div style={{ ...metrics, marginTop: 14 }}>
                  <Metric label="Vector" value={ms(timings.vector_ms)} />
                  <Metric label="BM25" value={ms(timings.bm25_ms)} />
                  <Metric label="Fusion" value={ms(timings.fusion_ms)} />
                  <Metric label="Rerank" value={ms(timings.rerank_ms)} />
                  <Metric label="Retrieval" value={ms(timings.retrieval_total_ms ?? timings.retrieval_ms)} />
                  <Metric label="LLM" value={ms(timings.llm_ms)} />
                  <Metric label="Total" value={ms(timings.total_ms)} />
                </div>
              </section>
            )}

            <div style={{ marginTop: 24 }}>
              {trace.events.map((event, index) => {
                const eventTimings = ((event as unknown as { timings?: TimingMap }).timings || {}) as TimingMap;
                return (
                  <article key={`${event.type}-${index}`} style={eventCard}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                      <strong>{index + 1}. {labels[event.type] || event.type}</strong>
                      <span style={{ color: "#98a2b3", fontSize: 12 }}>{event.round != null ? `Round ${event.round}` : ""}</span>
                    </div>
                    {event.mode && <p>mode: <code>{event.mode}</code></p>}
                    {event.question_preview && <p>question: {event.question_preview}</p>}
                    {event.tools?.length ? <p>tools: <code>{event.tools.join(", ")}</code></p> : null}
                    {event.tool && <p>tool: <code>{event.tool}</code></p>}
                    {event.arguments && <pre style={pre}>{JSON.stringify(event.arguments, null, 2)}</pre>}
                    {event.status && <p>status: <strong>{event.status}</strong></p>}
                    {event.result_count != null && <p>result_count: {event.result_count}</p>}
                    {event.latency_ms != null && <p>latency: {event.latency_ms} ms</p>}
                    {Object.keys(eventTimings).length > 0 && (
                      <div style={eventTimingGrid}>
                        <span>Vector <b>{ms(eventTimings.vector_ms)}</b></span>
                        <span>BM25 <b>{ms(eventTimings.bm25_ms)}</b></span>
                        <span>Fusion <b>{ms(eventTimings.fusion_ms)}</b></span>
                        <span>Rerank <b>{ms(eventTimings.rerank_ms)}</b></span>
                        <span>Total <b>{ms(eventTimings.total_ms)}</b></span>
                      </div>
                    )}
                    {event.answer_preview && <p>answer preview: {event.answer_preview}</p>}
                    {event.max_tool_rounds && <p>tool-call budget reached: {event.max_tool_rounds}</p>}
                  </article>
                );
              })}
            </div>
          </>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div style={{ padding: 14, border: "1px solid #eaecf0", borderRadius: 10, background: "#fff" }}><span style={{ display: "block", fontSize: 11, color: "#667085" }}>{label}</span><strong style={{ display: "block", marginTop: 5 }}>{value}</strong></div>;
}

const shell: React.CSSProperties = { minHeight: "100vh", background: "#f8fafc", padding: "40px 20px", color: "#101828" };
const card: React.CSSProperties = { margin: "0 auto", maxWidth: 760, background: "#fff", border: "1px solid #eaecf0", borderRadius: 16, padding: 24, boxShadow: "0 10px 30px rgba(16,24,40,.06)" };
const metrics: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: 10, marginTop: 24 };
const eventCard: React.CSSProperties = { marginBottom: 10, border: "1px solid #eaecf0", borderRadius: 10, padding: 14, background: "#fcfcfd", fontSize: 13 };
const eventTimingGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: 8, marginTop: 10, padding: 10, background: "#f8fafc", borderRadius: 8, color: "#475467", fontSize: 12 };
const pre: React.CSSProperties = { whiteSpace: "pre-wrap", padding: 10, background: "#f2f4f7", borderRadius: 8, overflowX: "auto" };
const primaryButton: React.CSSProperties = { border: 0, borderRadius: 8, padding: "10px 14px", background: "#1570ef", color: "white", fontWeight: 700, cursor: "pointer" };
const linkButton: React.CSSProperties = { textDecoration: "none", border: "1px solid #d0d5dd", borderRadius: 8, padding: "8px 10px", color: "#344054", fontSize: 12 };
