const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";
const TOKEN_KEY = "yaoke_access_token";
const AGENT_MODE_KEY = "yaoke_agent_mode";
const LAST_TRACE_KEY = "yaoke_last_agent_trace";
const AGENT_MODE_EVENT = "yaoke-agent-mode";

export type AgentMode = "local" | "auto" | "web";

export type User = {
  username: string;
  display_name: string;
  role: "ADMIN" | "SALES" | "HR" | "USER" | "VIEWER";
  access_role?: "admin" | "user" | "viewer";
  permissions?: string[];
  capabilities?: string[] | Record<string, boolean>;
};

export type Permission =
  | "knowledge:read"
  | "knowledge:query"
  | "knowledge:manage"
  | "conversation:read"
  | "conversation:write"
  | "agent:run"
  | "trace:read"
  | "trace:read:any"
  | "retrieval:debug"
  | "evaluation:run"
  | "audit:read"
  | "system:operate";

const LEGACY_ROLE_PERMISSIONS: Record<User["role"], Permission[]> = {
  ADMIN: [
    "knowledge:read", "knowledge:query", "knowledge:manage", "conversation:read",
    "conversation:write", "agent:run", "trace:read", "trace:read:any", "retrieval:debug", "evaluation:run", "audit:read", "system:operate",
  ],
  SALES: ["knowledge:read", "knowledge:query", "conversation:read", "conversation:write", "agent:run", "trace:read"],
  HR: ["knowledge:read", "knowledge:query", "conversation:read", "conversation:write", "agent:run", "trace:read"],
  USER: ["knowledge:read", "knowledge:query", "conversation:read", "conversation:write", "agent:run", "trace:read"],
  VIEWER: ["knowledge:read", "conversation:read", "trace:read"],
};

function normalizePermission(value: string) {
  return value.trim().toLowerCase().replace(/[._/\s-]+/g, ":");
}

export function userPermissions(user: User): Set<string> {
  const explicit = Array.isArray(user.permissions);
  const capabilityList = Array.isArray(user.capabilities)
    ? user.capabilities
    : user.capabilities && typeof user.capabilities === "object"
      ? Object.entries(user.capabilities).filter(([, enabled]) => enabled).map(([name]) => name)
      : [];
  const hasCapabilityField = user.capabilities != null;
  const values = [...(user.permissions || []), ...capabilityList].map(normalizePermission);

  // Older deployments only expose role. Once either capability field exists,
  // the backend response is authoritative, including an intentionally empty list.
  if (!explicit && !hasCapabilityField) {
    return new Set((LEGACY_ROLE_PERMISSIONS[user.role] || []).map(normalizePermission));
  }
  return new Set(values);
}

export function hasPermission(user: User | null | undefined, permission: Permission) {
  if (!user) return false;
  return userPermissions(user).has(normalizePermission(permission));
}

export function hasAnyPermission(user: User | null | undefined, permissions: Permission[]) {
  return permissions.some((permission) => hasPermission(user, permission));
}

export function accessRoleName(user: User) {
  if (user.access_role === "admin") return "管理员";
  if (user.access_role === "viewer") return "访客";
  if (user.access_role === "user") return "普通用户";
  return user.role === "ADMIN" ? "管理员" : user.role === "SALES" ? "销售" : user.role === "HR" ? "人事" : user.role === "VIEWER" ? "访客" : "普通用户";
}

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  department: string;
};

export type Source = {
  citation_index?: number | null;
  source_type?: "enterprise" | "web";
  title?: string | null;
  file_name: string;
  page?: number | null;
  content_preview: string;
  relevance_score?: number | null;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  url?: string | null;
  domain?: string | null;
};

export type DocumentItem = {
  file_name: string;
  file_type: string;
  file_size_kb: number;
  upload_date: string;
  chunk_count: number;
  knowledge_base_id: string;
  knowledge_base_name: string;
  status?: string | null;
  enabled?: boolean;
  archived?: boolean;
  owner?: string | null;
  department?: string | null;
  updated_at?: string | null;
  last_error?: string | null;
};

