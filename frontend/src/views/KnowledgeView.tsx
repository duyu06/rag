"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ChunkItem, DocumentItem, hasPermission, IngestionJob, KnowledgeBase } from "@/lib/api";
import {
  DataTable,
  EmptyState,
  ErrorState,
  FilterChips,
  Kicker,
  Kv,
  Modal,
  PageHeader,
  PipelineStep,
  SkeletonRows,
  Stat,
  Status,
  statusTone,
  StepState,
  TRow,
  Tabs,
  departmentLabel,
  fmtMs,
  fmtNum,
  fmtTime,
  relTime,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

type Tab = "bases" | "documents" | "chunks" | "ingestion";

const DOC_COLS = "minmax(220px,2.2fr) 1fr 84px 72px 96px 84px minmax(180px,auto)";

// 仅展示层映射：键是后端协议枚举，比较与请求仍使用英文值。
const DOC_STATUS_ZH: Record<string, string> = { ARCHIVED: "已归档" };

// 摄取管道阶段名由后端返回（UPLOAD/PARSE/…），此处只做显示中文。
const STAGE_ZH: Record<string, string> = {
  UPLOAD: "上传",
  PARSE: "解析",
  NORMALIZE: "规范化",
  CHUNK: "切分",
  EMBED: "向量化",
  INDEX: "索引",
};

// action 字面量会拼进请求 URL，必须保持英文；只有这一张展示表被翻译。
const ACTION_ZH: Record<Parameters<typeof api.documentAction>[0], string> = {
  reindex: "重建索引",
  enable: "启用",
  disable: "停用",
  archive: "归档",
  restore: "恢复",
  move: "移动",
};

function docStatus(doc: DocumentItem): string {
  if (doc.archived) return "ARCHIVED";
  if (doc.enabled === false) return "DISABLED";
  return (doc.status || "READY").toUpperCase();
}

// 交给 <Status> 显示：能映射的枚举由 ui.tsx 转中文，其余在这里兜底。
function docStatusLabel(status: string): string {
  return DOC_STATUS_ZH[status] ?? status;
}

function stageLabel(name?: string | null): string {
  const key = (name || "").toUpperCase();
  return STAGE_ZH[key] ?? key;
}

function stageState(status?: string | null): StepState {
  const s = (status || "").toUpperCase();
  if (s === "OK" || s === "READY" || s === "DONE" || s === "COMPLETE" || s === "SUCCESS") return "done";
  if (s === "RUNNING" || s === "PROCESSING" || s === "INDEXING" || s === "PENDING") return "running";
  if (s === "FAILED" || s === "ERROR") return "failed";
  return "waiting";
}

export default function KnowledgeView({ user, bases, selectedKb, setSelectedKb, navigate, setNotice, payload }: ViewProps) {
  const canManage = hasPermission(user, "knowledge:manage");
  const [tab, setTab] = useState<Tab>((payload as { tab?: Tab } | undefined)?.tab || "bases");

  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState("");

  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [sortBy, setSortBy] = useState<"name" | "chunks" | "date">("date");
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const [detail, setDetail] = useState<DocumentItem | null>(null);
  const [detailChunks, setDetailChunks] = useState<ChunkItem[]>([]);
  const [moveTarget, setMoveTarget] = useState<DocumentItem | null>(null);
  const [moveKb, setMoveKb] = useState("");

  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [chunkFile, setChunkFile] = useState("");
  const [chunkOpen, setChunkOpen] = useState<ChunkItem | null>(null);
  const [chunksLoading, setChunksLoading] = useState(false);

  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [jobOpen, setJobOpen] = useState<string>("");
  const [jobsLoading, setJobsLoading] = useState(false);

  const loadDocs = useCallback(async () => {
    setDocsLoading(true);
    setDocsError("");
    try {
      const data = await api.documents(selectedKb);
      setDocs(data.documents || []);
    } catch (e) {
      setDocsError(e instanceof Error ? e.message : "文档加载失败");
    } finally {
      setDocsLoading(false);
    }
  }, [selectedKb]);

  useEffect(() => { void loadDocs(); }, [loadDocs]);

  useEffect(() => {
    if (payload?.fileName) {
      setTab("documents");
      setFilter(payload.fileName);
    }
  }, [payload?.fileName]);

  const loadChunks = useCallback(async (fileName: string, offset = 0, append = false) => {
    setChunksLoading(true);
    try {
      const data = await api.chunks({ knowledgeBaseId: selectedKb, fileName: fileName || undefined, limit: 20, offset });
      setChunks((current) => (append ? [...current, ...(data.chunks || [])] : data.chunks || []));
      setChunkTotal(data.total ?? (data.chunks || []).length);
    } catch {
      setChunks([]);
      setChunkTotal(0);
    } finally {
      setChunksLoading(false);
    }
  }, [selectedKb]);

  useEffect(() => {
    if (tab === "chunks") void loadChunks(chunkFile);
  }, [tab, chunkFile, loadChunks]);

  useEffect(() => {
    if (tab === "ingestion") {
      setJobsLoading(true);
      api.ingestionJobs(20).then((data) => setJobs(data.jobs || [])).catch(() => setJobs([])).finally(() => setJobsLoading(false));
    }
  }, [tab]);

  const filteredDocs = useMemo(() => {
    const term = filter.trim().toLowerCase();
    let rows = docs.filter((doc) => {
      if (term && !`${doc.file_name} ${doc.knowledge_base_name}`.toLowerCase().includes(term)) return false;
      if (statusFilter === "ARCHIVED") return doc.archived === true;
      if (statusFilter !== "ALL" && docStatus(doc) !== statusFilter) return doc.archived ? false : true && docStatus(doc) === statusFilter;
      return !doc.archived || statusFilter === "ARCHIVED";
    });
    rows = [...rows].sort((a, b) => {
      if (sortBy === "name") return a.file_name.localeCompare(b.file_name);
      if (sortBy === "chunks") return b.chunk_count - a.chunk_count;
      return (b.upload_date || "").localeCompare(a.upload_date || "");
    });
    return rows;
  }, [docs, filter, statusFilter, sortBy]);

  const selectedKeys = Object.keys(selected).filter((k) => selected[k]);

  const runAction = async (action: Parameters<typeof api.documentAction>[0], doc: DocumentItem, extra?: { target_knowledge_base_id?: string }) => {
    try {
      await api.documentAction(action, { file_name: doc.file_name, knowledge_base_id: doc.knowledge_base_id, ...extra });
      setNotice(`${ACTION_ZH[action]} · ${doc.file_name}`);
      await loadDocs();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : `${ACTION_ZH[action]}失败`, "err");
    }
  };

  const bulk = async (action: Parameters<typeof api.documentAction>[0]) => {
    const targets = docs.filter((doc) => selected[`${doc.knowledge_base_id}:${doc.file_name}`]);
    for (const doc of targets) {
      try { await api.documentAction(action, { file_name: doc.file_name, knowledge_base_id: doc.knowledge_base_id }); } catch { /* continue bulk */ }
    }
    setNotice(`${ACTION_ZH[action]} · ${targets.length} 份文档`);
    setSelected({});
    await loadDocs();
  };

  const openDetail = async (doc: DocumentItem) => {
    setDetail(doc);
    setDetailChunks([]);
    try {
      const data = await api.chunks({ knowledgeBaseId: doc.knowledge_base_id, fileName: doc.file_name, limit: 10 });
      setDetailChunks(data.chunks || []);
    } catch { /* detail chunks optional */ }
  };

  const kbHealth = (base: KnowledgeBase) => {
    const rows = docs.filter((doc) => doc.knowledge_base_id === base.id);
    const failed = rows.filter((doc) => docStatus(doc) === "FAILED").length;
    const indexing = rows.filter((doc) => docStatus(doc) === "INDEXING").length;
    if (failed) return <Status label={`${failed} 项失败`} tone="err" />;
    if (indexing) return <Status label={`${indexing} 项索引中`} tone="warn" />;
    return <Status label="就绪" tone="ok" />;
  };

  return (
    <>
      <PageHeader
        kicker="04 知识库 · 生命周期管控"
        title="知识库"
        desc="知识库、文档、切片与摄取管道。每个来源的每一阶段都可核查：有没有进入索引？没有的话卡在哪一步？"
        actions={canManage && (
          <div className="actions-row">
            <label className="btn btn--primary btn--sm">
              上传文档
              <input
                type="file"
                accept=".pdf,.docx,.txt,.md"
                style={{ display: "none" }}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  try {
                    const result = await api.upload(file, selectedKb === "all" ? bases[0]?.id || "kb_public" : selectedKb);
                    setNotice(`已开始摄取 · ${result.file_name}`);
                    setTab("ingestion");
                  } catch (err) {
                    setNotice(err instanceof Error ? err.message : "上传失败", "err");
                  }
                }}
              />
            </label>
          </div>
        )}
      />

      <Tabs
        items={[
          { key: "bases", label: "知识库", count: bases.length },
          { key: "documents", label: "文档", count: docs.length },
          { key: "chunks", label: "切片" },
          { key: "ingestion", label: "摄取", count: jobs.length || undefined },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "bases" && (
        <section aria-label="知识库列表">
          {bases.map((base, index) => {
            const rows = docs.filter((doc) => doc.knowledge_base_id === base.id);
            const chunksCount = rows.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
            const updatedAt = rows.map((doc) => doc.updated_at || doc.upload_date).sort().pop();
            return (
              <div
                key={base.id}
                className="kb-row"
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === "Enter" && (setSelectedKb(base.id), setTab("documents"))}
                onClick={() => { setSelectedKb(base.id); setTab("documents"); }}
              >
                <span className="idx">{String(index + 1).padStart(2, "0")}</span>
                <div style={{ minWidth: 0 }}>
                  <h3>{base.name}<small>{departmentLabel(base.department)}</small></h3>
                  <p className="desc">{base.description || `知识域 ${base.id}。`}</p>
                  <div className="facts">
                    <span>文档 <b>{rows.length}</b></span>
                    <span>切片 <b>{fmtNum(chunksCount)}</b></span>
                    <span>更新 <b>{relTime(updatedAt)}</b></span>
                    <span>ID <b>{base.id}</b></span>
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>{kbHealth(base)}<div className="open mt-2">打开 →</div></div>
              </div>
            );
          })}
          {!bases.length && !docsLoading && <EmptyState code="知识库 / 空" title="没有可见的知识库" desc="当前角色的权限策略尚未授予任何知识库的访问范围。" />}
        </section>
      )}

      {tab === "documents" && (
        <>
          <div className="row-between mb-6">
            <input className="input" style={{ maxWidth: 320 }} placeholder="按文件名筛选…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="筛选文档" />
            <div className="actions-row">
              <FilterChips
                options={[
                  { key: "ALL", label: "全部" },
                  { key: "READY", label: "就绪" },
                  { key: "INDEXING", label: "索引中" },
                  { key: "FAILED", label: "失败" },
                  { key: "DISABLED", label: "已停用" },
                  { key: "ARCHIVED", label: "已归档" },
                ]}
                value={statusFilter}
                onChange={setStatusFilter}
              />
              <FilterChips
                label="排序"
                options={[{ key: "date", label: "更新时间" }, { key: "name", label: "名称" }, { key: "chunks", label: "切片数" }]}
                value={sortBy}
                onChange={(key) => setSortBy(key as typeof sortBy)}
              />
            </div>
          </div>

          {canManage && selectedKeys.length > 0 && (
            <div className="notice" role="status">
              <span>已选 {selectedKeys.length} 项</span>
              <div className="actions-row">
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void bulk("reindex")}>重建索引</button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void bulk("enable")}>启用</button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void bulk("disable")}>停用</button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void bulk("archive")}>归档</button>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setSelected({})}>清除选择</button>
              </div>
            </div>
          )}

          {docsError && <div className="mb-6"><ErrorState title="文档列表加载失败" what={docsError} cause="后端服务不可达。" next="重试，或到「系统」页查看服务状态。" actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => void loadDocs()}>重试</button>} /></div>}
          {docsLoading && !docs.length && <SkeletonRows rows={6} />}

          {!docsLoading && (
            <DataTable
              cols={DOC_COLS}
              head={[
                canManage ? <label key="bulk" className="check" style={{ minHeight: 24 }}><input type="checkbox" aria-label="全选" checked={selectedKeys.length > 0 && selectedKeys.length === filteredDocs.length} onChange={(e) => { const next: Record<string, boolean> = {}; if (e.target.checked) filteredDocs.forEach((d) => { next[`${d.knowledge_base_id}:${d.file_name}`] = true; }); setSelected(next); }} /></label> : <span key="bulk">选择</span>,
                "名称", "知识库", "大小", "切片", "状态", "更新时间 · 操作",
              ]}
            >
              {filteredDocs.map((doc) => {
                const key = `${doc.knowledge_base_id}:${doc.file_name}`;
                const status = docStatus(doc);
                return (
                  <TRow key={key} cols={DOC_COLS} selected={Boolean(selected[key])} onClick={() => void openDetail(doc)} label={`打开 ${doc.file_name}`}>
                    <span onClick={(e) => e.stopPropagation()}>
                      {canManage && <input type="checkbox" checked={Boolean(selected[key])} aria-label={`选择 ${doc.file_name}`} onChange={(e) => setSelected((c) => ({ ...c, [key]: e.target.checked }))} />}
                    </span>
                    <span className="primary-col"><span className="type-badge">{doc.file_type.toUpperCase()}</span><b>{doc.file_name}</b></span>
                    <span className="cell-mono">{doc.knowledge_base_name}</span>
                    <span className="cell-mono">{fmtNum(Math.round(doc.file_size_kb))} KB</span>
                    <span className="cell-mono">{fmtNum(doc.chunk_count)}</span>
                    <span><Status label={docStatusLabel(status)} tone={statusTone(status)} /></span>
                    <span className="cell-mono" onClick={(e) => e.stopPropagation()}>
                      {fmtTime(doc.updated_at || doc.upload_date)}
                      {canManage && (
                        <span style={{ marginLeft: 8 }}>
                          <button type="button" className="btn-link" onClick={() => void runAction("reindex", doc)}>重建索引</button>
                          {doc.enabled === false
                            ? <button type="button" className="btn-link" style={{ marginLeft: 8 }} onClick={() => void runAction("enable", doc)}>启用</button>
                            : <button type="button" className="btn-link" style={{ marginLeft: 8 }} onClick={() => void runAction("disable", doc)}>停用</button>}
                        </span>
                      )}
                    </span>
                  </TRow>
                );
              })}
              {!filteredDocs.length && <EmptyState code="文档 / 0" title="没有匹配的文档。" desc="调整筛选条件，或上传源文档以启动摄取。" />}
            </DataTable>
          )}
        </>
      )}

      {tab === "chunks" && (
        <>
          <div className="row-between mb-6">
            <form className="actions-row" style={{ gap: "var(--s3)" }} onSubmit={(e) => { e.preventDefault(); void loadChunks(chunkFile); }}>
              <input className="input" style={{ maxWidth: 320 }} placeholder="按源文档筛选…" value={chunkFile} onChange={(e) => setChunkFile(e.target.value)} aria-label="按源文档筛选切片" />
              <button type="submit" className="btn btn--ghost btn--sm">筛选</button>
            </form>
            <Kicker>{fmtNum(chunkTotal)} 个切片 · 服务端分页 · 范围 {selectedKb.toUpperCase()}</Kicker>
          </div>
          <DataTable cols="56px minmax(200px,1.4fr) 90px 64px 72px 60px minmax(200px,2fr) 120px" head={["#", "源文档", "知识库", "页码", "章节", "Token", "预览", "更新时间"]}>
            {chunksLoading && !chunks.length ? <TRow cols="1fr"><SkeletonRows rows={5} /></TRow> : null}
            {chunks.map((chunk, index) => (
              <TRow key={chunk.id} cols="56px minmax(200px,1.4fr) 90px 64px 72px 60px minmax(200px,2fr) 120px" selected={chunkOpen?.id === chunk.id} onClick={() => setChunkOpen(chunk)} label={`打开切片 ${index}`}>
                <span className="cell-mono">{String((chunk.chunk_index ?? index) + 1).padStart(3, "0")}</span>
                <span className="primary-col"><b>{chunk.file_name}</b></span>
                <span className="cell-mono">{chunk.knowledge_base_id || "—"}</span>
                <span className="cell-mono">{chunk.page ?? "—"}</span>
                <span className="cell-mono">{chunk.section || "—"}</span>
                <span className="cell-mono">{fmtNum(chunk.tokens)}</span>
                <span className="cell-mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{chunk.content}</span>
                <span className="cell-mono">{relTime(chunk.uploaded_at)}</span>
              </TRow>
            ))}
            {!chunksLoading && !chunks.length && <TRow cols="1fr"><EmptyState code="切片 / 0" title="当前范围内没有切片。" desc="文档走完摄取管道后才会出现切片。" /></TRow>}
          </DataTable>
          {chunks.length < chunkTotal && (
            <div className="result-bar"><Kicker>已显示 {chunks.length} / {chunkTotal}</Kicker><button type="button" className="btn-link" onClick={() => void loadChunks(chunkFile, chunks.length, true)}>加载更多 →</button></div>
          )}

          {chunkOpen && (
            <section className="panel mt-8" aria-label="切片详情">
              <div className="panel-head">
                <div><h3>切片详情 · {chunkOpen.id.slice(0, 12)}</h3><div className="sub">{chunkOpen.file_name} · {chunkOpen.page != null ? `第 ${chunkOpen.page} 页` : "无页码"} · {chunkOpen.section || "无章节"}</div></div>
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setChunkOpen(null)}>关闭</button>
              </div>
              <div className="panel-pad">
                <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.8, maxHeight: 240, overflow: "auto" }}>{chunkOpen.content}</p>
                <div className="stat-row">
                  <Stat value={fmtNum(chunkOpen.tokens)} label="Token" />
                  <Stat value={chunkOpen.chunk_index != null ? chunkOpen.chunk_index + 1 : "—"} label="位置" />
                  <Stat value={chunkOpen.knowledge_base_name || chunkOpen.knowledge_base_id || "—"} label="知识库" />
                </div>
                <div className="actions-row">
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => chunkOpen.knowledge_base_id && void api.openSource(chunkOpen.knowledge_base_id, chunkOpen.file_name)}>返回源文档</button>
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => { setChunkFile(chunkOpen.file_name); }}>查看同文档上下文</button>
                  <button type="button" className="btn btn--accent btn--sm" onClick={() => navigate("retrieval", { query: chunkOpen.content.slice(0, 40), fileName: chunkOpen.file_name })}>
                    测试检索 →
                  </button>
                </div>
                <p className="muted mt-4" style={{ fontSize: 12 }}>该切片的向量分 / BM25 分 / 重排分由检索实验室的运行产出。</p>
              </div>
            </section>
          )}
        </>
      )}

      {tab === "ingestion" && (
        <section aria-label="摄取任务">
          {jobsLoading && <SkeletonRows rows={4} />}
          {!jobsLoading && !jobs.length && <EmptyState code="摄取 / 空闲" title="暂无摄取任务。" desc="上传文档后，其 上传 → 解析 → 规范化 → 切分 → 向量化 → 索引 六阶段管道会在此逐条记录。" />}
          {jobs.map((job) => {
            const open = jobOpen === job.job_id;
            return (
              <div key={job.job_id} className="panel" style={{ marginBottom: "var(--s4)" }}>
                <div className="row-between" style={{ padding: "var(--s4) var(--s6)", cursor: "pointer" }} onClick={() => setJobOpen(open ? "" : job.job_id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setJobOpen(open ? "" : job.job_id)}>
                  <div>
                    <b>{job.file_name}</b>
                    <div className="meta">{job.knowledge_base_name || job.knowledge_base_id || "—"} · {fmtTime(job.created_at)} · {fmtMs(job.total_elapsed_ms)}</div>
                  </div>
                  <div className="actions-row">
                    <Status label={(job.status || "PROCESSING").toUpperCase()} />
                    <span className="kicker">{open ? "−" : "+"} {job.stages?.length || 0} 个阶段</span>
                  </div>
                </div>
                {open && (
                  <div className="pipe" style={{ borderTop: "1px solid var(--line)" }}>
                    {(job.stages || []).map((stage, index) => (
                      <PipelineStep
                        key={stage.name}
                        index={index + 1}
                        name={stageLabel(stage.name)}
                        detail={stage.detail || undefined}
                        state={stageState(stage.status)}
                        cause={stage.error || undefined}
                        actions={stage.error && canManage ? (
                          <button type="button" className="btn btn--ghost btn--sm" onClick={(e) => { e.stopPropagation(); void runAction("reindex", { file_name: job.file_name, knowledge_base_id: job.knowledge_base_id || "" } as DocumentItem); }}>
                            重试
                          </button>
                        ) : undefined}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      )}

      {detail && (
        <Modal
          kicker="文档"
          title={detail.file_name}
          onClose={() => setDetail(null)}
          footer={
            <>
              {canManage && <button type="button" className="btn btn--ghost btn--sm" onClick={() => { setMoveKb(bases.find((b) => b.id !== detail.knowledge_base_id)?.id || ""); setMoveTarget(detail); }}>移动</button>}
              {canManage && <button type="button" className="btn btn--ghost btn--sm" onClick={() => { void runAction("archive", detail); setDetail(null); }}>归档</button>}
              {canManage && (
                <button type="button" className="btn btn--danger btn--sm" onClick={async () => {
                  if (!confirm(`确定删除 ${detail.file_name}？`)) return;
                  try { await api.deleteDocument(detail.file_name, detail.knowledge_base_id); setNotice("文档已删除"); setDetail(null); await loadDocs(); }
                  catch (e) { setNotice(e instanceof Error ? e.message : "删除失败", "err"); }
                }}>删除</button>
              )}
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void api.openSource(detail.knowledge_base_id, detail.file_name).catch((e) => setNotice(e.message, "err"))}>打开原文</button>
            </>
          }
        >
          <div className="mt-6">
            <Kv
              items={[
                ["状态", <Status key="s" label={docStatusLabel(docStatus(detail))} tone={statusTone(docStatus(detail))} />],
                ["知识库", `${detail.knowledge_base_name} (${detail.knowledge_base_id})`],
                ["大小", `${fmtNum(Math.round(detail.file_size_kb))} KB`],
                ["切片", fmtNum(detail.chunk_count)],
                ["上传时间", fmtTime(detail.upload_date)],
                ["所有者", detail.owner || "—"],
                ["权限", `读取 / 检索 / 下载随角色生效 → 见 ${detail.knowledge_base_id} 的访问控制；在「治理」页维护。`],
                ["最近错误", detail.last_error || "无"],
              ]}
            />
          </div>
          <div className="mt-8">
            <Kicker>切片（前 {detailChunks.length} 个）</Kicker>
            <div className="mt-2">
              {detailChunks.map((chunk, index) => (
                <div key={chunk.id} className="rank" style={{ gridTemplateColumns: "28px 1fr 60px" }}>
                  <span className="n">{String(index + 1).padStart(2, "0")}</span>
                  <span className="nm" style={{ whiteSpace: "normal" }}>{chunk.content.slice(0, 140)}</span>
                  <span className="sc">{chunk.page ? `${chunk.page} 页` : "—"}</span>
                </div>
              ))}
              {!detailChunks.length && <p className="muted" style={{ fontSize: 13 }}>暂无切片（接口尚未就绪，或文档仍在索引中）。</p>}
            </div>
            <div className="actions-row mt-4">
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => { setTab("chunks"); setChunkFile(detail.file_name); setDetail(null); }}>在切片列表中打开</button>
              <button type="button" className="btn btn--accent btn--sm" onClick={() => { navigate("retrieval", { query: detail.file_name.replace(/\.[^.]+$/, ""), fileName: detail.file_name }); setDetail(null); }}>测试检索 →</button>
            </div>
          </div>
        </Modal>
      )}

      {moveTarget && (
        <Modal
          kicker="文档 / 移动"
          title={`移动 ${moveTarget.file_name}`}
          onClose={() => setMoveTarget(null)}
          footer={
            <>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setMoveTarget(null)}>取消</button>
              <button type="button" className="btn btn--primary btn--sm" onClick={async () => {
                await runAction("move", moveTarget, { target_knowledge_base_id: moveKb });
                setMoveTarget(null);
              }}>移动</button>
            </>
          }
        >
          <div className="form-grid">
            <div className="field">
              <label htmlFor="move-kb">目标知识库</label>
              <select id="move-kb" className="select" value={moveKb} onChange={(e) => setMoveKb(e.target.value)}>
                {bases.filter((b) => b.id !== moveTarget.knowledge_base_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
