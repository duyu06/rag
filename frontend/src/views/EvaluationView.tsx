"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, EvalCaseResult, EvalRun, FailureCase } from "@/lib/api";
import {
  DataTable,
  EmptyState,
  ErrorState,
  Kicker,
  Kv,
  MetricStrip,
  Modal,
  PageHeader,
  SkeletonRows,
  Status,
  TRow,
  Tabs,
  fmtMs,
  fmtNum,
  fmtTime,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

type Tab = "overview" | "dataset" | "runs" | "failures";

// 显示层译名：value 是提交 / 比对后端用的原始字符串，保持英文；label 只用于展示。
const FAILURE_TYPES: { value: string; label: string }[] = [
  { value: "RETRIEVAL", label: "未检索到" },
  { value: "RERANK", label: "排序错误" },
  { value: "CHUNK", label: "切分问题" },
  { value: "QUERY REWRITE", label: "查询改写问题" },
  { value: "ACL", label: "权限受限" },
  { value: "ANSWER", label: "回答不完整" },
];

const ACTIONS: { value: string; label: string }[] = [
  { value: "Add synonym mapping", label: "补充同义词映射" },
  { value: "Adjust Chunk", label: "调整切分" },
  { value: "Change retrieval config", label: "修改检索配置" },
  { value: "Re-index", label: "重建索引" },
  { value: "None yet", label: "暂不处理" },
];

// run.modes 的 key 来自后端，不做翻译；只在展示时换成中文模式名。
const MODE_LABELS: Record<string, string> = {
  vector: "向量",
  bm25: "关键词",
  hybrid: "混合",
  hybrid_rerank: "混合+重排",
};

// 指标字段名是后端 key，展示沿用 HIT@1 / HIT@3 / MRR 记法。
const METRIC_LABELS: Record<string, string> = {
  hit_at_1: "HIT@1",
  hit_at_3: "HIT@3",
  mrr: "MRR",
};

const failureTypeLabel = (value?: string | null) => FAILURE_TYPES.find((item) => item.value === value)?.label ?? value ?? "";
const actionLabel = (value?: string | null) => ACTIONS.find((item) => item.value === value)?.label ?? value ?? "";
const modeLabel = (value?: string | null) => (value ? MODE_LABELS[value] ?? value.toUpperCase() : "");

function modeKeys(run: EvalRun) {
  return Object.keys(run.modes || {});
}

export default function EvaluationView({ navigate, payload }: ViewProps) {
  const [tab, setTab] = useState<Tab>("overview");
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [compareId, setCompareId] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [failures, setFailures] = useState<FailureCase[]>([]);
  const [editing, setEditing] = useState<FailureCase | null>(null);
  const [editType, setEditType] = useState("");
  const [editCause, setEditCause] = useState("");
  const [editAction, setEditAction] = useState("");
  const [editRegression, setEditRegression] = useState(false);

  const primaryMode = useMemo(() => (run ? modeKeys(run).slice(-1)[0] : ""), [run]);

  const refreshRuns = useCallback(async () => {
    try {
      const data = await api.evalRuns(10);
      setRuns(data.runs || []);
      return data.runs || [];
    } catch {
      return [];
    }
  }, []);

  const openRun = useCallback(async (runId: string) => {
    try {
      const detail = await api.evalRun(runId);
      setRun(detail);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "评测记录加载失败");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      const list = await refreshRuns();
      if (list.length) await openRun(list[0].run_id);
      try { setFailures((await api.evalFailures()).cases || []); } catch { /* pending backend */ }
    })();
  }, [refreshRuns, openRun]);

  const runEvaluation = async () => {
    setRunning(true);
    setError("");
    try {
      await api.runEvaluation();
      const list = await refreshRuns();
      if (list.length) await openRun(list[0].run_id);
      try { setFailures((await api.evalFailures()).cases || []); } catch { /* ignore */ }
    } catch (e) {
      setError(e instanceof Error ? e.message : "评测失败");
    } finally {
      setRunning(false);
    }
  };

  const [compareDetail, setCompareDetail] = useState<EvalRun | null>(null);

  useEffect(() => {
    if (!compareId) {
      setCompareDetail(null);
      return;
    }
    // runs 列表接口不含 cases，对比必须拉取完整运行详情
    let active = true;
    void (async () => {
      try {
        const detail = await api.evalRun(compareId);
        if (active) setCompareDetail(detail);
      } catch {
        if (active) setCompareDetail(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [compareId]);

  const compareRun = compareDetail;

  const diff = useMemo(() => {
    if (!run || !compareRun || !primaryMode) return null;
    const base = new Map((compareRun.cases?.[primaryMode] || []).map((item) => [item.case_id, item]));
    const improved: EvalCaseResult[] = [];
    const regressed: EvalCaseResult[] = [];
    let unchanged = 0;
    for (const item of run.cases?.[primaryMode] || []) {
      const old = base.get(item.case_id);
      if (!old) continue;
      if (!old.passed && item.passed) improved.push(item);
      if (old.passed && !item.passed) regressed.push(item);
      if (old.passed === item.passed) unchanged += 1;
    }
    return { improved, regressed, unchanged };
  }, [run, compareRun, primaryMode]);

  const saveFailure = async () => {
    if (!editing) return;
    try {
      await api.patchEvalFailure(editing.case_id, {
        failure_type: editType || undefined,
        root_cause: editCause || undefined,
        action: editAction || undefined,
        regression: editRegression,
      });
      setFailures((current) => current.map((item) => item.case_id === editing.case_id
        ? { ...item, failure_type: editType, root_cause: editCause, action: editAction, regression: editRegression }
        : item));
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "失败案例更新失败");
      setEditing(null);
    }
  };

  const openFailure = (item: FailureCase) => {
    setEditing(item);
    setEditType(item.failure_type || "");
    setEditCause(item.root_cause || "");
    setEditAction(item.action || "");
    setEditRegression(Boolean(item.regression));
  };

  return (
    <>
      <PageHeader
        kicker="07 评测 · HIT@1 / HIT@3 / MRR"
        title="评测"
        desc="按检索模式统计数据集整体质量，保存每次运行记录并支持两两对比；失败案例作为一等数据，驱动改进闭环。"
        actions={
          <div className="actions-row">
            <button type="button" className="btn btn--primary btn--sm" disabled={running} onClick={() => void runEvaluation()}>
              {running ? "评测进行中…" : "运行评测"}
            </button>
            {payload?.caseId && <button type="button" className="btn btn--ghost btn--sm" onClick={() => setTab("failures")}>查看失败案例</button>}
          </div>
        }
      />

      {error && <div className="mb-6"><ErrorState title="评测出错" what={error} cause="某个评测接口调用失败。" next="请重试，或查看“系统”视图的状态。" actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => setError("")}>关闭提示</button>} /></div>}

      <Tabs
        items={[
          { key: "overview", label: "总览" },
          { key: "dataset", label: "数据集", count: run?.cases?.[primaryMode]?.length },
          { key: "runs", label: "运行记录", count: runs.length },
          { key: "failures", label: "失败案例", count: failures.length || undefined },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "overview" && (
        !run && !running ? <EmptyState code="评测 / 暂无运行记录" title="尚无已保存的运行。" desc="运行一次评测套件即可持久化指标，并开启对比流程。" action={<button type="button" className="btn btn--primary" onClick={() => void runEvaluation()}>运行评测</button>} />
          : running && !run ? <SkeletonRows rows={5} />
          : run && (
            <>
              <section className="panel" aria-label="运行指标">
                <div className="panel-head">
                  <div><h3>运行 · {run.name}</h3><div className="sub">{run.run_id} · {fmtTime(run.created_at)} · 数据集 {fmtNum(run.dataset_size)} 个用例</div></div>
                  <Status label="COMPLETE" tone="ok" />
                </div>
                <DataTable cols="180px 90px 90px 90px 110px 90px 90px" head={["检索模式", "HIT@1", "HIT@3", "MRR", "有据率", "用例数", "耗时"]}>
                  {modeKeys(run).map((mode) => {
                    const m = run.modes[mode];
                    return (
                      <TRow key={mode} cols="180px 90px 90px 90px 110px 90px 90px">
                        <span className="primary-col"><b>{modeLabel(mode)}</b></span>
                        <span className="cell-mono">{m.hit_at_1?.toFixed(3)}</span>
                        <span className="cell-mono">{m.hit_at_3?.toFixed(3)}</span>
                        <span className="cell-mono">{m.mrr?.toFixed(3)}</span>
                        <span className="cell-mono">{m.grounded_pct == null ? "—" : `${Math.round(m.grounded_pct)}%`}</span>
                        <span className="cell-mono">{fmtNum(m.total)}</span>
                        <span className="cell-mono">{fmtMs(m.elapsed_ms)}</span>
                      </TRow>
                    );
                  })}
                </DataTable>
                <MetricStrip items={[
                  ["最佳 HIT@3", Math.max(...modeKeys(run).map((k) => run.modes[k].hit_at_3 || 0)).toFixed(3)],
                  ["最佳 MRR", Math.max(...modeKeys(run).map((k) => run.modes[k].mrr || 0)).toFixed(3)],
                  ["失败案例", fmtNum(failures.length)],
                ]} />
              </section>
              <p className="muted mt-4" style={{ fontSize: 12 }}>有据率 = 结论能被所引用证据支撑的回答占比（回答级指标）。上方的检索指标以“混合+重排”作为出厂配置。</p>
            </>
          )
      )}

      {tab === "dataset" && (
        run ? (
          <DataTable cols="64px minmax(240px,2fr) 160px 90px 90px 90px 110px" head={["#", "问题", "期望来源", "标签", "排名", "结果", ""]}>
            {(run.cases?.[primaryMode] || []).map((item, index) => (
              <TRow key={item.case_id} cols="64px minmax(240px,2fr) 160px 90px 90px 90px 110px">
                <span className="cell-mono">{String(index + 1).padStart(2, "0")}</span>
                <span className="primary-col"><b>{item.question}</b></span>
                <span className="cell-mono">{item.expected_file}</span>
                <span className="cell-mono">{item.tag || "—"}</span>
                <span className="cell-mono">{item.rank ?? "未命中"}</span>
                <span>{item.passed ? <Status label="PASS" tone="ok" /> : <Status label="FAILED" tone="err" />}</span>
                <span><button type="button" className="btn-link" onClick={() => navigate("retrieval", { query: item.question, fileName: item.expected_file })}>调试 →</button></span>
              </TRow>
            ))}
          </DataTable>
        ) : <EmptyState code="数据集 / 未加载" title="请先运行一次评测。" desc="数据集视图展示的是某次运行中已持久化的逐用例结果。" />
      )}

      {tab === "runs" && (
        <>
          <DataTable cols="48px 200px minmax(200px,1fr) 120px 100px" head={["基线", "运行", "名称", "创建时间", "用例数"]}>
            {runs.map((item) => (
              <TRow key={item.run_id} cols="48px 200px minmax(200px,1fr) 120px 100px" selected={run?.run_id === item.run_id} onClick={() => void openRun(item.run_id)}>
                <span><input type="radio" name="run-a" checked={run?.run_id === item.run_id} onChange={() => void openRun(item.run_id)} aria-label={`选择运行记录 ${item.name}`} /></span>
                <span className="cell-mono">{item.run_id.slice(0, 8)}</span>
                <span className="primary-col"><b>{item.name}</b></span>
                <span className="cell-mono">{fmtTime(item.created_at)}</span>
                <span className="cell-mono">{fmtNum(item.dataset_size)}</span>
              </TRow>
            ))}
            {!runs.length && <TRow cols="1fr"><EmptyState code="运行记录 / 0" title="暂无已保存的运行记录。" desc="在“07 评测”之后创建的运行记录会列在这里。" /></TRow>}
          </DataTable>

          {run && runs.length > 1 && (
            <div className="row-between mt-8">
              <div className="actions-row">
                <Kicker>对比对象</Kicker>
                <select className="select" style={{ maxWidth: 240 }} value={compareId} onChange={(e) => setCompareId(e.target.value)} aria-label="对比运行记录">
                  <option value="">— 请选择 —</option>
                  {runs.filter((item) => item.run_id !== run.run_id).map((item) => <option key={item.run_id} value={item.run_id}>{item.name} · {fmtTime(item.created_at)}</option>)}
                </select>
              </div>
              {compareRun && diff && (
                <div className="actions-row">
                  <Status label={`${diff.improved.length} 项改善`} tone="ok" />
                  <Status label={`${diff.regressed.length} 项回退`} tone={diff.regressed.length ? "err" : "idle"} />
                  <Status label={`${diff.unchanged} 项持平`} tone="idle" />
                </div>
              )}
            </div>
          )}

          {compareRun && run && (
            <section className="panel mt-6">
              <div className="panel-head"><div><h3>对比 · {compareRun.run_id.slice(0, 8)} → {run.run_id.slice(0, 8)}</h3><div className="sub">检索模式：{modeLabel(primaryMode)}</div></div></div>
              <DataTable cols="160px 110px 110px 110px" head={["指标", "基线", "当前", "Δ"]}>
                {["hit_at_1", "hit_at_3", "mrr"].map((metric) => {
                  const a = (compareRun.modes[primaryMode] as any)?.[metric] ?? 0;
                  const b = (run.modes[primaryMode] as any)?.[metric] ?? 0;
                  const delta = b - a;
                  return (
                    <TRow key={metric} cols="160px 110px 110px 110px">
                      <span>{METRIC_LABELS[metric] ?? metric.toUpperCase()}</span>
                      <span className="cell-mono">{a.toFixed(3)}</span>
                      <span className="cell-mono">{b.toFixed(3)}</span>
                      <span className="cell-mono" style={{ color: delta > 0 ? "var(--ok)" : delta < 0 ? "var(--err)" : undefined }}>
                        {delta > 0 ? "+" : ""}{delta.toFixed(3)} {delta > 0 ? "▲" : delta < 0 ? "▼" : ""}
                      </span>
                    </TRow>
                  );
                })}
              </DataTable>
              {diff && (diff.improved.length > 0 || diff.regressed.length > 0) && (
                <div style={{ padding: "var(--s6)" }}>
                  {diff.improved.length > 0 && (
                    <>
                      <Kicker>改善用例</Kicker>
                      {diff.improved.map((item) => <div key={item.case_id} className="recent-item"><span className="n">▲</span><b>{item.question} → {item.expected_file}</b></div>)}
                    </>
                  )}
                  {diff.regressed.length > 0 && (
                    <>
                      <Kicker>回退用例 — 禁止发布</Kicker>
                      {diff.regressed.map((item) => <div key={item.case_id} className="recent-item"><span className="n">▼</span><b>{item.question} → {item.expected_file}</b></div>)}
                    </>
                  )}
                </div>
              )}
            </section>
          )}
        </>
      )}

      {tab === "failures" && (
        <>
          <DataTable cols="64px minmax(220px,2fr) 150px 90px 130px 120px 140px 90px" head={["#", "查询", "期望来源", "排名", "失败类型", "处理动作", "根本原因", "回归用例"]}>
            {failures.map((item, index) => (
              <TRow key={item.case_id} cols="64px minmax(220px,2fr) 150px 90px 130px 120px 140px 90px" selected={editing?.case_id === item.case_id} onClick={() => openFailure(item)} label={`编辑失败案例 ${item.case_id}`}>
                <span className="cell-mono">{String(index + 1).padStart(2, "0")}</span>
                <span className="primary-col"><b>{item.question}</b></span>
                <span className="cell-mono">{item.expected_file}</span>
                <span className="cell-mono">{item.rank ?? "未命中"}</span>
                <span>{item.failure_type ? <Status label={failureTypeLabel(item.failure_type)} tone="err" /> : <Kicker>待归类</Kicker>}</span>
                <span className="cell-mono">{item.action ? actionLabel(item.action) : "—"}</span>
                <span className="cell-mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.root_cause || "—"}</span>
                <span className="cell-mono">{item.regression ? "是" : "—"}</span>
              </TRow>
            ))}
            {!failures.length && <TRow cols="1fr"><EmptyState code="失败案例 / 已清空" title="暂无待处理失败案例。" desc="每次运行后，数据集中未通过的用例会自动落到这里 —— 请归类出根本原因与处理动作。" /></TRow>}
          </DataTable>
          {failures.length > 0 && <p className="muted mt-4" style={{ fontSize: 12 }}>闭环：发现 → 定位原因 → 修改配置 / 切分 / 同义词映射 → 重新运行 → 对比。标记为“回归用例”的案例每次都会重新校验。</p>}
        </>
      )}

      {editing && (
        <Modal
          kicker="失败案例归类"
          title={editing.question}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => { navigate("retrieval", { query: editing.question, fileName: editing.expected_file }); }}>到检索实验室调试 →</button>
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void saveFailure()}>保存归类</button>
            </>
          }
        >
          <div className="mt-6">
            <Kv items={[
              ["期望来源", editing.expected_file],
              ["实际结果", (editing.top_files || []).join(", ") || "—"],
              ["期望排名", "≤ 1（HIT@1）/ ≤ 3（HIT@3）"],
              ["实际排名", String(editing.rank ?? "未命中")],
              ["运行记录", editing.run_id],
            ]} />
          </div>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="ft">失败类型</label>
              <select id="ft" className="select" value={editType} onChange={(e) => setEditType(e.target.value)}>
                <option value="">— 请归类 —</option>
                {FAILURE_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="rc">根本原因</label>
              <textarea id="rc" className="textarea" value={editCause} onChange={(e) => setEditCause(e.target.value)} placeholder="例如：切分把费率表与它的小节标题拆开了" />
            </div>
            <div className="field">
              <label htmlFor="ac">处理动作</label>
              <select id="ac" className="select" value={editAction} onChange={(e) => setEditAction(e.target.value)}>
                <option value="">— 请选择 —</option>
                {ACTIONS.map((action) => <option key={action.value} value={action.value}>{action.label}</option>)}
              </select>
            </div>
            <label className="check"><input type="checkbox" checked={editRegression} onChange={(e) => setEditRegression(e.target.checked)} />加入回归用例集</label>
          </div>
        </Modal>
      )}
    </>
  );
}
