"use client";

import { useEffect, useMemo, useState } from "react";
import { api, User } from "@/lib/api";

const MODES = [
  ["vector", "Vector Search"],
  ["bm25", "BM25 Search"],
  ["hybrid", "Hybrid Search"],
  ["hybrid_rerank", "Hybrid + Rerank"],
] as const;

export default function AdminEvaluationPage() {
  const [user, setUser] = useState<User | null>(null);
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void api.me().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const best = useMemo(() => {
    if (!result?.report) return null;
    return MODES.map(([key, label]) => ({ key, label, data: result.report[key] }))
      .filter((item) => item.data)
      .sort((a, b) => (b.data.mrr || 0) - (a.data.mrr || 0))[0] || null;
  }, [result]);

  const run = async () => {
    setRunning(true);
    setError("");
    try {
      setResult(await api.runEvaluation());
    } catch (e) {
      setError(e instanceof Error ? e.message : "评测失败");
    } finally {
      setRunning(false);
    }
  };

  if (loading) return <Shell><p>正在校验管理员身份…</p></Shell>;
  if (user?.role !== "ADMIN") return <Shell><h1>无权访问</h1><p>四路评测仅管理员可执行。</p><a href="/">返回 yaoke</a></Shell>;

  return (
    <Shell>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 20, alignItems: "flex-start" }}>
        <div><span style={eyebrow}>RETRIEVAL EVALUATION</span><h1 style={{ margin: "8px 0" }}>30 题 · 四路 RAG 检索评测</h1><p style={muted}>结果实时来自当前 Qdrant，不使用预置百分比。用于比较 Vector、BM25、Hybrid 与 Cross-Encoder Rerank。</p></div>
        <div style={{ display: "flex", gap: 8 }}><a href="/" style={secondary}>返回工作台</a><button onClick={() => void run()} disabled={running} style={primary}>{running ? "评测中…" : "运行四路评测"}</button></div>
      </header>

      {error && <div style={errorBox}>{error}</div>}
      {best && <div style={bestBox}>当前 MRR 最优：<strong>{best.label}</strong> · {Number(best.data.mrr || 0).toFixed(3)}</div>}

      <section style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 12, marginTop: 20 }}>
        {MODES.map(([key, label]) => <MetricCard key={key} label={label} data={result?.report?.[key]} />)}
      </section>

      <section style={panel}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>逐题检索结果</h2>
        <p style={muted}>{result ? `${result.dataset_size} questions · Top ${result.top_k}` : "运行后显示 Hybrid + Rerank 的逐题命中情况。"}</p>
        {!result && <p style={{ padding: "28px 0", color: "#98a2b3" }}>请先在管理员 Demo 工具中初始化 20 份资料。</p>}
        {(result?.report?.hybrid_rerank?.cases || []).map((item: any, index: number) => (
          <div key={index} style={{ display: "grid", gridTemplateColumns: "58px 1fr", gap: 12, padding: "12px 0", borderTop: "1px solid #eaecf0" }}>
            <span style={{ ...badge, background: item.rank ? "#ecfdf3" : "#fef3f2", color: item.rank ? "#027a48" : "#b42318" }}>{item.rank ? `#${item.rank}` : "MISS"}</span>
            <div><strong>{item.question}</strong><div style={muted}>Expected: {item.expected_file}</div><small style={{ color: "#98a2b3" }}>Top: {(item.top_files || []).join(" / ") || "无结果"}</small></div>
          </div>
        ))}
      </section>
    </Shell>
  );
}

function MetricCard({ label, data }: { label: string; data: any }) {
  return <article style={panel}><strong>{label}</strong><div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6, marginTop: 14 }}><Metric label="Hit@1" value={data ? `${Math.round(data.hit_at_1 * 100)}%` : "—"} /><Metric label="Hit@3" value={data ? `${Math.round((data.hit_at_3 || 0) * 100)}%` : "—"} /><Metric label="MRR" value={data ? Number(data.mrr).toFixed(3) : "—"} /></div><div style={{ marginTop: 10, fontSize: 10, color: "#98a2b3" }}>{data ? `${Math.round(data.elapsed_ms || 0)} ms · ${data.total} questions` : "等待评测"}</div></article>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div><span style={{ display: "block", fontSize: 10, color: "#667085" }}>{label}</span><strong style={{ display: "block", marginTop: 4, fontSize: 20 }}>{value}</strong></div>; }
function Shell({ children }: { children: React.ReactNode }) { return <main style={{ minHeight: "100vh", background: "#f5f7fb", color: "#172033", padding: "36px", fontFamily: "Inter,system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif" }}><div style={{ maxWidth: 1380, margin: "0 auto" }}>{children}</div></main>; }
const panel: React.CSSProperties = { marginTop: 20, background: "white", border: "1px solid #e4e7ec", borderRadius: 12, padding: 18, boxShadow: "0 8px 28px rgba(16,24,40,.05)" };
const primary: React.CSSProperties = { border: 0, borderRadius: 8, background: "#2357d9", color: "white", padding: "10px 14px", fontWeight: 650, cursor: "pointer" };
const secondary: React.CSSProperties = { ...primary, background: "white", color: "#344054", border: "1px solid #d0d5dd", textDecoration: "none" };
const eyebrow: React.CSSProperties = { fontSize: 10, letterSpacing: ".12em", color: "#2357d9", fontWeight: 700 };
const muted: React.CSSProperties = { color: "#667085", fontSize: 12, lineHeight: 1.6 };
const errorBox: React.CSSProperties = { marginTop: 16, padding: 12, borderRadius: 8, background: "#fef3f2", color: "#b42318" };
const bestBox: React.CSSProperties = { marginTop: 16, padding: 12, borderRadius: 8, background: "#eff8ff", color: "#175cd3" };
const badge: React.CSSProperties = { alignSelf: "start", textAlign: "center", padding: "5px 7px", borderRadius: 6, fontSize: 10, fontWeight: 700 };
