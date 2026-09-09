"use client";

import { useEffect, useMemo, useState } from "react";
import { api, AuditEvent, User } from "@/lib/api";

export default function AdminAuditPage() {
  const [user, setUser] = useState<User | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    setError("");
    try {
      const data = await api.audit(200);
      setEvents(data.events || []);
      setSummary(data.summary || {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "审计日志加载失败");
    }
  };

  useEffect(() => {
    void api.me().then(async (current) => { setUser(current); if (current.role === "ADMIN") await load(); }).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const actions = useMemo(() => ["ALL", ...Array.from(new Set(events.map((event) => event.action))).sort()], [events]);
  const visible = filter === "ALL" ? events : events.filter((event) => event.action === filter);

  if (loading) return <Shell><p>正在加载审计数据…</p></Shell>;
  if (user?.role !== "ADMIN") return <Shell><h1>无权访问</h1><p>审计日志仅管理员可查看。</p><a href="/">返回 NexusKB</a></Shell>;

  return (
    <Shell>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 20, alignItems: "flex-start" }}>
        <div><span style={eyebrow}>AUDIT TRAIL</span><h1 style={{ margin: "8px 0" }}>企业知识访问审计</h1><p style={muted}>记录登录、查询、拒绝访问、入库、删除、来源查看、检索调试、评测与 Demo 管理动作。</p></div>
        <div style={{ display: "flex", gap: 8 }}><a href="/" style={secondary}>返回工作台</a><button onClick={() => void load()} style={primary}>刷新</button></div>
      </header>

      {error && <div style={errorBox}>{error}</div>}
      <section style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 12, marginTop: 20 }}>
        <Summary label="今日查询" value={summary.today_queries ?? 0} />
        <Summary label="平均查询耗时" value={`${Math.round(summary.avg_query_latency_ms ?? 0)} ms`} />
        <Summary label="拒绝访问" value={summary.denied_access ?? 0} />
        <Summary label="今日事件" value={summary.events_today ?? 0} />
      </section>

      <section style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}><div><h2 style={{ margin: 0, fontSize: 16 }}>最近事件</h2><p style={muted}>最多读取最近 200 条 JSONL 审计记录。</p></div><select value={filter} onChange={(e) => setFilter(e.target.value)} style={select}>{actions.map((action) => <option key={action}>{action}</option>)}</select></div>
        <div style={{ display: "grid", gridTemplateColumns: "145px 100px 80px 115px 90px 1fr", gap: 10, padding: "10px 0", color: "#98a2b3", fontSize: 10, borderBottom: "1px solid #eaecf0" }}><span>时间</span><span>用户</span><span>角色</span><span>动作</span><span>状态</span><span>详情</span></div>
        {visible.map((event, index) => <div key={`${event.timestamp}-${index}`} style={{ display: "grid", gridTemplateColumns: "145px 100px 80px 115px 90px 1fr", gap: 10, padding: "11px 0", borderBottom: "1px solid #f2f4f7", alignItems: "start", fontSize: 11 }}><span>{new Date(event.timestamp).toLocaleString("zh-CN")}</span><strong>{event.username}</strong><span>{event.role}</span><span>{event.action}</span><span style={{ color: event.status === "DENIED" || event.status === "FAILED" ? "#b42318" : "#027a48" }}>{event.status}</span><div><div>{event.knowledge_base_id || "—"}{event.latency_ms != null ? ` · ${Math.round(event.latency_ms)}ms` : ""}{event.num_sources != null ? ` · ${event.num_sources} sources` : ""}</div>{event.query && <small style={{ display: "block", marginTop: 3, color: "#667085" }}>{event.query}</small>}{event.detail && <small style={{ display: "block", marginTop: 3, color: "#98a2b3" }}>{event.detail}</small>}</div></div>)}
        {visible.length === 0 && <p style={{ padding: "30px 0", color: "#98a2b3" }}>当前过滤条件下暂无审计事件。</p>}
      </section>
    </Shell>
  );
}

function Summary({ label, value }: { label: string; value: string | number }) { return <article style={{ ...panel, marginTop: 0 }}><span style={muted}>{label}</span><strong style={{ display: "block", marginTop: 7, fontSize: 26 }}>{value}</strong></article>; }
function Shell({ children }: { children: React.ReactNode }) { return <main style={{ minHeight: "100vh", background: "#f5f7fb", color: "#172033", padding: "36px", fontFamily: "Inter,system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif" }}><div style={{ maxWidth: 1480, margin: "0 auto" }}>{children}</div></main>; }
const panel: React.CSSProperties = { marginTop: 20, background: "white", border: "1px solid #e4e7ec", borderRadius: 12, padding: 18, boxShadow: "0 8px 28px rgba(16,24,40,.05)" };
const primary: React.CSSProperties = { border: 0, borderRadius: 8, background: "#2357d9", color: "white", padding: "10px 14px", fontWeight: 650, cursor: "pointer" };
const secondary: React.CSSProperties = { ...primary, background: "white", color: "#344054", border: "1px solid #d0d5dd", textDecoration: "none" };
const eyebrow: React.CSSProperties = { fontSize: 10, letterSpacing: ".12em", color: "#2357d9", fontWeight: 700 };
const muted: React.CSSProperties = { color: "#667085", fontSize: 12, lineHeight: 1.6 };
const errorBox: React.CSSProperties = { marginTop: 16, padding: 12, borderRadius: 8, background: "#fef3f2", color: "#b42318" };
const select: React.CSSProperties = { border: "1px solid #d0d5dd", borderRadius: 8, padding: "8px 10px", background: "white", color: "#344054" };
