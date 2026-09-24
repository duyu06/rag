"use client";

import { useCallback, useEffect, useState } from "react";
import { api, SystemStatus, TypesafeStats } from "@/lib/api";
import {
  DataTable,
  ErrorState,
  Kicker,
  PageHeader,
  SkeletonRows,
  Stat,
  Status,
  TRow,
  Tone,
  fmtMs,
  fmtNum,
  relTime,
  statusTone,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

type ServiceRow = {
  name: string;
  status: string;
  model: string;
  p50?: number | null;
  p95?: number | null;
  ttft?: number | null;
  note: string;
};

// UNKNOWN 不在 <Status> 内置词表里，显示层补译；其余状态交给 Status 内部映射。
function healthStatusLabel(status?: string | null) {
  const key = (status || "UNKNOWN").toUpperCase();
  return key === "UNKNOWN" ? "未知" : key;
}

// 判定层五档模式（设计 §3）：数据层仍是英文枚举，只有显示文案走中文。
const TYPESAFE_MODE_LABELS: Record<string, string> = {
  off: "未启用",
  shadow: "只观测",
  selective: "按需判定",
  active: "高置信免判",
  strict: "恒判",
};

// 熔断三态（app/resilience.CircuitBreaker.state 的取值）。
const BREAKER_LABELS: Record<string, string> = {
  closed: "闭合",
  open: "打开",
  half_open: "半开",
};
const BREAKER_TONES: Record<string, Tone> = {
  closed: "ok",
  open: "err",
  half_open: "warn",
};

function typesafeModeLabel(mode?: string | null) {
  return TYPESAFE_MODE_LABELS[(mode || "off").toLowerCase()] ?? "未启用";
}

function breakerLabelOf(state?: string | null) {
  return BREAKER_LABELS[(state || "").toLowerCase()] ?? "未知";
}

function breakerToneOf(state?: string | null): Tone {
  return BREAKER_TONES[(state || "").toLowerCase()] ?? "idle";
}

// 比率一律"一位小数百分比"（术语基准：不新增缩写英文，P50 / P95 属保留项）。
// 第二参数 = 分母侧还有没有样本：`sample_count == 0` 时后端把比率折成 0.0，那是"没数据"
// 而不是"零触发 / 零降级"，显示层一律走 "—"——空看板不该被读成全绿。
function fmtRate(value?: number | null, hasSamples = true) {
  return value == null || !hasSamples ? "—" : `${(value * 100).toFixed(1)}%`;
}

// 成本沿用后端聚合的美元口径（`cost_per_query_p50`），不换算、不自造单价。
// 小数位自适应：个位数美分以内（<0.001）保留 6 位才看得见量级，否则 4 位足够。
function fmtUsd(value?: number | null) {
  return value == null ? "—" : `$${value.toFixed(Math.abs(value) < 0.001 ? 6 : 4)}`;
}

export default function SystemView({ setNotice }: ViewProps) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [statusData, healthData] = await Promise.all([
        api.systemStatus(),
        api.health().catch(() => null),
      ]);
      setStatus(statusData);
      setHealth(healthData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "系统状态加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const services: ServiceRow[] = status ? [
    { name: "大模型", status: status.llm.status, model: `${status.llm.model} · ${status.llm.provider}`, p50: status.llm.p50_ms, p95: status.llm.p95_ms, ttft: status.llm.ttft_ms, note: "生成 + 重排序兜底" },
    { name: "向量化", status: status.embedding.status, model: `${status.embedding.model}${status.embedding.dimension ? ` · ${status.embedding.dimension}d` : ""}`, note: "入库与查询时向量化" },
    { name: "关键词检索 BM25", status: status.bm25.status, model: "内存关键词索引", note: "词法召回通道" },
    { name: "重排序", status: status.reranker.status, model: status.reranker.model || "cross-encoder", note: "hybrid_rerank 流水线阶段" },
    { name: "向量库", status: status.vector_db.status, model: `qdrant${status.vector_db.collection ? ` · ${status.vector_db.collection}` : ""}`, note: "按权限过滤的稠密检索" },
    { name: "索引", status: status.index.failed_jobs > 0 ? "DEGRADED" : "ONLINE", model: "知识索引", note: "文档 / 分块 / 失败任务" },
  ] : [];

  const demoActionLabel = (action: "initialize" | "reset") => (action === "initialize" ? "初始化" : "重置");

  const typesafe: TypesafeStats | undefined = status?.typesafe ?? undefined;
  // `mode=="off"`（含 `typesafe_enabled=false`）或后端未返回该块：整块显示"未启用"。
  const typesafeOff = !typesafe || typesafe.mode === "off";
  // 比率的分母是"真正进入判定层的样本数"（`sample_count`）：为 0 时所有比率卡显示 "—"。
  const typesafeHasSamples = (typesafe?.sample_count ?? 0) > 0;

  const demo = async (action: "initialize" | "reset") => {
    setBusy(action);
    try {
      if (action === "initialize") await api.initializeDemo();
      else await api.resetDemo();
      setNotice(`演示数据${demoActionLabel(action)}完成`);
      await load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "演示数据操作失败", "err");
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <PageHeader
        kicker="10 系统 — 可观测性，而不是“运行正常”"
        title="系统"
        desc="逐服务状态与延迟分位数、索引新鲜度、模型路由。颜色仅承载语义。"
        actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => void load()}>刷新</button>}
      />

      {loading && <SkeletonRows rows={6} />}
      {error && <ErrorState title="状态不可用" what={error} cause="/system/status 接口不可达。" next="确认 API 服务已在 :8001 端口启动，然后重试。" actions={<button type="button" className="btn btn--primary btn--sm" onClick={() => void load()}>重试</button>} />}

      {!loading && status && (
        <>
          <div className="stat-row">
            <Stat big value={<Status label={healthStatusLabel(status.overall)} />} label="总体状态" />
            <Stat value={fmtNum(status.index.documents)} label="文档" />
            <Stat value={fmtNum(status.index.chunks)} label="分块" />
            <Stat value={<span style={{ color: status.index.failed_jobs ? "var(--err)" : undefined }}>{fmtNum(status.index.failed_jobs)}</span>} label="失败任务" />
            <Stat value={relTime(status.index.last_sync_at)} label="最近同步" />
          </div>

          <section className="section" aria-label="核心服务">
            <div className="section-head"><h2 className="sec-title">核心服务</h2><Kicker>在线 / 降级 / 离线 / 失败</Kicker></div>
            <DataTable cols="140px 130px minmax(220px,1.6fr) 90px 90px 90px minmax(180px,1fr)" head={["服务", "状态", "模型 / 引擎", "P50", "P95", "TTFT", "说明"]}>
              {services.map((row) => (
                <TRow key={row.name} cols="140px 130px minmax(220px,1.6fr) 90px 90px 90px minmax(180px,1fr)">
                  <span className="primary-col"><b>{row.name}</b></span>
                  <span><Status label={healthStatusLabel(row.status)} /></span>
                  <span className="cell-mono">{row.model}</span>
                  <span className="cell-mono">{row.p50 != null ? fmtMs(row.p50) : "—"}</span>
                  <span className="cell-mono">{row.p95 != null ? fmtMs(row.p95) : "—"}</span>
                  <span className="cell-mono">{row.ttft != null ? fmtMs(row.ttft) : "—"}</span>
                  <span className="muted" style={{ fontSize: 12 }}>{row.note}</span>
                </TRow>
              ))}
            </DataTable>
          </section>

          <section className="section" aria-label="判定层">
            <div className="section-head"><h2 className="sec-title">判定层</h2><Kicker>判定层观测</Kicker></div>
            {typesafeOff ? (
              <p className="muted" style={{ fontSize: 12 }}>未启用 —— 判定层已关闭或未上报观测，检索只做本地精排。</p>
            ) : (
              <>
                <div className="stat-row">
                  <Stat value={fmtRate(typesafe?.trigger_rate, typesafeHasSamples)} label="触发率" />
                  <Stat value={fmtRate(typesafe?.skip_rate, typesafeHasSamples)} label="跳过率" />
                  <Stat value={fmtRate(typesafe?.cache_hit_ratio, typesafeHasSamples)} label="缓存命中" />
                  <Stat value={fmtRate(typesafe?.timeout_rate, typesafeHasSamples)} label="超时率" />
                  <Stat value={fmtRate(typesafe?.degraded_rate, typesafeHasSamples)} label="降级率" />
                  <Stat value={fmtNum(typesafe?.requests_per_query_p95)} label="每查询外呼数 P95" />
                  <Stat value={<Status label={breakerLabelOf(typesafe?.breaker_state)} tone={breakerToneOf(typesafe?.breaker_state)} />} label="熔断状态" />
                </div>
                <p className="muted mt-4" style={{ fontSize: 12 }}>
                  模式 {typesafeModeLabel(typesafe?.mode)} · 判定延迟 P50 {fmtMs(typesafe?.latency_p50_ms)} / P95 {fmtMs(typesafe?.latency_p95_ms)} · 慢批占比 {fmtRate(typesafe?.slow_rate, typesafeHasSamples)} · 每查询输入 Token P50 {fmtNum(typesafe?.input_tokens_per_query_p50)} · 每请求成本 P50 {fmtUsd(typesafe?.cost_per_query_p50)}
                </p>
                <p className="muted" style={{ fontSize: 12 }}>
                  比率分母为最近 {fmtNum(typesafe?.sample_count ?? 0)} 条真正进入判定层的请求；按置信度路由免判的请求不经过判定层，故不计入。分母为 0 时比率显示 —，不显示 0.0%。
                </p>
              </>
            )}
          </section>

          <section className="section" aria-label="模型路由">
            <div className="section-head"><h2 className="sec-title">模型路由</h2><Kicker>取自运行时配置</Kicker></div>
            <DataTable cols="180px 220px 160px 1fr" head={["任务", "模型", "提供方", "模式策略"]}>
              <TRow cols="180px 220px 160px 1fr"><span>回答生成</span><span className="cell-mono">{status.llm.model}</span><span className="cell-mono">{status.llm.provider}</span><span className="muted" style={{ fontSize: 12 }}>本地 = 仅检索 · 自动 = 工具调用智能体 · 联网 = 允许公开搜索工具</span></TRow>
              <TRow cols="180px 220px 160px 1fr"><span>向量化</span><span className="cell-mono">{status.embedding.model}</span><span className="cell-mono">{health?.embedding_provider || "ollama"}</span><span className="muted" style={{ fontSize: 12 }}>确定性；入库与查询共用</span></TRow>
              <TRow cols="180px 220px 160px 1fr"><span>重排序</span><span className="cell-mono">{status.reranker.model || "cross-encoder"}</span><span className="cell-mono">本地</span><span className="muted" style={{ fontSize: 12 }}>按请求开启（rerank 开关）</span></TRow>
              <TRow cols="180px 220px 160px 1fr"><span>向量存储</span><span className="cell-mono">qdrant</span><span className="cell-mono">本地 Docker</span><span className="muted" style={{ fontSize: 12 }}>payload 元数据过滤 = 权限边界</span></TRow>
            </DataTable>
          </section>

          <section className="section" aria-label="维护">
            <div className="section-head"><h2 className="sec-title">维护</h2><Kicker>演示数据生命周期</Kicker></div>
            <div className="actions-row">
              <button type="button" className="btn btn--ghost" disabled={Boolean(busy)} onClick={() => void demo("initialize")}>{busy === "initialize" ? "进行中…" : "初始化演示数据"}</button>
              <button type="button" className="btn btn--danger" disabled={Boolean(busy)} onClick={() => { if (confirm("确定重置全部演示知识吗？")) void demo("reset"); }}>{busy === "reset" ? "进行中…" : "重置演示数据"}</button>
            </div>
            <p className="muted mt-4" style={{ fontSize: 12 }}>重置会删除演示知识库、文档、索引与评测历史，然后重新写入五份演示数据源。</p>
          </section>
        </>
      )}

      {!loading && !status && !error && (
        <ErrorState title="无遥测数据" what="状态接口没有返回任何内容。" cause="后端版本可能尚未提供 /system/status。" next="部署更新后的后端，或刷新后重试。" actions={<button type="button" className="btn btn--primary btn--sm" onClick={() => void load()}>重试</button>} />
      )}
    </>
  );
}
