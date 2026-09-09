"use client";

import { useCallback, useEffect, useState } from "react";
import { api, AuditEvent, session, User } from "@/lib/api";

const labels: Record<string, string> = {
  vector: "Vector",
  bm25: "BM25",
  hybrid: "Hybrid",
  hybrid_rerank: "Hybrid + Rerank",
};

function percent(value?: number) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function actionLabel(action: string) {
  const map: Record<string, string> = {
    LOGIN: "登录",
    QUERY: "问答",
    ACCESS: "访问控制",
    INGEST: "文档入库",
    DELETE: "删除文档",
    SOURCE_VIEW: "查看来源",
    RETRIEVAL_DEBUG: "检索调试",
    EVALUATION: "RAG 评测",
    DEMO_INIT: "初始化 Demo",
    DEMO_RESET: "重置 Demo",
  };
  return map[action] || action;
}

export default function DemoTools() {
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [audit, setAudit] = useState<AuditEvent[]>([]);

  const syncUser = useCallback(async () => {
    if (!session.hasToken()) {
      setUser(null);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  const refreshPanel = useCallback(async () => {
    if (user?.role !== "ADMIN") return;
    const [demoResult, statsResult, auditResult] = await Promise.allSettled([
      api.demoStatus(),
      api.stats("all"),
      api.audit(8),
    ]);
    if (demoResult.status === "fulfilled") setStatus(demoResult.value);
    if (statsResult.status === "fulfilled") setStats(statsResult.value);
    if (auditResult.status === "fulfilled") setAudit(auditResult.value.events || []);
  }, [user]);

  useEffect(() => {
    void syncUser();
    window.addEventListener("yaoke-auth", syncUser);
    window.addEventListener("focus", syncUser);
    return () => {
      window.removeEventListener("yaoke-auth", syncUser);
      window.removeEventListener("focus", syncUser);
    };
  }, [syncUser]);

  useEffect(() => {
    if (open) void refreshPanel();
  }, [open, refreshPanel]);

  if (user?.role !== "ADMIN") return null;

  const runInit = async () => {
    setBusy("init");
    setMessage("正在初始化 20 份企业演示资料，首次运行可能需要下载 Embedding 模型…");
    try {
      const result = await api.initializeDemo();
      setStatus(result.status);
      setMessage(result.message);
      await refreshPanel();
      setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "初始化失败");
    } finally {
      setBusy("");
    }
  };

  const runReset = async () => {
    if (!confirm("重置会重新索引内置 20 份 Demo 文档，但不会删除你额外上传的资料。继续吗？")) return;
    setBusy("reset");
    setMessage("正在重建 Demo 索引…");
    try {
      const result = await api.resetDemo();
      setStatus(result.status);
      setMessage(result.message);
      await refreshPanel();
      setTimeout(() => window.location.reload(), 700);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重置失败");
    } finally {
      setBusy("");
    }
  };

  const runEvaluation = async () => {
    setBusy("eval");
    setMessage("正在运行 30 道题的四路检索评测…");
    try {
      const result = await api.runEvaluation();
      setEvaluation(result);
      setMessage(`评测完成：${result.dataset_size} 道题`);
      await refreshPanel();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "评测失败");
    } finally {
      setBusy("");
    }
  };

  const shell: React.CSSProperties = {
    position: "fixed", right: 18, bottom: 18, zIndex: 1000, fontFamily: "inherit",
  };
  const panel: React.CSSProperties = {
    width: 390, maxHeight: "80vh", overflow: "auto", marginBottom: 10, padding: 14,
    background: "#101828", color: "white", border: "1px solid #344054", borderRadius: 12,
    boxShadow: "0 18px 50px rgba(16,24,40,.28)",
  };
  const button: React.CSSProperties = {
    border: 0, borderRadius: 8, padding: "9px 11px", fontSize: 12, fontWeight: 650, cursor: "pointer",
  };

  const metrics = [
    ["文档", String(stats?.total_documents ?? "—")],
    ["Chunks", String(stats?.total_chunks ?? "—")],
    ["今日问答", String(stats?.today_queries ?? 0)],
    ["平均耗时", `${stats?.avg_query_latency_ms ?? 0}ms`],
    ["拒绝访问", String(stats?.denied_access ?? 0)],
  ];

  return (
    <div style={shell}>
      {open && (
        <div style={panel}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div><strong style={{ fontSize: 14 }}>Demo 工具 / 运行态</strong><div style={{ marginTop: 3, fontSize: 10, color: "#98a2b3" }}>P1.4 / v0.4.0 · Agent + 真实指标 + 审计</div></div>
            <span style={{ fontSize: 10, color: status?.ready ? "#6ce9a6" : "#fdb022" }}>
              {status ? `${status.ready_count}/${status.total} ready` : "checking"}
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 5, marginTop: 12 }}>
            {metrics.map(([name, value]) => (
              <div key={name} style={{ padding: "8px 5px", textAlign: "center", borderRadius: 7, background: "#182230" }}>
                <strong style={{ display: "block", fontSize: 12 }}>{value}</strong>
                <span style={{ display: "block", marginTop: 3, fontSize: 8, color: "#98a2b3" }}>{name}</span>
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
            <button disabled={Boolean(busy)} onClick={() => void runInit()} style={{ ...button, background: "#2357d9", color: "white" }}>
              {busy === "init" ? "初始化中…" : "初始化 Demo"}
            </button>
            <button disabled={Boolean(busy)} onClick={() => void runReset()} style={{ ...button, background: "#344054", color: "white" }}>
              {busy === "reset" ? "重置中…" : "重置 Demo"}
            </button>
          </div>

          <button disabled={Boolean(busy)} onClick={() => void runEvaluation()} style={{ ...button, width: "100%", marginTop: 8, background: "#12b76a", color: "#061c14" }}>
            {busy === "eval" ? "评测中…" : "运行四路 RAG 评测"}
          </button>

          {message && <div style={{ marginTop: 10, padding: 9, borderRadius: 7, background: "#182230", fontSize: 10, lineHeight: 1.5, color: "#d0d5dd" }}>{message}</div>}

          {evaluation?.report && (
            <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
              {Object.entries(evaluation.report).map(([key, raw]) => {
                const data = raw as any;
                return (
                  <div key={key} style={{ display: "grid", gridTemplateColumns: "1.5fr .7fr .7fr .7fr", gap: 6, alignItems: "center", padding: "8px 9px", background: "#182230", borderRadius: 7, fontSize: 10 }}>
                    <strong>{labels[key] || key}</strong>
                    <span>H@1 {percent(data.hit_at_1)}</span>
                    <span>H@3 {percent(data.hit_at_3)}</span>
                    <span>MRR {Number(data.mrr || 0).toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          )}

          <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #344054" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ fontSize: 11 }}>最近审计</strong>
              <button onClick={() => void refreshPanel()} style={{ border: 0, background: "transparent", color: "#84adff", fontSize: 9, cursor: "pointer" }}>刷新</button>
            </div>
            <div style={{ display: "grid", gap: 5, marginTop: 7 }}>
              {audit.slice(0, 6).map((event, index) => (
                <div key={`${event.timestamp}-${index}`} style={{ padding: "7px 8px", borderRadius: 6, background: "#182230", fontSize: 9, lineHeight: 1.45 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <strong>{actionLabel(event.action)} · {event.username}</strong>
                    <span style={{ color: event.status === "DENIED" ? "#f97066" : "#6ce9a6" }}>{event.status}</span>
                  </div>
                  <div style={{ marginTop: 2, color: "#98a2b3" }}>
                    {event.query ? event.query.slice(0, 42) : event.detail || event.knowledge_base_id || "—"}
                    {event.latency_ms != null ? ` · ${Math.round(event.latency_ms)}ms` : ""}
                  </div>
                </div>
              ))}
              {audit.length === 0 && <span style={{ color: "#98a2b3", fontSize: 9 }}>暂无审计事件</span>}
            </div>
          </div>
        </div>
      )}

      <button onClick={() => setOpen((value) => !value)} style={{ ...button, background: "#101828", color: "white", boxShadow: "0 10px 30px rgba(16,24,40,.22)" }}>
        {open ? "收起 Demo 工具" : "Demo 工具"}
      </button>
    </div>
  );
}
