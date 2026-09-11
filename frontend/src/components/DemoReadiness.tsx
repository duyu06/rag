"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

type CheckState = {
  key: string;
  label: string;
  ok: boolean | null;
  detail: string;
};

function names(payload: any) {
  return new Set<string>((payload?.tools || []).map((item: any) => String(item?.name || "")));
}

function toolPolicyOk(actual: Set<string>, expected: string[]) {
  return actual.size === expected.length && expected.every((name) => actual.has(name));
}

export default function DemoReadiness({ onNavigate }: { onNavigate: (view: "chat" | "evaluation" | "system") => void }) {
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<any>(null);
  const [demo, setDemo] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [localTools, setLocalTools] = useState<any>(null);
  const [autoTools, setAutoTools] = useState<any>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    const [healthResult, demoResult, statsResult, localResult, autoResult] = await Promise.allSettled([
      api.health(),
      api.demoStatus(),
      api.stats("all"),
      api.agentTools("local"),
      api.agentTools("auto"),
    ]);

    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (demoResult.status === "fulfilled") setDemo(demoResult.value);
    if (statsResult.status === "fulfilled") setStats(statsResult.value);
    if (localResult.status === "fulfilled") setLocalTools(localResult.value);
    if (autoResult.status === "fulfilled") setAutoTools(autoResult.value);

    const failed = [healthResult, demoResult, statsResult, localResult, autoResult].filter(
      (result) => result.status === "rejected",
    ).length;
    if (failed) setError(`${failed} 项运行态检查未返回，建议刷新或检查依赖服务。`);

    setLastChecked(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const checks = useMemo<CheckState[]>(() => {
    const local = names(localTools);
    const auto = names(autoTools);
    const corpusTotal = Number(demo?.total || 0);
    const corpusReady = Number(demo?.ready_count || 0);

    return [
      {
        key: "runtime",
        label: "API Runtime",
        ok: health ? health.status === "healthy" : null,
        detail: health ? `${health.phase || "unknown"} / v${health.version || "?"}` : "等待健康检查",
      },
      {
        key: "qdrant",
        label: "Qdrant",
        ok: health ? Boolean(health.vector_db_connected) : null,
        detail: health?.vector_db_connected ? "Vector DB connected" : "未连接",
      },
      {
        key: "ornith",
        label: "Ornith",
        ok: health ? Boolean(health.agent_llm_connected) : null,
        detail: health?.agent_llm_model || health?.llm_model || "等待模型探测",
      },
      {
        key: "corpus",
        label: "Demo Corpus",
        ok: demo ? Boolean(demo.ready) && corpusTotal > 0 && corpusReady === corpusTotal : null,
        detail: demo ? `${corpusReady}/${corpusTotal} ready` : "等待 Demo 状态",
      },
      {
        key: "local-policy",
        label: "Local Tool Policy",
        ok: localTools ? toolPolicyOk(local, ["enterprise_search"]) : null,
        detail: localTools ? Array.from(local).join(" + ") || "无工具" : "等待 Tool Registry",
      },
      {
        key: "auto-policy",
        label: "Auto Tool Policy",
        ok: autoTools ? toolPolicyOk(auto, ["enterprise_search", "web_search"]) : null,
        detail: autoTools ? Array.from(auto).join(" + ") || "无工具" : "等待 Tool Registry",
      },
      {
        key: "streaming",
        label: "Native Streaming",
        ok: health ? health.native_streaming === true && health.phase === "P1.8" : null,
        detail: health?.native_streaming ? "Conversation SSE · local native stream" : "等待 P1.8 runtime",
      },
    ];
  }, [health, demo, localTools, autoTools]);

  const passed = checks.filter((item) => item.ok === true).length;
  const ready = checks.length > 0 && passed === checks.length;
  const metrics = [
    ["文档", stats?.total_documents ?? "—"],
    ["Chunks", stats?.total_chunks ?? "—"],
    ["今日问答", stats?.today_queries ?? 0],
    ["平均耗时", `${Math.round(stats?.avg_query_latency_ms ?? 0)} ms`],
    ["拒绝访问", stats?.denied_access ?? 0],
  ];

  return (
    <section className="panel" style={{ marginBottom: 18 }}>
      <div className="panel-head" style={{ alignItems: "flex-start" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
            <h3 style={{ margin: 0 }}>Interview Readiness</h3>
            <span
              style={{
                borderRadius: 999,
                padding: "4px 9px",
                fontSize: 11,
                fontWeight: 750,
                background: ready ? "rgba(18,183,106,.12)" : "rgba(247,144,9,.12)",
                color: ready ? "#067647" : "#b54708",
              }}
            >
              {loading ? "CHECKING" : ready ? "READY" : "DEGRADED"}
            </span>
          </div>
          <p style={{ marginTop: 6 }}>
            P1.8 演示前一屏检查：运行依赖、20/20 数据、Tool Policy、原生 Streaming 与最近运行指标。
          </p>
        </div>
        <button className="link-btn" disabled={loading} onClick={() => void refresh()}>
          {loading ? "检查中…" : "重新检查"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(155px,1fr))", gap: 9 }}>
        {checks.map((item) => (
          <div
            key={item.key}
            style={{
              border: "1px solid #eaecf0",
              borderRadius: 10,
              padding: "11px 12px",
              background: item.ok === false ? "#fff8f6" : "#fcfcfd",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
              <strong style={{ fontSize: 12 }}>{item.label}</strong>
              <span style={{ fontSize: 11, fontWeight: 800, color: item.ok === true ? "#067647" : item.ok === false ? "#b42318" : "#667085" }}>
                {item.ok === true ? "PASS" : item.ok === false ? "FAIL" : "…"}
              </span>
            </div>
            <div style={{ marginTop: 6, fontSize: 10, lineHeight: 1.45, color: "#667085", wordBreak: "break-word" }}>
              {item.detail}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,minmax(0,1fr))", gap: 8, marginTop: 10 }}>
        {metrics.map(([label, value]) => (
          <div key={String(label)} style={{ borderRadius: 9, padding: "9px 8px", background: "#f9fafb", textAlign: "center" }}>
            <strong style={{ display: "block", fontSize: 13 }}>{String(value)}</strong>
            <span style={{ display: "block", marginTop: 3, fontSize: 9, color: "#667085" }}>{label}</span>
          </div>
        ))}
      </div>

      {error && <div className="notice danger" style={{ marginTop: 10, marginBottom: 0 }}>{error}</div>}

      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        <small style={{ color: "#667085" }}>
          {lastChecked ? `最近检查：${lastChecked.toLocaleTimeString("zh-CN", { hour12: false })} · ${passed}/${checks.length} PASS` : "尚未完成检查"}
        </small>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="link-btn" onClick={() => onNavigate("system")}>系统状态</button>
          <button className="link-btn" onClick={() => onNavigate("evaluation")}>RAG 评测</button>
          <button className="primary" onClick={() => onNavigate("chat")}>开始演示</button>
        </div>
      </div>
    </section>
  );
}
