import { AgentMode, agentModePreference, Source } from "@/lib/api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";
const TOKEN_KEY = "yaoke_access_token";
const ACTIVE_CONVERSATION_KEY = "yaoke_active_conversation";

export type ConversationSummary = {
  id: string;
  username: string;
  title: string;
  mode: AgentMode;
  knowledge_base_id?: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview?: string | null;
};

export type ConversationMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  status: "generating" | "completed" | "failed";
  trace_id?: string | null;
  latency_ms?: number | null;
  created_at: string;
  sources: Source[];
};

export type Conversation = Omit<ConversationSummary, "message_count" | "last_message_preview"> & {
  messages: ConversationMessage[];
};

function authHeaders(extra?: Record<string, string>) {
  const value = typeof window === "undefined" ? "" : localStorage.getItem(TOKEN_KEY) || "";
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

export const activeConversationPreference = {
  get() {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(ACTIVE_CONVERSATION_KEY) || "";
  },
  set(id: string) {
    if (typeof window === "undefined") return;
    if (id) localStorage.setItem(ACTIVE_CONVERSATION_KEY, id);
    else localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
  },
};

export const conversationApi = {
  async list(): Promise<ConversationSummary[]> {
    const response = await fetch(`${API_BASE_URL}/conversations`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "会话列表加载失败"));
    const data = await response.json();
    return data.conversations || [];
  },

  async create(knowledgeBaseId?: string | null): Promise<Conversation> {
    const response = await fetch(`${API_BASE_URL}/conversations`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        mode: agentModePreference.get(),
        knowledge_base_id: !knowledgeBaseId || knowledgeBaseId === "all" ? null : knowledgeBaseId,
      }),
    });
    if (!response.ok) throw new Error(await parseError(response, "新建会话失败"));
    return response.json();
  },

  async get(id: string): Promise<Conversation> {
    const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(id)}`, {
      headers: authHeaders(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await parseError(response, "会话加载失败"));
    return response.json();
  },

  async rename(id: string, title: string): Promise<Conversation> {
    const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ title }),
    });
    if (!response.ok) throw new Error(await parseError(response, "会话重命名失败"));
    return response.json();
  },

  async remove(id: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!response.ok) throw new Error(await parseError(response, "删除会话失败"));
  },

  async send(
    id: string,
    content: string,
    options: { knowledgeBaseId?: string | null; rerank?: boolean },
  ): Promise<{ conversation: Conversation; message: ConversationMessage; trace_id?: string | null }> {
    const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        content,
        mode: agentModePreference.get(),
        knowledge_base_id:
          !options.knowledgeBaseId || options.knowledgeBaseId === "all"
            ? null
            : options.knowledgeBaseId,
        top_k: 5,
        rerank: Boolean(options.rerank),
      }),
    });
    if (!response.ok) throw new Error(await parseError(response, "会话问答失败"));
    const data = await response.json();
    if (data.trace_id) agentModePreference.saveTraceId(String(data.trace_id));
    return data;
  },
};