export type DebugResult = {
  file_name?: string;
  page?: number | null;
  content: string;
  knowledge_base_id?: string;
  knowledge_base_name?: string;
  vector_score: number;
  bm25_score: number;
  hybrid_score: number;
  rerank_score?: number | null;
};

export type AuditEvent = {
  timestamp: string;
  username: string;
  role: string;
  action: string;
  status: string;
  knowledge_base_id?: string;
  query?: string;
  latency_ms?: number;
  num_sources?: number;
  detail?: string;
};

export type AgentTraceEvent = {
  type: string;
  timestamp?: string;
  round?: number;
  mode?: AgentMode;
  tool?: string;
  tools?: string[];
  status?: string;
  latency_ms?: number;
  result_count?: number;
  arguments?: Record<string, unknown>;
  question_preview?: string;
  answer_preview?: string;
  max_tool_rounds?: number;
};

export type AgentTrace = {
  trace_id: string;
  timestamp: string;
  username: string;
  role: string;
  mode: AgentMode;
  model: string;
  max_tool_rounds: number;
  evidence_count: number;
  elapsed_ms: number;
  events: AgentTraceEvent[];
};

function token() {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) || "";
}

function authHeaders(extra?: Record<string, string>) {
  const value = token();
  return {
    ...(value ? { Authorization: `Bearer ${value}` } : {}),
    ...(extra || {}),
  };
}

async function parseError(response: Response, fallback: string) {
  try {
    const data = await response.json();
    return data.detail || fallback;
  } catch {
    return fallback;
  }
}

function querySuffix(knowledgeBaseId?: string | null) {
  if (!knowledgeBaseId || knowledgeBaseId === "all") return "";
  return `?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`;
}

function emitAuthChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("yaoke-auth"));
}

export const session = {
  hasToken() {
    return Boolean(token());
  },
  save(accessToken: string) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    emitAuthChanged();
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    emitAuthChanged();
  },
};

export const agentModePreference = {
  get(): AgentMode {
    if (typeof window === "undefined") return "auto";
    const value = localStorage.getItem(AGENT_MODE_KEY);
    return value === "local" || value === "web" || value === "auto" ? value : "auto";
  },
  set(mode: AgentMode) {
    localStorage.setItem(AGENT_MODE_KEY, mode);
    window.dispatchEvent(new Event(AGENT_MODE_EVENT));
  },
  event: AGENT_MODE_EVENT,
  lastTraceId() {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(LAST_TRACE_KEY) || "";
  },
  saveTraceId(traceId: string) {
    if (typeof window === "undefined" || !traceId) return;
    localStorage.setItem(LAST_TRACE_KEY, traceId);
    window.dispatchEvent(new Event("yaoke-agent-trace"));
  },
};

