"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, DebugResult, DocumentItem, Source } from "@/lib/api";

type View = "dashboard" | "chat" | "knowledge" | "retrieval" | "system";

const nav: Array<{ key: View; label: string; short: string }> = [
  { key: "dashboard", label: "工作台", short: "总" },
  { key: "chat", label: "AI 知识助手", short: "问" },
  { key: "knowledge", label: "知识库", short: "库" },
  { key: "retrieval", label: "检索测试", short: "检" },
  { key: "system", label: "系统状态", short: "态" },
];

const suggestions = [
  "广州普通员工出差住宿标准是多少？",
  "退款超过 500 元需要谁审批？",
  "X100 产品保修期多久？",
  "销售折扣超过多少需要主管审批？",
];

function score(value?: number | null) {
  return value == null ? "—" : value.toFixed(3);
}

export default function Home() {
  const [view, setView] = useState<View>("dashboard");
  const [health, setHealth] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    const [healthResult, statsResult, docsResult] = await Promise.allSettled([
      api.health(),
      api.stats(),
      api.documents(),
    ]);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (statsResult.status === "fulfilled") setStats(statsResult.value);
    if (docsResult.status === "fulfilled") setDocs(docsResult.value.documents);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">N</div>
          <div><strong>NexusKB</strong><span>企业 AI 知识中台</span></div>
        </div>
        <nav className="nav-list">
          {nav.map((item) => (
            <button key={item.key} className={view === item.key ? "nav-item active" : "nav-item"} onClick={() => setView(item.key)}>
              <span className="nav-icon">{item.short}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="status-line"><i className={health?.status === "healthy" ? "dot ok" : "dot"} />{health?.status === "healthy" ? "服务运行正常" : "服务待检查"}</div>
          <div className="user-card"><div className="avatar">管</div><div><strong>管理员</strong><span>Demo Workspace</span></div></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div><h1>{nav.find((item) => item.key === view)?.label}</h1><p>Enterprise Retrieval-Augmented Generation</p></div>
          <div className="top-actions"><span className="pill">Hybrid RAG</span><span className="pill subtle">{stats?.embedding_model || "BGE Embedding"}</span></div>
        </header>

        <div className="content-area">
          {notice && <div className="notice" onClick={() => setNotice("")}>{notice}</div>}
          {view === "dashboard" && <Dashboard stats={stats} health={health} docs={docs} onNavigate={setView} />}
          {view === "chat" && <ChatPanel />}
          {view === "knowledge" && <KnowledgePanel docs={docs} loading={loadingDocs} setLoading={setLoadingDocs} onChanged={refresh} setNotice={setNotice} />}
          {view === "retrieval" && <RetrievalPanel />}
          {view === "system" && <SystemPanel stats={stats} health={health} />}
        </div>
      </section>
    </main>
  );
}

function Dashboard({ stats, health, docs, onNavigate }: { stats: any; health: any; docs: DocumentItem[]; onNavigate: (view: View) => void }) {
  const cards = [
    ["知识库", "1", "默认企业知识库"],
    ["文档", String(stats?.total_documents ?? docs.length), "已完成索引"],
    ["Chunks", String(stats?.total_chunks ?? 0), "向量检索单元"],
    ["系统状态", health?.status === "healthy" ? "正常" : "待检查", health?.llm_model || "LLM"],
  ];
  return <>
    <section className="hero-card">
      <div><span className="eyebrow">NexusKB / Enterprise RAG</span><h2>让企业知识可检索、可引用、可验证</h2><p>通过中文语义向量、BM25 精确词检索与 Cross-Encoder 重排序，把制度、SOP 和产品资料转化为可追溯的 AI 问答能力。</p></div>
      <button className="primary" onClick={() => onNavigate("chat")}>开始提问</button>
    </section>
    <section className="metric-grid">{cards.map(([label, value, desc]) => <div className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{desc}</small></div>)}</section>
    <section className="two-col">
      <div className="panel"><div className="panel-head"><div><h3>检索链路</h3><p>当前 P0 技术路径</p></div></div><div className="pipeline"><b>Query</b><i>→</i><b>Vector + BM25</b><i>→</i><b>Hybrid</b><i>→</i><b>Rerank</b><i>→</i><b>LLM + Citation</b></div></div>
      <div className="panel"><div className="panel-head"><div><h3>最近文档</h3><p>企业知识资产</p></div><button className="link-btn" onClick={() => onNavigate("knowledge")}>管理文档</button></div>{docs.slice(0, 4).map((doc) => <div className="doc-row compact" key={doc.file_name}><div className="file-badge">{doc.file_type.toUpperCase()}</div><div><strong>{doc.file_name}</strong><span>{doc.chunk_count} chunks · {doc.file_size_kb} KB</span></div></div>)}{docs.length === 0 && <Empty text="上传 demo-data 中的资料开始演示" />}</div>
    </section>
  </>;
}

function ChatPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [running, setRunning] = useState(false);
  const [rerank, setRerank] = useState(false);
  const ask = async (value?: string) => {
    const q = (value ?? question).trim();
    if (!q || running) return;
    setQuestion(q); setAnswer(""); setSources([]); setRunning(true);
    try {
      await api.queryStream(q, rerank, { onSources: setSources, onToken: (text) => setAnswer((old) => old + text), onDone: () => setRunning(false) });
    } catch (error) { setAnswer(error instanceof Error ? error.message : "请求失败"); setRunning(false); }
  };
  return <section className="chat-layout">
    <div className="chat-main panel">
      <div className="chat-title"><div><span className="assistant-logo">AI</span><div><h3>企业知识助手</h3><p>仅依据知识库内容回答，关键事实附带来源</p></div></div><label className="switch-label"><input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />启用 Rerank</label></div>
      {!answer && !running && <div className="chat-empty"><span className="large-mark">N</span><h2>今天想查什么企业知识？</h2><p>可以查询制度、SOP、产品参数和内部规范。</p><div className="suggestions">{suggestions.map((item) => <button key={item} onClick={() => void ask(item)}>{item}</button>)}</div></div>}
      {(answer || running) && <div className="conversation"><div className="message user-message">{question}</div><div className="message ai-message">{answer || <span className="typing">正在检索企业知识…</span>}</div></div>}
      <div className="composer"><textarea value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(); } }} placeholder="输入问题，例如：退款超过 500 元需要谁审批？" /><button className="primary" disabled={running} onClick={() => void ask()}>{running ? "处理中" : "发送"}</button></div>
    </div>
    <aside className="source-panel panel"><div className="panel-head"><div><h3>引用来源</h3><p>{sources.length ? `${sources.length} 个相关 Chunk` : "回答依据将在这里展示"}</p></div></div>{sources.map((source, index) => <article className="source-card" key={`${source.file_name}-${index}`}><div className="source-number">{index + 1}</div><div><strong>{source.file_name}</strong><span>{source.page ? `第 ${source.page} 页 · ` : ""}匹配度 {source.relevance_score == null ? "—" : `${Math.round(source.relevance_score * 100)}%`}</span><p>{source.content_preview}</p></div></article>)}{sources.length === 0 && <Empty text="暂无引用" />}</aside>
  </section>;
}

