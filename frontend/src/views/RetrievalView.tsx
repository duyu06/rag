"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, DebugResult } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  Kicker,
  MetricStrip,
  PageHeader,
  RankRow,
  SkeletonRows,
  Status,
  fmtMs,
  fmtScore,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

type Mode = "vector" | "bm25" | "hybrid";

// 显示层译名；传给 API 的 mode 值保持英文枚举。
const MODE_LABELS: Record<Mode, string> = {
  vector: "向量",
  bm25: "关键词",
  hybrid: "混合",
};

export default function RetrievalView({ bases, selectedKb, navigate, payload }: ViewProps) {
  const [query, setQuery] = useState(payload?.query || "广州出差住宿标准");
  const [expected, setExpected] = useState(payload?.fileName || "");
  const [mode, setMode] = useState<Mode>("hybrid");
  const [rerank, setRerank] = useState(true);
  const [topK, setTopK] = useState(8);
  const [results, setResults] = useState<DebugResult[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [tookMs, setTookMs] = useState<number | null>(null);
  const [ran, setRan] = useState(false);

  useEffect(() => {
    if (payload?.query) {
      setQuery(payload.query);
      if (payload.fileName) setExpected(payload.fileName);
    }
  }, [payload?.query, payload?.fileName]);

  const run = useCallback(async () => {
    if (!query.trim()) return;
    setRunning(true);
    setError("");
    try {
      const started = performance.now();
      const data = await api.debug(query.trim(), mode, rerank, selectedKb === "all" ? null : selectedKb);
      setResults((data.results || []).slice(0, topK));
      setTookMs(Math.round(performance.now() - started));
      setRan(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "检索失败");
      setResults([]);
    } finally {
      setRunning(false);
    }
  }, [query, mode, rerank, selectedKb, topK]);

  useEffect(() => {
    if (payload?.query) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isHit = useCallback((row: DebugResult, rank: number) => {
    if (!expected.trim()) return null;
    const term = expected.trim().toLowerCase();
    return (row.file_name || "").toLowerCase().includes(term) ? rank <= 3 && (rank === 1 ? true : true) : false;
  }, [expected]);

  const metrics = useMemo(() => {
    if (!expected.trim()) return null;
    const term = expected.trim().toLowerCase();
    const index = results.findIndex((row) => (row.file_name || "").toLowerCase().includes(term));
    if (index < 0) return { hit1: 0, hit3: 0, mrr: 0, rank: null as number | null };
    const rank = index + 1;
    return { hit1: rank === 1 ? 1 : 0, hit3: rank <= 3 ? 1 : 0, mrr: 1 / rank, rank };
  }, [results, expected]);

  const scopeName = selectedKb === "all" ? "全部可访问知识库" : bases.find((b) => b.id === selectedKb)?.name || selectedKb;

  return (
    <>
      <PageHeader
        kicker="05 检索实验室 · 白盒检索"
        title="检索实验室"
        desc="对线上索引分别运行向量、关键词、混合融合与重排序，查看排名与分数，并对照期望来源给出命中 / 未命中判定。"
        actions={<Status label={running ? "RUNNING" : ran ? "READY" : "空闲"} tone={running ? "warn" : "ok"} />}
      />

      <div className="split">
        <div style={{ minWidth: 0 }}>
          <section className="panel" aria-label="排序结果">
            <div className="result-bar">
              <span>查询 · “{query}” · {MODE_LABELS[mode]}{rerank ? " + 重排" : ""} · 范围 {scopeName}</span>
              <span>{tookMs != null ? fmtMs(tookMs) : ""} {expected ? ` · 期望来源：${expected}${metrics?.rank ? ` · 命中于第 ${metrics.rank} 位` : metrics ? " · 未检索到" : ""}` : ""}</span>
            </div>
            {running && <div style={{ padding: "var(--s4) var(--s6)" }}><SkeletonRows rows={6} /></div>}
            {!running && !results.length && ran && !error && (
              <EmptyState code="检索 / 0 条候选" title="没有返回任何结果。" desc="在该查询与范围下，经权限过滤后的候选集为空。" />
            )}
            {!running && !results.length && !ran && !error && (
              <EmptyState code="检索实验室 / 空闲" title="配置参数后运行。" desc="选择检索模式，可填写期望来源，然后点击“运行检索”。" />
            )}
            {results.map((row, index) => {
              const score = rerank && row.rerank_score != null ? row.rerank_score : row.hybrid_score ?? row.vector_score;
              return (
                <RankRow
                  key={`${row.file_name}-${index}`}
                  index={index + 1}
                  name={row.file_name ?? "未知来源"}
                  meta={`${row.knowledge_base_name || row.knowledge_base_id || "—"} · 第 ${row.page ?? "—"} 页 · 向量 ${fmtScore(row.vector_score)} · BM25 ${fmtScore(row.bm25_score)} · 融合 ${fmtScore(row.hybrid_score)} · 重排 ${row.rerank_score == null ? "—" : fmtScore(row.rerank_score)}`}
                  score={fmtScore(score)}
                  hit={isHit(row, index + 1)}
                  onClick={() => navigate("knowledge", { fileName: row.file_name, knowledgeBaseId: row.knowledge_base_id })}
                />
              );
            })}
            {error && <div style={{ padding: "var(--s6)" }}><ErrorState title="检索运行失败" what={error} cause="检索调试接口拒绝了该请求。" next="确认检索模式与范围；具备 system:operate 权限的用户可复查服务状态。" actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => void run()}>重试</button>} /></div>}
            <MetricStrip
              items={[
                ["HIT@1", metrics ? String(metrics.hit1) : "—"],
                ["HIT@3", metrics ? String(metrics.hit3) : "—"],
                ["MRR", metrics ? metrics.mrr.toFixed(3) : "—"],
                ["候选数", results.length],
                ["耗时", fmtMs(tookMs)],
              ]}
            />
          </section>
          <p className="muted mt-4" style={{ fontSize: 12 }}>
            每行分数展示各召回通道：向量 = 稠密向量检索，BM25 = 关键词检索，融合 = RRF 混合融合，重排 = 交叉编码器重排序。数据集级别的 HIT@1 / HIT@3 / MRR 见“评测”视图。
          </p>
        </div>

        <aside className="inspector panel" aria-label="检索参数">
          <div className="insp-head"><h3>检索参数配置</h3></div>
          <div className="insp-sec">
            <div className="k">查询</div>
            <textarea className="textarea mt-2" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="检索查询" />
          </div>
          <div className="insp-sec">
            <div className="k">检索模式</div>
            <div className="seg mt-2" role="group" aria-label="检索模式">
              {(["vector", "bm25", "hybrid"] as Mode[]).map((m) => (
                <button key={m} type="button" className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{MODE_LABELS[m]}</button>
              ))}
            </div>
            <label className="check mt-4"><input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />重排序（交叉编码器）</label>
          </div>
          <div className="insp-sec">
            <div className="k">期望来源（用于命中 / 未命中判定）</div>
            <input className="input mt-2" placeholder="如：差旅制度.pdf" value={expected} onChange={(e) => setExpected(e.target.value)} />
          </div>
          <div className="insp-sec">
            <div className="k">返回条数</div>
            <select className="select mt-2" value={topK} onChange={(e) => setTopK(Number(e.target.value))} aria-label="返回条数">
              {[3, 5, 8, 12].map((k) => <option key={k} value={k}>前 {k} 条</option>)}
            </select>
          </div>
          <div className="insp-sec">
            <div className="k">范围</div>
            <div className="v mt-2">{scopeName}</div>
            <Kicker>在顶部栏切换</Kicker>
          </div>
          <div className="insp-sec">
            <button type="button" className="btn btn--primary btn--full" disabled={running || !query.trim()} onClick={() => void run()}>
              {running ? "进行中…" : "运行检索"}
            </button>
          </div>
        </aside>
      </div>
    </>
  );
}
