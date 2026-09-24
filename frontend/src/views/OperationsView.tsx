"use client";

import { useEffect, useState } from "react";
import { api, AuditEvent, FeedbackItem, UsageSummary } from "@/lib/api";
import {
  DataTable,
  EmptyState,
  ErrorState,
  FilterChips,
  Kicker,
  PageHeader,
  SkeletonRows,
  Stat,
  Status,
  TRow,
  fmtMs,
  fmtNum,
  fmtTime,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

/* 显示层译名：以下映射只用于渲染，比较值与接口字段保持英文。 */
const ROLE_LABELS: Record<string, string> = {
  ADMIN: "管理员",
  SALES: "销售",
  HR: "人事",
  USER: "普通用户",
  VIEWER: "访客",
};
const ACTION_LABELS: Record<string, string> = {
  ALL: "全部",
  LOGIN: "登录",
  LOGOUT: "登出",
  QUERY: "问答",
  ASK: "问答",
  SEARCH: "搜索",
  UPLOAD: "上传",
  INGEST: "文档入库",
  DOWNLOAD: "下载",
  DELETE: "删除",
  ACCESS: "访问",
  AUTHORIZATION: "授权",
  ACCESS_REQUEST: "权限申请",
  SOURCE_VIEW: "查看来源",
  RETRIEVAL_DEBUG: "检索调试",
  EVALUATION: "RAG 评测",
  EVAL_FAILURE_TRIAGE: "评测失败归类",
  FEEDBACK: "回答反馈",
  DOCUMENT_MOVE: "文档移动",
  DOCUMENT_ENABLE: "文档启用",
  DOCUMENT_DISABLE: "文档停用",
  DOCUMENT_REINDEX: "重建索引",
  DEMO_INIT: "初始化演示数据",
  DEMO_RESET: "重置演示数据",
  TOOL_CALL: "工具调用",
  TOOL_RESULT: "工具结果",
  DENIED: "已拒绝",
};
const CATEGORY_LABELS: Record<string, string> = {
  ANSWER: "回答",
  RETRIEVAL: "检索",
  CITATION: "引用",
  CONFLICT: "冲突",
  OTHER: "其他",
};

function roleLabel(role?: string | null) {
  if (!role) return "—";
  return ROLE_LABELS[role.toUpperCase()] ?? role;
}

function actionLabel(action?: string | null) {
  if (!action) return "—";
  return ACTION_LABELS[action.toUpperCase()] ?? action;
}

function categoryLabel(category?: string | null) {
  if (!category) return "—";
  return CATEGORY_LABELS[category.toUpperCase()] ?? category.toUpperCase();
}

export default function OperationsView({ navigate }: ViewProps) {
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [logs, setLogs] = useState<AuditEvent[]>([]);
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [logFilter, setLogFilter] = useState("ALL");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setError("");
      try {
        const [usageData, auditData] = await Promise.all([
          api.usage().catch(() => null),
          api.audit(100),
        ]);
        const feedbackData = await api.feedbackList(50).catch(() => ({ items: [] as FeedbackItem[] }));
        if (cancelled) return;
        setUsage(usageData);
        setLogs(auditData.events || []);
        setFeedback(feedbackData.items || []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "运营数据加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, []);

  const logTypes = ["ALL", "QUERY", "LOGIN", "UPLOAD", "DELETE", "DOWNLOAD", "DENIED"];
  const shownLogs = logFilter === "ALL" ? logs : logs.filter((event) => event.action.toUpperCase().includes(logFilter));

  return (
    <>
      <PageHeader
        kicker="08 运营 — 使用量 · 质量信号"
        title="运营"
        desc="知识系统真实的使用情况，以及回答在哪些地方失败。这里的反馈会进入评测闭环。"
      />

      {error && <div className="mb-6"><ErrorState title="运营数据加载失败" what={error} cause="审计接口不可用。" next="查看“系统”视图的状态后重试。" actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => location.reload()}>重新加载</button>} /></div>}
      {loading && <SkeletonRows rows={5} />}

      {!loading && (
        <>
          <div className="stat-row">
            <Stat big value={usage ? fmtNum(usage.queries_30d) : "—"} label="问答数 / 30 天" />
            <Stat value={usage?.queries_today != null ? fmtNum(usage.queries_today) : "—"} label="今日问答数" />
            <Stat value={usage ? `${fmtNum(usage.active_users)}/${fmtNum(usage.total_users)}` : "—"} label="活跃 / 总用户" />
            <Stat value={usage ? `${Math.round(usage.adoption_pct)}%` : "—"} label="采用率" />
            <Stat value={usage?.avg_latency_ms != null ? fmtMs(usage.avg_latency_ms) : "—"} label="平均问答延迟" />
            <Stat value={usage?.top_department?.name || "—"} label="最活跃部门" />
          </div>

          <section className="section" aria-label="回答反馈">
            <div className="section-head">
              <h2 className="sec-title">回答反馈</h2>
              <Kicker>{fmtNum(feedback.length)} 条信号 · 差评 → 失败分诊</Kicker>
            </div>
            <DataTable cols="64px minmax(220px,2fr) 110px 130px minmax(160px,1fr) 110px 90px" head={["#", "问题", "评价", "类别", "详情", "用户", "时间"]}>
              {feedback.map((item, index) => (
                <TRow key={item.id} cols="64px minmax(220px,2fr) 110px 130px minmax(160px,1fr) 110px 90px">
                  <span className="cell-mono">{String(index + 1).padStart(2, "0")}</span>
                  <span className="primary-col"><b>{item.question}</b></span>
                  <span>{item.verdict === "up" ? <Status label="好评" tone="ok" /> : <Status label="差评" tone="err" />}</span>
                  <span className="cell-mono">{categoryLabel(item.category)}</span>
                  <span className="cell-mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.detail || "—"}</span>
                  <span className="cell-mono">{item.username}</span>
                  <span className="cell-mono">{fmtTime(item.created_at)}</span>
                </TRow>
              ))}
              {!feedback.length && <TRow cols="1fr"><EmptyState code="反馈 / 0" title="尚无反馈记录。" desc="问答中的点赞与问题上报会落到这里，并按类别供分诊。" action={<button type="button" className="btn btn--ghost" onClick={() => navigate("evaluation")}>查看评测失败案例 →</button>} /></TRow>}
            </DataTable>
          </section>

          <section className="section" aria-label="问答日志">
            <div className="section-head">
              <h2 className="sec-title">活动与问答日志</h2>
              <FilterChips options={logTypes.map((t) => ({ key: t, label: ACTION_LABELS[t] ?? t }))} value={logFilter} onChange={setLogFilter} />
            </div>
            <DataTable cols="150px 120px 90px 140px 110px minmax(200px,1.6fr) 90px 90px" head={["时间", "用户", "角色", "操作", "状态", "查询 / 对象", "延迟", "来源数"]}>
              {shownLogs.slice(0, 60).map((event, index) => (
                <TRow key={index} cols="150px 120px 90px 140px 110px minmax(200px,1.6fr) 90px 90px">
                  <span className="cell-mono">{fmtTime(event.timestamp)}</span>
                  <span className="cell-mono">{event.username}</span>
                  <span className="cell-mono">{roleLabel(event.role)}</span>
                  <span className="cell-mono">{actionLabel(event.action)}</span>
                  <span><Status label={(event.status || "OK").toUpperCase()} /></span>
                  <span className="cell-mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{event.query || event.detail || event.knowledge_base_id || "—"}</span>
                  <span className="cell-mono">{fmtMs(event.latency_ms)}</span>
                  <span className="cell-mono">{event.num_sources ?? "—"}</span>
                </TRow>
              ))}
              {!shownLogs.length && <TRow cols="1fr"><EmptyState code="日志 / 0" title="没有匹配的事件。" desc="高风险操作（登录、问答、下载、删除、权限与模型变更）都会留下审计记录。" /></TRow>}
            </DataTable>
            {shownLogs.length > 60 && <div className="result-bar"><Kicker>共 {shownLogs.length} 条，此处显示前 60 条</Kicker><span>更多数据请调用接口 /audit?limit=</span></div>}
          </section>
        </>
      )}
    </>
  );
}