function KnowledgePanel({ docs, loading, setLoading, onChanged, setNotice }: { docs: DocumentItem[]; loading: boolean; setLoading: (v: boolean) => void; onChanged: () => Promise<void>; setNotice: (v: string) => void }) {
  const upload = async (file?: File) => {
    if (!file) return; setLoading(true);
    try { const result = await api.upload(file); setNotice(`${result.file_name} 已入库，共 ${result.chunks_stored} 个 Chunk`); await onChanged(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "上传失败"); }
    finally { setLoading(false); }
  };
  const remove = async (name: string) => { if (!confirm(`确认删除 ${name}？`)) return; await api.deleteDocument(name); setNotice("文档已删除"); await onChanged(); };
  return <section className="panel knowledge-panel"><div className="panel-head"><div><h3>企业知识文档</h3><p>支持 PDF、DOCX、TXT、Markdown，单文件不超过 20MB</p></div><label className="primary file-button">{loading ? "处理中…" : "上传文档"}<input type="file" accept=".pdf,.docx,.txt,.md" disabled={loading} onChange={(e) => void upload(e.target.files?.[0])} /></label></div><div className="table-head"><span>文档</span><span>大小</span><span>Chunks</span><span>更新时间</span><span></span></div>{docs.map((doc) => <div className="doc-row" key={doc.file_name}><div className="doc-name"><div className="file-badge">{doc.file_type.toUpperCase()}</div><div><strong>{doc.file_name}</strong><span>索引状态：READY</span></div></div><span>{doc.file_size_kb} KB</span><span>{doc.chunk_count}</span><span>{new Date(doc.upload_date).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span><button className="danger-link" onClick={() => void remove(doc.file_name)}>删除</button></div>)}{docs.length === 0 && <Empty text="暂无文档。建议先上传 demo-data 下的 4 份企业资料。" />}</section>;
}

function RetrievalPanel() {
  const [query, setQuery] = useState(suggestions[0]);
  const [mode, setMode] = useState<"vector" | "bm25" | "hybrid">("hybrid");
  const [rerank, setRerank] = useState(false);
  const [rows, setRows] = useState<DebugResult[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const run = async () => { if (!query.trim()) return; setRunning(true); setError(""); try { const result = await api.debug(query, mode, rerank); setRows(result.results); } catch (e) { setError(e instanceof Error ? e.message : "检索失败"); } finally { setRunning(false); } };
  return <section className="retrieval-layout"><div className="panel debug-controls"><div className="panel-head"><div><h3>RAG 检索调试器</h3><p>直接观察不同检索策略的候选排序</p></div></div><label>Query<textarea value={query} onChange={(e) => setQuery(e.target.value)} /></label><label>Retrieval Mode<div className="segmented">{(["vector", "bm25", "hybrid"] as const).map((value) => <button key={value} className={mode === value ? "selected" : ""} onClick={() => setMode(value)}>{value === "vector" ? "Vector" : value === "bm25" ? "BM25" : "Hybrid"}</button>)}</div></label><label className="check-row"><input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />Cross-Encoder Rerank</label><button className="primary full" onClick={() => void run()} disabled={running}>{running ? "检索中…" : "运行检索"}</button>{error && <p className="error-text">{error}</p>}<div className="hint-box"><strong>为什么要 Hybrid？</strong><p>Vector 适合“出差住酒店能报多少”这类语义查询；BM25 更擅长产品型号、SOP 编号、精确金额和专有词。Hybrid 兼顾两者。</p></div></div><div className="panel debug-results"><div className="panel-head"><div><h3>检索结果</h3><p>{rows.length ? `Top ${rows.length} candidates` : "运行后显示分数"}</p></div></div>{rows.length > 0 && <div className="score-head"><span># / Source</span><span>Vector</span><span>BM25</span><span>Hybrid</span><span>Rerank</span></div>}{rows.map((row, index) => <article className="debug-row" key={`${row.file_name}-${index}`}><div><strong>{index + 1}. {row.file_name || "未知文档"}</strong><span>{row.page ? `第 ${row.page} 页` : "文本块"}</span><p>{row.content}</p></div><code>{score(row.vector_score)}</code><code>{score(row.bm25_score)}</code><code>{score(row.hybrid_score)}</code><code className={row.rerank_score != null ? "accent-code" : ""}>{score(row.rerank_score)}</code></article>)}{rows.length === 0 && <Empty text="输入 Query 后运行检索" />}</div></section>;
}

function SystemPanel({ stats, health }: { stats: any; health: any }) {
  const items = useMemo(() => [
    ["API 状态", health?.status || "unknown"],
    ["Vector DB", health?.vector_db_connected ? "Qdrant connected" : "Qdrant disconnected"],
    ["LLM Provider", health?.llm_provider || "—"],
    ["LLM Model", health?.llm_model || stats?.llm_model || "—"],
    ["Embedding", stats?.embedding_model || "BAAI/bge-small-zh-v1.5"],
    ["Vector Dimension", String(stats?.embedding_dimension || "—")],
    ["Collection", stats?.collection_name || "nexuskb"],
    ["Retrieval", "Vector + BM25 Hybrid"],
  ], [health, stats]);
  return <section className="panel system-panel"><div className="panel-head"><div><h3>运行环境</h3><p>用于演示系统依赖和模型配置</p></div><span className={health?.status === "healthy" ? "health-badge healthy" : "health-badge"}>{health?.status || "unknown"}</span></div><div className="system-grid">{items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="architecture"><h4>Request Trace</h4><div className="pipeline vertical"><b>User Query</b><i>↓</i><b>Embedding / Tokenize</b><i>↓</i><b>Qdrant + BM25</b><i>↓</i><b>Hybrid Fusion / Rerank</b><i>↓</i><b>Context → LLM → Citation</b></div></div></section>;
}

function Empty({ text }: { text: string }) { return <div className="empty"><span>∅</span><p>{text}</p></div>; }
