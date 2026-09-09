const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";
const TOKEN_KEY = "nexuskb_access_token";

export type User = {
  username: string;
  display_name: string;
  role: "ADMIN" | "SALES" | "HR";
};

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  department: string;
};

export type Source = {
  file_name: string;
  page?: number | null;
  content_preview: string;
  relevance_score?: number | null;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
};

export type DocumentItem = {
  file_name: string;
  file_type: string;
  file_size_kb: number;
  upload_date: string;
  chunk_count: number;
  knowledge_base_id: string;
  knowledge_base_name: string;
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
  if (typeof window !== "undefined") window.dispatchEvent(new Event("nexuskb-auth"));
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
    },
  ) {
    const response = await fetch(`${API_BASE_URL}/query/stream`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        question,
        k: 5,
        include_sources: true,
        use_hybrid_search: true,
        use_reranking: rerank,
        knowledge_base_id: knowledgeBaseId === "all" ? null : knowledgeBaseId,
      }),
    });
    if (!response.ok || !response.body) {
      throw new Error(await parseError(response, "问答请求失败"));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const lines = frame.split("\n");
        const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
        const raw = lines.find((line) => line.startsWith("data:"))?.slice(5).trim();
        if (!raw) continue;
        const data = JSON.parse(raw);
        if (event === "sources") handlers.onSources(data.sources || []);
        if (event === "token") handlers.onToken(String(data.text || ""));
        if (event === "done") handlers.onDone();
      }
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
};
