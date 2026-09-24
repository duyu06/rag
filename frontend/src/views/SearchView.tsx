"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, SearchResult } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  FilterChips,
  Kicker,
  PageHeader,
  SkeletonRows,
  Status,
  departmentLabel,
  fmtMs,
  fmtScore,
  highlight,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

const PAGE_SIZE = 20;

export default function SearchView({ bases, selectedKb, setSelectedKb, setNotice, payload }: ViewProps) {
  const [query, setQuery] = useState(payload?.query || "");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [tookMs, setTookMs] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState(0);
  const [searched, setSearched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const terms = useMemo(() => query.split(/[\s，。？?；;：:、]+/).filter((t) => t.length >= 2), [query]);

  const run = useCallback(async (q: string, kb: string, offset = 0, append = false) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setRunning(true);
    setError("");
    if (!append) { setResults([]); setCursor(0); }
    try {
      const scoped = kb === "all" ? null : kb;
      const result = await api.search(trimmed, scoped);
      const rows = (result.results || []).slice(offset, offset + PAGE_SIZE);
      setResults((current) => (append ? [...current, ...rows] : rows));
      setTotal(result.results?.length ?? rows.length);
      setTookMs(result.took_ms ?? null);
      setSearched(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "搜索失败");
    } finally {
      setRunning(false);
    }
  }, []);

  useEffect(() => {
    if (payload?.query) {
      setQuery(payload.query);
      void run(payload.query, selectedKb);
    }
    inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload?.query]);

  const openOriginal = async (row: SearchResult) => {
    if (!row.knowledge_base_id) { setNotice("该结果没有绑定源文件。", "err"); return; }
    try { await api.openSource(row.knowledge_base_id, row.file_name); }
    catch (e) { setNotice(e instanceof Error ? e.message : "打开失败", "err"); }
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        if (event.key === "Escape") (event.target as HTMLElement).blur();
        return;
      }
      if (event.key === "j") setCursor((c) => Math.min(results.length - 1, c + 1));
      else if (event.key === "k") setCursor((c) => Math.max(0, c - 1));
      else if (event.key === "Enter" && results[cursor]) void openOriginal(results[cursor]);
      else if (event.key === "/") { event.preventDefault(); inputRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, cursor]);

  // key 是范围协议值（"all" 与知识库 ID），label 才是展示文案。
  const scopeOptions = [
    { key: "all", label: "全部知识库" },
    ...bases.map((base) => ({ key: base.id, label: base.name.toUpperCase() })),
  ];

  return (
    <>
      <PageHeader
        kicker="03 检索 · 找文档，不给答案"
        title="检索"
        desc="在你有权限访问的知识范围内做关键词 + 语义查找。问答（02）生成带引用的回答，检索返回来源文档。"
      />

      <form
        className="home-search"
        style={{ maxWidth: "none", marginBottom: "var(--s6)" }}
        onSubmit={(e) => { e.preventDefault(); void run(query, selectedKb); }}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索文档、章节、页面内容…"
          aria-label="检索知识库"
        />
        <span className="hint">{running ? <Status label="PROCESSING" tone="warn" /> : "⏎ 搜索 · J/K 移动 · ⌘K 全局"}</span>
      </form>

      <FilterChips
        label="范围"
        options={scopeOptions}
        value={selectedKb}
        onChange={(key) => {
          setSelectedKb(key);
          if (query.trim()) void run(query, key);
        }}
      />

      {error && (
        <div style={{ margin: "var(--s6) 0" }}>
          <ErrorState
            title="搜索失败"
            what={error}
            cause="搜索接口拒绝了请求，或当前不可用。"
            next="确认范围后重试；需要带权限范围的答案请改用问答。"
            actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => void run(query, selectedKb)}>重试</button>}
          />
        </div>
      )}

      <section className="panel mt-6" aria-label="搜索结果">
        <div className="result-bar">
          <span>
            {searched ? `${results.length}${total != null && total > results.length ? ` / ${total}` : ""} 条结果 · 范围 ${selectedKb === "all" ? "全部" : selectedKb.toUpperCase()}${tookMs != null ? ` · ${fmtMs(tookMs)}` : ""}` : "空闲 — 请输入查询词"}
          </span>
          <span>{running ? "搜索中…" : results.length ? "双击 → 打开原文" : ""}</span>
        </div>

        {running && !results.length && <div style={{ padding: "var(--s4) var(--s6)" }}><SkeletonRows rows={5} /></div>}

        {!running && !results.length && searched && !error && (
          <EmptyState
            code="检索 / 0 条结果"
            title="没有匹配的片段。"
            desc="少说几个词，或切换范围试试。需要答案而不是文档时，请改用问答。"
          />
        )}

        {results.map((row, index) => (
          <div
            key={`${row.file_name}-${index}`}
            className={index === cursor ? "sresult sel" : "sresult"}
            onClick={() => { setCursor(index); }}
            onDoubleClick={() => void openOriginal(row)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter") { setCursor(index); void openOriginal(row); } }}
          >
            <span className="n">{String(index + 1).padStart(2, "0")}</span>
            <div style={{ minWidth: 0 }}>
              <div className="doc">{row.file_name}</div>
              <p className="snippet">{highlight((row.content || "").slice(0, 260), terms)}</p>
              <div className="tags">
                <span>{row.knowledge_base_name || row.knowledge_base_id || "—"}</span>
                {row.page ? <span>{row.page} 页</span> : null}
                {row.section ? <span>{row.section}</span> : null}
                {row.file_type ? <span>{row.file_type.toUpperCase()}</span> : null}
              </div>
            </div>
            <div className="right">
              <span>得分 {fmtScore(row.score)}</span>
              <span>{departmentLabel(row.department) || "全企业"}</span>
              <button
                type="button"
                className="btn-link"
                onClick={(e) => { e.stopPropagation(); void openOriginal(row); }}
              >
                打开原文 →
              </button>
            </div>
          </div>
        ))}

        {total != null && total > results.length && (
          <div className="result-bar">
            <Kicker>仍有更多结果</Kicker>
            <button type="button" className="btn-link" onClick={() => void run(query, selectedKb, results.length, true)}>加载更多 →</button>
          </div>
        )}
      </section>
    </>
  );
}