export const api = {
  async login(username: string, password: string): Promise<{ access_token: string; user: User }> {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) throw new Error(await parseError(response, "登录失败"));
    const data = await response.json();
    session.save(data.access_token);
    return data;
  },

  async me(): Promise<User> {
    const response = await fetch(`${API_BASE_URL}/auth/me`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "登录已失效"));
    return response.json();
  },

  async knowledgeBases(): Promise<KnowledgeBase[]> {
    const response = await fetch(`${API_BASE_URL}/knowledge-bases`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "知识库加载失败"));
    const data = await response.json();
    return data.knowledge_bases || [];
  },

  async health() {
    const response = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!response.ok) throw new Error("健康检查失败");
    return response.json();
  },

  async stats(knowledgeBaseId?: string | null) {
    const response = await fetch(`${API_BASE_URL}/stats${querySuffix(knowledgeBaseId)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "统计数据加载失败"));
    return response.json();
  },

  async audit(limit = 20): Promise<{ events: AuditEvent[]; summary: Record<string, number> }> {
    const response = await fetch(`${API_BASE_URL}/audit?limit=${limit}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "审计日志加载失败"));
    return response.json();
  },

  async agentTools(mode: AgentMode = agentModePreference.get()) {
    const response = await fetch(`${API_BASE_URL}/tools?mode=${encodeURIComponent(mode)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "Agent 工具列表加载失败"));
    return response.json();
  },

  async agentTrace(traceId?: string): Promise<AgentTrace> {
    const id = traceId || agentModePreference.lastTraceId();
    if (!id) throw new Error("暂无 Agent Trace");
    const response = await fetch(`${API_BASE_URL}/agent/traces/${encodeURIComponent(id)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "Agent Trace 加载失败"));
    return response.json();
  },

  async documents(knowledgeBaseId?: string | null): Promise<{
    documents: DocumentItem[];
    total_documents: number;
    total_chunks: number;
  }> {
    const response = await fetch(`${API_BASE_URL}/documents${querySuffix(knowledgeBaseId)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "文档列表加载失败"));
    return response.json();
  },

  async upload(file: File, knowledgeBaseId: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("knowledge_base_id", knowledgeBaseId);
    const response = await fetch(`${API_BASE_URL}/ingest`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    if (!response.ok) throw new Error(await parseError(response, "上传失败"));
    return response.json();
  },

  async deleteDocument(fileName: string, knowledgeBaseId: string) {
    const response = await fetch(
      `${API_BASE_URL}/documents/${encodeURIComponent(fileName)}?knowledge_base_id=${encodeURIComponent(knowledgeBaseId)}`,
      { method: "DELETE", headers: authHeaders() },
    );
    if (!response.ok) throw new Error(await parseError(response, "删除失败"));
    return response.json();
  },

  async openSource(knowledgeBaseId: string, fileName: string) {
    const response = await fetch(
      `${API_BASE_URL}/source/${encodeURIComponent(knowledgeBaseId)}/${encodeURIComponent(fileName)}`,
      { headers: authHeaders() },
    );
    if (!response.ok) throw new Error(await parseError(response, "来源文件打开失败"));
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },

  async demoStatus() {
    const response = await fetch(`${API_BASE_URL}/demo/status`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "Demo 状态读取失败"));
    return response.json();
  },

  async initializeDemo() {
    const response = await fetch(`${API_BASE_URL}/demo/initialize`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: "{}",
    });
    if (!response.ok) throw new Error(await parseError(response, "Demo 初始化失败"));
    return response.json();
  },

  async resetDemo() {
    const response = await fetch(`${API_BASE_URL}/demo/reset`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: "{}",
    });
    if (!response.ok) throw new Error(await parseError(response, "Demo 重置失败"));
    return response.json();
  },

  async debug(
    query: string,
    mode: "vector" | "bm25" | "hybrid",
    rerank: boolean,
    knowledgeBaseId?: string | null,
  ) {
    const response = await fetch(`${API_BASE_URL}/retrieval/debug`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        query,
        mode,
        top_k: 8,
        rerank,
        knowledge_base_id: knowledgeBaseId === "all" ? null : knowledgeBaseId,
      }),
    });
    if (!response.ok) throw new Error(await parseError(response, "检索失败"));
    return response.json() as Promise<{ results: DebugResult[] }>;
  },

  async queryStream(
    question: string,
    rerank: boolean,
    knowledgeBaseId: string | null,
    handlers: {
      onSources: (sources: Source[]) => void;
      onToken: (text: string) => void;
      onDone: () => void;
      onTrace?: (traceId: string) => void;
      onStatus?: (phase: string, message: string) => void;
    },
  ) {
    const response = await fetch(`${API_BASE_URL}/agent/query/stream`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        question,
        mode: agentModePreference.get(),
        knowledge_base_id: knowledgeBaseId === "all" ? null : knowledgeBaseId,
        top_k: 5,
        rerank,
      }),
    });
    if (!response.ok || !response.body) {
      throw new Error(await parseError(response, "Agent 问答请求失败"));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let doneSignaled = false;
    let streamError = "";

    const consumeFrame = (frame: string) => {
      const lines = frame.split("\n");
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const raw = lines.find((line) => line.startsWith("data:"))?.slice(5).trim();
      if (!raw) return;
      const data = JSON.parse(raw);
      if (event === "trace" && data.trace_id) {
        agentModePreference.saveTraceId(String(data.trace_id));
        handlers.onTrace?.(String(data.trace_id));
      }
      if (event === "status") handlers.onStatus?.(String(data.phase || "working"), String(data.message || "正在处理"));
      if (event === "sources") handlers.onSources(data.sources || []);
      if (event === "token") handlers.onToken(String(data.text || ""));
      if (event === "error") streamError = String(data.detail || "Agent 问答失败");
      if (event === "done" && !doneSignaled) {
        doneSignaled = true;
        handlers.onDone();
      }
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";
        for (const frame of frames) consumeFrame(frame);
      }
      buffer += decoder.decode();
      if (buffer.trim()) consumeFrame(buffer);
      if (streamError) throw new Error(streamError);
    } finally {
      // A proxy/network interruption can close SSE without a final done frame.
      // Always release the UI busy state exactly once.
      if (!doneSignaled) handlers.onDone();
    }
  },

  async runEvaluation() {
    const response = await fetch(`${API_BASE_URL}/evaluation/run`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        modes: ["vector", "bm25", "hybrid", "hybrid_rerank"],
        top_k: 3,
      }),
    });
    if (!response.ok) throw new Error(await parseError(response, "评测失败"));
    return response.json();
  },

  /* ---------- Knowledge OS extensions ---------- */

  async search(query: string, knowledgeBaseId?: string | null): Promise<{ results: SearchResult[]; took_ms: number }> {
    const response = await fetch(`${API_BASE_URL}/search`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ query, top_k: 20, knowledge_base_id: knowledgeBaseId === "all" ? null : knowledgeBaseId || null }),
    });
    if (!response.ok) throw new Error(await parseError(response, "搜索失败"));
    return response.json();
  },

  async chunks(params: { knowledgeBaseId?: string | null; fileName?: string | null; limit?: number; offset?: number }): Promise<{ chunks: ChunkItem[]; total: number }> {
    const search = new URLSearchParams();
    if (params.knowledgeBaseId && params.knowledgeBaseId !== "all") search.set("knowledge_base_id", params.knowledgeBaseId);
    if (params.fileName) search.set("file_name", params.fileName);
    search.set("limit", String(params.limit ?? 50));
    search.set("offset", String(params.offset ?? 0));
    const response = await fetch(`${API_BASE_URL}/chunks?${search.toString()}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "Chunk 列表加载失败"));
    return response.json();
  },

  async documentAction(
    action: "reindex" | "enable" | "disable" | "archive" | "restore" | "move",
    payload: { file_name: string; knowledge_base_id: string; target_knowledge_base_id?: string },
  ) {
    const response = await fetch(`${API_BASE_URL}/documents/${action}`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseError(response, "文档操作失败"));
    return response.json();
  },

  async ingestionJobs(limit = 20): Promise<{ jobs: IngestionJob[] }> {
    const response = await fetch(`${API_BASE_URL}/ingestion/jobs?limit=${limit}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "摄取任务加载失败"));
    return response.json();
  },

  async feedback(payload: { conversation_id?: string; message_id?: string; question: string; verdict: "up" | "down"; category?: string; detail?: string }) {
    const response = await fetch(`${API_BASE_URL}/feedback`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseError(response, "反馈提交失败"));
    return response.json();
  },

  async feedbackList(limit = 50): Promise<{ items: FeedbackItem[] }> {
    const response = await fetch(`${API_BASE_URL}/feedback?limit=${limit}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "反馈列表加载失败"));
    return response.json();
  },

  async usage(): Promise<UsageSummary> {
    const response = await fetch(`${API_BASE_URL}/operations/usage`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "使用统计加载失败"));
    return response.json();
  },

  async systemStatus(): Promise<SystemStatus> {
    const response = await fetch(`${API_BASE_URL}/system/status`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "系统状态加载失败"));
    return response.json();
  },

  async users(): Promise<{ users: UserRow[] }> {
    const response = await fetch(`${API_BASE_URL}/auth/users`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "成员列表加载失败"));
    return response.json();
  },

  async requestAccess(payload: { resource: string; policy: string; reason: string }) {
    const response = await fetch(`${API_BASE_URL}/access/requests`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseError(response, "权限申请失败"));
    return response.json();
  },

  async evalRuns(limit = 10): Promise<{ runs: EvalRun[] }> {
    const response = await fetch(`${API_BASE_URL}/evaluation/runs?limit=${limit}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "评测历史加载失败"));
    return response.json();
  },

  async evalRun(runId: string): Promise<EvalRun> {
    const response = await fetch(`${API_BASE_URL}/evaluation/runs/${encodeURIComponent(runId)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "评测记录加载失败"));
    return response.json();
  },

  async evalFailures(): Promise<{ cases: FailureCase[] }> {
    const response = await fetch(`${API_BASE_URL}/evaluation/failures`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "失败案例加载失败"));
    return response.json();
  },

  async patchEvalFailure(caseId: string, payload: Partial<Pick<FailureCase, "failure_type" | "root_cause" | "action" | "regression">>) {
    const response = await fetch(`${API_BASE_URL}/evaluation/failures/${encodeURIComponent(caseId)}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await parseError(response, "失败案例更新失败"));
    return response.json();
  },
};

export type SearchResult = {
  file_name: string;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  page?: number | null;
  section?: string | null;
  content: string;
  score?: number | null;
  file_type?: string | null;
  department?: string | null;
  updated_at?: string | null;
};

export type ChunkItem = {
  id: string;
  file_name: string;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  page?: number | null;
  section?: string | null;
  chunk_index?: number | null;
  content: string;
  tokens?: number | null;
  uploaded_at?: string | null;
};

export type IngestionStage = {
  name: string;
  status: string;
  detail?: string | null;
  error?: string | null;
  elapsed_ms?: number | null;
};

export type IngestionJob = {
  job_id: string;
  file_name: string;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  status: string;
  total_elapsed_ms?: number | null;
  created_at: string;
  stages: IngestionStage[];
};

export type FeedbackItem = {
  id: string;
  username: string;
  question: string;
  verdict: "up" | "down";
  category?: string | null;
  detail?: string | null;
  created_at: string;
};

export type UsageSummary = {
  active_users: number;
  total_users: number;
  queries_30d: number;
  adoption_pct: number;
  top_department?: { name: string; queries: number } | null;
  queries_today?: number;
  avg_latency_ms?: number | null;
};

// 判定层（TypeSafe）滚动聚合：与后端 `app/security.py::PUBLIC_TYPESAFE_STATS_KEYS` 同集合。
// 整块可选：旧后端不返回 `typesafe` 时前端显示"未启用"，不得因此崩。
export type TypesafeStats = {
  mode?: string | null;
  sample_count?: number | null;
  trigger_rate?: number | null;
  skip_rate?: number | null;
  cache_hit_ratio?: number | null;
  requests_per_query_p50?: number | null;
  requests_per_query_p95?: number | null;
  input_tokens_per_query_p50?: number | null;
  cost_per_query_p50?: number | null;
  timeout_rate?: number | null;
  degraded_rate?: number | null;
  slow_rate?: number | null;
  latency_p50_ms?: number | null;
  latency_p95_ms?: number | null;
  breaker_state?: string | null;
};

export type SystemStatus = {
  overall: string;
  llm: { status: string; model: string; provider: string; p50_ms?: number | null; p95_ms?: number | null; ttft_ms?: number | null };
  embedding: { status: string; model: string; dimension?: number | null };
  bm25: { status: string };
  reranker: { status: string; model?: string | null };
  vector_db: { status: string; collection?: string | null };
  index: { documents: number; chunks: number; failed_jobs: number; last_sync_at?: string | null };
  typesafe?: TypesafeStats | null;
};

export type UserRow = {
  username: string;
  display_name: string;
  role: string;
  department?: string | null;
  status?: string | null;
  last_login?: string | null;
};

export type EvalCaseResult = {
  case_id: string;
  question: string;
  expected_file: string;
  tag?: string | null;
  rank?: number | null;
  top_files?: string[];
  passed: boolean;
  failure_type?: string | null;
  root_cause?: string | null;
  action?: string | null;
  regression?: boolean | null;
};

export type EvalRun = {
  run_id: string;
  name: string;
  created_at: string;
  dataset_size: number;
  modes: Record<string, { hit_at_1: number; hit_at_3: number; mrr: number; total: number; grounded_pct?: number | null; elapsed_ms?: number | null }>;
  cases: Record<string, EvalCaseResult[]>;
};

export type FailureCase = EvalCaseResult & { run_id: string; actual_rank?: number | null };
