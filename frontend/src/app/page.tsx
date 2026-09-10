"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ConversationChatPanel from "@/components/ConversationChatPanel";
import {
  api,
  DebugResult,
  DocumentItem,
  KnowledgeBase,
  session,
  User,
} from "@/lib/api";

type View = "dashboard" | "chat" | "knowledge" | "retrieval" | "evaluation" | "system";

const baseNav: Array<{ key: View; label: string; short: string }> = [
  { key: "dashboard", label: "工作台", short: "总" },
  { key: "chat", label: "AI 知识助手", short: "问" },
  { key: "knowledge", label: "知识库", short: "库" },
  { key: "retrieval", label: "检索测试", short: "检" },
  { key: "evaluation", label: "RAG 评测", short: "评" },
  { key: "system", label: "系统状态", short: "态" },
];

const suggestions = [
  "广州普通员工出差住宿标准是多少？",
  "退款超过 500 元需要谁审批？",
  "X100 产品保修期多久？",
  "销售折扣超过多少需要主管审批？",
];

const roleName: Record<User["role"], string> = {
  ADMIN: "管理员",
  SALES: "销售",
  HR: "HR",
};

function score(value?: number | null) {
  return value == null ? "—" : value.toFixed(3);
}

function BrandLogo({ large = false }: { large?: boolean }) {
  return (
    <img
      className={large ? "brand-mark large" : "brand-mark"}
      src="/yaoke-logo.webp"
      alt="yaoke"
      style={{ objectFit: "contain", background: "#fff" }}
    />
  );
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [view, setView] = useState<View>("dashboard");
  const [health, setHealth] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedKb, setSelectedKb] = useState("all");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(
    async (kb = selectedKb) => {
      if (!user) return;
      const [healthResult, statsResult, docsResult, basesResult] = await Promise.allSettled([
        api.health(),
        api.stats(kb),
        api.documents(kb),
        api.knowledgeBases(),
      ]);
      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      if (statsResult.status === "fulfilled") setStats(statsResult.value);
      if (docsResult.status === "fulfilled") setDocs(docsResult.value.documents);
      if (basesResult.status === "fulfilled") setBases(basesResult.value);
    },
    [selectedKb, user],
  );

  useEffect(() => {
    const boot = async () => {
      if (!session.hasToken()) {
        setBooting(false);
        return;
      }
      try {
        const current = await api.me();
        setUser(current);
      } catch {
        session.clear();
      } finally {
        setBooting(false);
      }
    };
    void boot();
  }, []);

  useEffect(() => {
    if (user) void refresh();
  }, [user, selectedKb, refresh]);

  const nav = useMemo(
    () => baseNav.filter((item) => item.key !== "evaluation" || user?.role === "ADMIN"),
    [user],
  );

  if (booting) {
    return <div className="boot-screen"><BrandLogo large /><p>正在加载 yaoke…</p></div>;
  }

  if (!user) {
    return <LoginScreen onLogin={setUser} />;
  }

  const logout = () => {
    session.clear();
    setUser(null);
    setDocs([]);
    setBases([]);
    setStats(null);
    setView("dashboard");
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <BrandLogo />
          <div><strong>yaoke</strong><span>企业 AI 知识中台</span></div>
        </div>

        <nav className="nav-list">
          {nav.map((item) => (
            <button
              key={item.key}
              className={view === item.key ? "nav-item active" : "nav-item"}
              onClick={() => setView(item.key)}
            >
              <span className="nav-icon">{item.short}</span>{item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="status-line">
            <i className={health?.status === "healthy" ? "dot ok" : "dot"} />
            {health?.status === "healthy" ? "服务运行正常" : "服务待检查"}
          </div>
          <div className="user-card">
            <div className="avatar">{user.display_name.slice(0, 1)}</div>
            <div><strong>{user.display_name}</strong><span>{roleName[user.role]} · {user.username}</span></div>
            <button className="logout-btn" onClick={logout}>退出</button>
          </div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div>
            <h1>{nav.find((item) => item.key === view)?.label || "yaoke"}</h1>
            <p>Enterprise RAG · Tool Calling Agent</p>
          </div>
          <div className="top-actions">
            <label className="kb-filter">
              <span>知识域</span>
              <select value={selectedKb} onChange={(e) => setSelectedKb(e.target.value)}>
                <option value="all">全部可访问知识库</option>
                {bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}
              </select>
            </label>
            <span className="role-pill">{roleName[user.role]}</span>
          </div>
        </header>

        <div className="content-area">
          {notice && <div className="notice" onClick={() => setNotice("")}>{notice}</div>}

          {view === "dashboard" && (
            <Dashboard
              stats={stats}
              health={health}
              docs={docs}
              bases={bases}
              user={user}
              onNavigate={setView}
            />
          )}
          <div hidden={view !== "chat"}>
            <ConversationChatPanel selectedKb={selectedKb} bases={bases} />
          </div>
          {view === "knowledge" && (
            <KnowledgePanel
              docs={docs}
              bases={bases}
              user={user}
              selectedKb={selectedKb}
              onChanged={() => refresh(selectedKb)}
              setNotice={setNotice}
            />
          )}
          {view === "retrieval" && <RetrievalPanel selectedKb={selectedKb} />}
          {view === "evaluation" && user.role === "ADMIN" && <EvaluationPanel />}
          {view === "system" && <SystemPanel stats={stats} health={health} user={user} bases={bases} />}
        </div>
      </section>
    </main>
  );
}

function LoginScreen({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const accounts = [
    { role: "管理员", username: "admin", password: "admin123", access: "全部知识库 / 文档管理 / RAG 评测" },
    { role: "销售", username: "sales01", password: "sales123", access: "公共 / 产品 / 销售 / 售后" },
    { role: "HR", username: "hr01", password: "hr123", access: "公共 / HR" },
  ];

  const submit = async () => {
    setRunning(true);
    setError("");
    try {
      const result = await api.login(username, password);
      onLogin(result.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-intro">
        <div className="brand login-brand"><BrandLogo /><div><strong>yaoke</strong><span>Enterprise Knowledge Copilot</span></div></div>
        <div className="login-copy">
          <span className="eyebrow">ENTERPRISE RAG / RBAC</span>
          <h1>企业知识，按权限被准确检索。</h1>
          <p>多知识库隔离、JWT 身份鉴别、检索前 ACL 过滤、Hybrid Search、Rerank 与 Citation，组成一套可解释的企业知识问答链路。</p>
          <div className="feature-strip">
            <span>Multi-KB</span><span>JWT / RBAC</span><span>Hybrid Retrieval</span><span>Evaluation</span>
          </div>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-title"><span className="assistant-logo">AI</span><div><h2>登录演示工作区</h2><p>切换不同角色验证知识库隔离</p></div></div>
          <label>用户名<input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label>密码<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void submit(); }} /></label>
          {error && <p className="error-text">{error}</p>}
          <button className="primary full" disabled={running} onClick={() => void submit()}>{running ? "登录中…" : "登录 yaoke"}</button>

          <div className="demo-accounts">
            <div className="section-label">演示账号</div>
            {accounts.map((account) => (
              <button
                key={account.username}
                className="demo-account"
                onClick={() => { setUsername(account.username); setPassword(account.password); setError(""); }}
              >
                <div><strong>{account.role}</strong><span>{account.username} / {account.password}</span></div>
                <small>{account.access}</small>
              </button>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

function Dashboard({
  stats,
  health,
  docs,
  bases,
  user,
  onNavigate,
}: {
  stats: any;
  health: any;
  docs: DocumentItem[];
  bases: KnowledgeBase[];
  user: User;
  onNavigate: (view: View) => void;
}) {
  const cards = [
    ["可访问知识库", String(stats?.knowledge_bases ?? bases.length), roleName[user.role] + " 权限域"],
    ["文档", String(stats?.total_documents ?? docs.length), "已完成索引"],
    ["Chunks", String(stats?.total_chunks ?? 0), "权限过滤后的检索单元"],
    ["系统状态", health?.status === "healthy" ? "正常" : "待检查", health?.llm_model || "LLM"],
  ];

  return (
    <>
      <section className="hero-card">
        <div>
          <span className="eyebrow">yaoke / Enterprise RAG P1.5</span>
          <h2>把“能问答”升级为“有权限边界的企业知识系统”</h2>
          <p>当前用户的角色会在检索前转换为 Qdrant metadata filter；无权限 Chunk 不会进入 Vector、BM25 或 LLM Context。</p>
        </div>
        <button className="primary" onClick={() => onNavigate("chat")}>开始提问</button>
      </section>

      <section className="metric-grid">
        {cards.map(([label, value, desc]) => <div className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{desc}</small></div>)}
      </section>

      <section className="two-col">
        <div className="panel">
          <div className="panel-head"><div><h3>企业检索链路</h3><p>ACL 在 Retrieval 前生效</p></div></div>
          <div className="pipeline">
            <b>JWT</b><i>→</i><b>Role ACL</b><i>→</i><b>Qdrant Filter</b><i>→</i><b>Vector + BM25</b><i>→</i><b>Rerank</b><i>→</i><b>LLM + Citation</b>
          </div>
          <div className="security-note">
            <strong>权限原则</strong>
            <p>不是“搜全库后让 Prompt 决定能不能说”，而是从候选集生成阶段就排除无权限知识。</p>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><div><h3>可访问知识域</h3><p>{roleName[user.role]} 当前权限</p></div><button className="link-btn" onClick={() => onNavigate("knowledge")}>管理知识</button></div>
          <div className="kb-mini-grid">
            {bases.map((base) => <div className="kb-mini" key={base.id}><span>{base.department}</span><strong>{base.name}</strong><p>{base.description}</p></div>)}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div><h3>最近文档</h3><p>仅展示当前账号有权访问的数据</p></div></div>
        {docs.slice(0, 5).map((doc) => (
          <div className="doc-row compact" key={`${doc.knowledge_base_id}-${doc.file_name}`}>
            <div className="file-badge">{doc.file_type.toUpperCase()}</div>
            <div className="grow"><strong>{doc.file_name}</strong><span>{doc.knowledge_base_name} · {doc.chunk_count} chunks · {doc.file_size_kb} KB</span></div>
          </div>
        ))}
        {docs.length === 0 && <Empty text="管理员可在知识库页面上传 demo-data 中的资料" />}
      </section>
    </>
  );
}

function KnowledgePanel({
  docs,
  bases,
  user,
  selectedKb,
  onChanged,
  setNotice,
}: {
  docs: DocumentItem[];
  bases: KnowledgeBase[];
  user: User;
  selectedKb: string;
  onChanged: () => Promise<void>;
  setNotice: (v: string) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [targetKb, setTargetKb] = useState(bases[0]?.id || "kb_public");

  useEffect(() => {
    if (selectedKb !== "all") setTargetKb(selectedKb);
    else if (!bases.find((item) => item.id === targetKb) && bases[0]) setTargetKb(bases[0].id);
  }, [selectedKb, bases, targetKb]);

  const upload = async (file?: File) => {
    if (!file || user.role !== "ADMIN") return;
    setUploading(true);
    try {
      const result = await api.upload(file, targetKb);
      setNotice(`${result.file_name} 已写入 ${result.knowledge_base_name}，共 ${result.chunks_stored} 个 Chunk`);
      await onChanged();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const remove = async (doc: DocumentItem) => {
    if (user.role !== "ADMIN") return;
    if (!confirm(`确认从 ${doc.knowledge_base_name} 删除 ${doc.file_name}？`)) return;
    try {
      await api.deleteDocument(doc.file_name, doc.knowledge_base_id);
      setNotice("文档已删除");
      await onChanged();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除失败");
    }
  };

  return (
    <>
      <section className="kb-grid">
        {bases.map((base) => {
          const count = docs.filter((doc) => doc.knowledge_base_id === base.id).length;
          return <article className="kb-card" key={base.id}><div className="kb-card-top"><span>{base.department}</span><b>{count} docs</b></div><h3>{base.name}</h3><p>{base.description}</p><code>{base.id}</code></article>;
        })}
      </section>

      <section className="panel knowledge-panel">
        <div className="panel-head">
          <div><h3>企业知识文档</h3><p>{user.role === "ADMIN" ? "管理员可上传与删除；其他角色为只读权限" : "当前角色仅可查看授权知识库"}</p></div>
          {user.role === "ADMIN" && (
            <div className="upload-actions">
              <select value={targetKb} onChange={(e) => setTargetKb(e.target.value)}>
                {bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}
              </select>
              <label className="primary file-button">
                {uploading ? "处理中…" : "上传文档"}
                <input type="file" accept=".pdf,.docx,.txt,.md" disabled={uploading} onChange={(e) => void upload(e.target.files?.[0])} />
              </label>
            </div>
          )}
        </div>

        <div className="demo-map">
          <strong>Demo 数据映射：</strong>
          <span>差旅制度 → 公共制度</span>
          <span>退款 SOP → 售后知识库</span>
          <span>X100 → 产品知识库</span>
          <span>销售折扣 → 销售知识库</span><span>HR员工手册 → HR 知识库</span>
        </div>

        <div className="table-head"><span>文档</span><span>知识库</span><span>大小</span><span>Chunks</span><span>更新时间</span><span></span></div>
        {docs.map((doc) => (
          <div className="doc-row" key={`${doc.knowledge_base_id}-${doc.file_name}`}>
            <div className="doc-name"><div className="file-badge">{doc.file_type.toUpperCase()}</div><div><strong>{doc.file_name}</strong><span>索引状态：READY</span></div></div>
            <span><b className="kb-name-cell">{doc.knowledge_base_name}</b></span>
            <span>{doc.file_size_kb} KB</span>
            <span>{doc.chunk_count}</span>
            <span>{new Date(doc.upload_date).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
            {user.role === "ADMIN" ? <button className="danger-link" onClick={() => void remove(doc)}>删除</button> : <span className="readonly">只读</span>}
          </div>
        ))}
        {docs.length === 0 && <Empty text="当前权限范围内暂无文档。" />}
      </section>
    </>
  );
}

function RetrievalPanel({ selectedKb }: { selectedKb: string }) {
  const [query, setQuery] = useState(suggestions[0]);
  const [mode, setMode] = useState<"vector" | "bm25" | "hybrid">("hybrid");
  const [rerank, setRerank] = useState(false);
  const [rows, setRows] = useState<DebugResult[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    if (!query.trim()) return;
    setRunning(true);
    setError("");
    try {
      const result = await api.debug(query, mode, rerank, selectedKb);
      setRows(result.results);
    } catch (e) {
      setError(e instanceof Error ? e.message : "检索失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="retrieval-layout">
      <div className="panel debug-controls">
        <div className="panel-head"><div><h3>RAG 检索调试器</h3><p>观察 ACL 过滤后的候选排序</p></div></div>
        <label>Query<textarea value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <label>Retrieval Mode
          <div className="segmented">
            {(["vector", "bm25", "hybrid"] as const).map((value) => (
              <button key={value} className={mode === value ? "selected" : ""} onClick={() => setMode(value)}>
                {value === "vector" ? "Vector" : value === "bm25" ? "BM25" : "Hybrid"}
              </button>
            ))}
          </div>
        </label>
        <label className="check-row"><input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />Cross-Encoder Rerank</label>
        <button className="primary full" onClick={() => void run()} disabled={running}>{running ? "检索中…" : "运行检索"}</button>
        {error && <p className="error-text">{error}</p>}
        <div className="hint-box"><strong>ACL 在哪里生效？</strong><p>JWT Role → Allowed KB IDs → Qdrant metadata filter。BM25 corpus 同样只由授权 Chunk 构建，因此无权限资料不会参与任何评分。</p></div>
      </div>

      <div className="panel debug-results">
        <div className="panel-head"><div><h3>检索结果</h3><p>{rows.length ? `Top ${rows.length} authorized candidates` : "运行后显示分数"}</p></div></div>
        {rows.length > 0 && <div className="score-head"><span># / Source</span><span>Vector</span><span>BM25</span><span>Hybrid</span><span>Rerank</span></div>}
        {rows.map((row, index) => (
          <article className="debug-row" key={`${row.file_name}-${index}`}>
            <div><strong>{index + 1}. {row.file_name || "未知文档"}</strong><span>{row.knowledge_base_name || "知识库"} · {row.page ? `第 ${row.page} 页` : "文本块"}</span><p>{row.content}</p></div>
            <code>{score(row.vector_score)}</code><code>{score(row.bm25_score)}</code><code>{score(row.hybrid_score)}</code><code className={row.rerank_score != null ? "accent-code" : ""}>{score(row.rerank_score)}</code>
          </article>
        ))}
        {rows.length === 0 && <Empty text="输入 Query 后运行检索，观察不同策略的排序差异。" />}
      </div>
    </section>
  );
}

function EvaluationPanel() {
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setRunning(true);
    setError("");
    try {
      setResult(await api.runEvaluation());
    } catch (e) {
      setError(e instanceof Error ? e.message : "评测失败");
    } finally {
      setRunning(false);
    }
  };

  const vector = result?.report?.vector;
  const bm25 = result?.report?.bm25;
  const hybrid = result?.report?.hybrid;
  const hybridRerank = result?.report?.hybrid_rerank;

  return (
    <>
      <section className="hero-card evaluation-hero">
        <div><span className="eyebrow">OFFLINE RETRIEVAL EVALUATION</span><h2>30 题 · 四路 RAG 检索评测</h2><p>固定企业知识 QA 集实时对比 Vector、BM25、Hybrid 与 Hybrid + Rerank 的 Hit@1、Hit@3 和 MRR。结果来自当前 Qdrant 数据，不使用预置或伪造指标。</p></div>
        <button className="primary" disabled={running} onClick={() => void run()}>{running ? "评测中…" : "运行四路评测"}</button>
      </section>

      {error && <div className="notice danger">{error}</div>}

      <section className="eval-grid">
        <EvalCard title="Vector Search" data={vector} />
        <EvalCard title="BM25 Search" data={bm25} />
        <EvalCard title="Hybrid Search" data={hybrid} />
        <EvalCard title="Hybrid + Rerank" data={hybridRerank} />
      </section>

      <section className="panel">
        <div className="panel-head"><div><h3>逐题结果 · Hybrid + Rerank</h3><p>{result ? `${result.dataset_size} questions · Top ${result.top_k}` : "运行评测后展示命中与错误案例"}</p></div></div>
        {!result && <Empty text="请先使用管理员 Demo 工具初始化 20 份演示资料，然后运行评测。" />}
        {result && (hybridRerank?.cases || []).map((item: any, index: number) => (
          <div className="eval-case" key={index}>
            <span className={item.rank ? "case-status pass" : "case-status fail"}>{item.rank ? `#${item.rank}` : "MISS"}</span>
            <div><strong>{item.question}</strong><span>Expected: {item.expected_file}</span><small>Top: {(item.top_files || []).join(" / ") || "无结果"}</small></div>
          </div>
        ))}
      </section>
    </>
  );
}

function EvalCard({ title, data }: { title: string; data: any }) {
  return (
    <div className="panel eval-card">
      <div className="panel-head"><div><h3>{title}</h3><p>{data ? `${data.total} questions · ${Math.round(data.elapsed_ms || 0)} ms` : "等待评测"}</p></div></div>
      <div className="eval-metrics">
        <div><span>Hit@1</span><strong>{data ? `${Math.round(data.hit_at_1 * 100)}%` : "—"}</strong></div>
        <div><span>Hit@3</span><strong>{data ? `${Math.round((data.hit_at_3 || 0) * 100)}%` : "—"}</strong></div>
        <div><span>MRR</span><strong>{data ? data.mrr.toFixed(3) : "—"}</strong></div>
      </div>
    </div>
  );
}

function SystemPanel({ stats, health, user, bases }: { stats: any; health: any; user: User; bases: KnowledgeBase[] }) {
  const rows = [
    ["API", health?.status || "unknown"],
    ["Vector Database", health?.vector_db_connected ? "Qdrant connected" : "disconnected"],
    ["LLM Provider", health?.llm_provider || "—"],
    ["LLM Model", health?.llm_model || stats?.llm_model || "—"],
    ["Embedding", stats?.embedding_model || "BAAI/bge-small-zh-v1.5"],
    ["Embedding Dimension", String(stats?.embedding_dimension ?? "—")],
    ["Authentication", "JWT HS256"],
    ["Current Role", `${roleName[user.role]} (${user.role})`],
    ["Accessible KBs", String(bases.length)],
  ];

  return (
    <section className="two-col system-grid">
      <div className="panel">
        <div className="panel-head"><div><h3>运行状态</h3><p>依赖与模型信息</p></div></div>
        {rows.map(([key, value]) => <div className="system-row" key={key}><span>{key}</span><strong>{value}</strong></div>)}
      </div>
      <div className="panel">
        <div className="panel-head"><div><h3>权限矩阵</h3><p>Demo RBAC</p></div></div>
        <div className="permission-table">
          <div className="permission-head"><span>Role</span><span>Public</span><span>HR</span><span>Product</span><span>Sales</span><span>Service</span></div>
          <PermissionRow role="ADMIN" values={[1, 1, 1, 1, 1]} active={user.role === "ADMIN"} />
          <PermissionRow role="SALES" values={[1, 0, 1, 1, 1]} active={user.role === "SALES"} />
          <PermissionRow role="HR" values={[1, 1, 0, 0, 0]} active={user.role === "HR"} />
        </div>
        <div className="security-note"><strong>生产替换点</strong><p>Demo 使用本地 JWT 用户表；实际企业环境应把 auth.py 替换为企业微信 / 飞书 / OIDC / SAML 身份源，检索 ACL 接口保持不变。</p></div>
      </div>
    </section>
  );
}

function PermissionRow({ role, values, active }: { role: string; values: number[]; active: boolean }) {
  return <div className={active ? "permission-row current" : "permission-row"}><strong>{role}</strong>{values.map((value, index) => <span key={index}>{value ? "✓" : "—"}</span>)}</div>;
}

function Empty({ text }: { text: string }) {
  return <div className="empty-state"><span>◇</span><p>{text}</p></div>;
}
