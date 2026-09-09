"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentTrace, agentModePreference, api, User } from "@/lib/api";

const labels: Record<string, string> = {
  user: "User",
  model_decision: "Model Decision",
  tool_start: "Tool Start",
  tool_end: "Tool Result",
  limit: "Round Limit",
  final: "Final Answer",
};

export default function AgentDebuggerPage() {
  const [user, setUser] = useState<User | null>(null);
  const [traceId, setTraceId] = useState("");
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (id?: string) => {
    const target = (id || traceId || agentModePreference.lastTraceId()).trim();
    if (!target) {
      setError("还没有 Agent Trace。先在 AI 知识助手中提问一次。 ");
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

  return (
    <main style={shell}>
      <section style={{ ...card, maxWidth: 1060 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 12, color: "#1570ef", fontWeight: 800 }}>NexusKB / P1.4</div>
            <h1 style={{ margin: "8px 0" }}>Agent Debugger</h1>
            <p style={{ margin: 0, color: "#667085" }}>只展示可公开的执行事件，不展示 Ornith hidden reasoning / chain-of-thought。</p>
          </div>
          <a href="/" style={linkButton}>返回工作台</a>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
          <input
            value={traceId}
            onChange={(event) => setTraceId(event.target.value)}
            placeholder="trace_id"
            style={{ flex: 1, padding: "10px 12px", border: "1px solid #d0d5dd", borderRadius: 8 }}
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
            </div>

            <div style={{ marginTop: 24 }}>
              {trace.events.map((event, index) => (
                <article key={`${event.type}-${index}`} style={eventCard}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>{index + 1}. {labels[event.type] || event.type}</strong>
                    <span style={{ color: "#98a2b3", fontSize: 12 }}>{event.round ? `Round ${event.round}` : ""}</span>
                  </div>
                  {event.mode && <p>mode: <code>{event.mode}</code></p>}
                  {event.question_preview && <p>question: {event.question_preview}</p>}
                  {event.tools?.length ? <p>tools: <code>{event.tools.join(", ")}</code></p> : null}
                  {event.tool && <p>tool: <code>{event.tool}</code></p>}
                  {event.arguments && <pre style={pre}>{JSON.stringify(event.arguments, null, 2)}</pre>}
                  {event.status && <p>status: <strong>{event.status}</strong></p>}
                  {event.result_count != null && <p>result_count: {event.result_count}</p>}
                  {event.latency_ms != null && <p>latency: {event.latency_ms} ms</p>}
                  {event.answer_preview && <p>answer preview: {event.answer_preview}</p>}
                  {event.max_tool_rounds && <p>tool-call budget reached: {event.max_tool_rounds}</p>}
                </article>
              ))}
            </div>
          </>
        )}
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div style={{ padding: 14, border: "1px solid #eaecf0", borderRadius: 10 }}><span style={{ display: "block", fontSize: 11, color: "#667085" }}>{label}</span><strong style={{ display: "block", marginTop: 5 }}>{value}</strong></div>;
}

const shell: React.CSSProperties = { minHeight: "100vh", background: "#f8fafc", padding: "40px 20px", color: "#101828" };
const card: React.CSSProperties = { margin: "0 auto", maxWidth: 760, background: "#fff", border: "1px solid #eaecf0", borderRadius: 16, padding: 24, boxShadow: "0 10px 30px rgba(16,24,40,.06)" };
const metrics: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10, marginTop: 24 };
const eventCard: React.CSSProperties = { marginBottom: 10, border: "1px solid #eaecf0", borderRadius: 10, padding: 14, background: "#fcfcfd", fontSize: 13 };
const pre: React.CSSProperties = { whiteSpace: "pre-wrap", padding: 10, background: "#f2f4f7", borderRadius: 8, overflowX: "auto" };
const primaryButton: React.CSSProperties = { border: 0, borderRadius: 8, padding: "10px 14px", background: "#1570ef", color: "white", fontWeight: 700, cursor: "pointer" };
const linkButton: React.CSSProperties = { textDecoration: "none", border: "1px solid #d0d5dd", borderRadius: 8, padding: "8px 10px", color: "#344054", fontSize: 12 };
