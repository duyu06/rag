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

export type ConversationTurnResponse = {
  conversation: Conversation;
  message: ConversationMessage;
  trace_id?: string | null;
  model_used?: string | null;
  context_messages?: number;
  timings?: Record<string, unknown> | null;
};

export type ConversationStreamHandlers = {
  onMessage?: (messageId: string) => void;
  onToken?: (text: string) => void;
  onSources?: (sources: Source[]) => void;
  onTrace?: (traceId: string) => void;
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

function normalizeKnowledgeBaseId(value?: string | null) {
  return !value || value === "all" ? null : value;
}

async function parseTurnResponse(response: Response, fallback: string): Promise<ConversationTurnResponse> {
  if (!response.ok) throw new Error(await parseError(response, fallback));
  const data = await response.json();
  if (data.trace_id) agentModePreference.saveTraceId(String(data.trace_id));
  return data;
}

async function parseTurnStream(
  response: Response,
  fallback: string,
  handlers: ConversationStreamHandlers,
): Promise<ConversationTurnResponse> {
  if (!response.ok || !response.body) {
    throw new Error(await parseError(response, fallback));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: ConversationTurnResponse | null = null;
  let streamError = "";

  const consumeFrame = (frame: string) => {
    const lines = frame.split("\n");
    const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
    const raw = lines.find((line) => line.startsWith("data:"))?.slice(5).trim();
    if (!event || !raw) return;
    const data = JSON.parse(raw);

    if (event === "message" && data.message_id) {
      handlers.onMessage?.(String(data.message_id));
    } else if (event === "token") {
      handlers.onToken?.(String(data.text || ""));
    } else if (event === "sources") {
      handlers.onSources?.(data.sources || []);
    } else if (event === "trace" && data.trace_id) {
      const traceId = String(data.trace_id);
      agentModePreference.saveTraceId(traceId);
      handlers.onTrace?.(traceId);
    } else if (event === "error") {
      streamError = String(data.detail || fallback);
    } else if (event === "done") {
      completed = data as ConversationTurnResponse;
      if (data.trace_id) agentModePreference.saveTraceId(String(data.trace_id));
    }
  };

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
  if (!completed) throw new Error("流式连接提前结束，回答未完成持久化");
  return completed;
}

function turnBody(content: string | null, options: { knowledgeBaseId?: string | null; rerank?: boolean }) {
  return JSON.stringify({
    ...(content == null ? {} : { content }),
    mode: agentModePreference.get(),
    knowledge_base_id: normalizeKnowledgeBaseId(options.knowledgeBaseId),
    top_k: 5,
    rerank: Boolean(options.rerank),
  });
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
        knowledge_base_id: normalizeKnowledgeBaseId(knowledgeBaseId),
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
  ): Promise<ConversationTurnResponse> {
    const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: turnBody(content, options),
    });
    return parseTurnResponse(response, "会话问答失败");
  },

  async sendStream(
    id: string,
    content: string,
    options: { knowledgeBaseId?: string | null; rerank?: boolean },
    handlers: ConversationStreamHandlers = {},
  ): Promise<ConversationTurnResponse> {
    const response = await fetch(`${API_BASE_URL}/conversations/${encodeURIComponent(id)}/messages/stream`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: turnBody(content, options),
    });
    return parseTurnStream(response, "会话流式问答失败", handlers);
  },

  async retry(
    conversationId: string,
    messageId: string,
    options: { knowledgeBaseId?: string | null; rerank?: boolean },
  ): Promise<ConversationTurnResponse> {
    const response = await fetch(
      `${API_BASE_URL}/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/retry`,
      {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: turnBody(null, options),
      },
    );
    return parseTurnResponse(response, "重试失败");
  },

  async retryStream(
    conversationId: string,
    messageId: string,
    options: { knowledgeBaseId?: string | null; rerank?: boolean },
    handlers: ConversationStreamHandlers = {},
  ): Promise<ConversationTurnResponse> {
    const response = await fetch(
      `${API_BASE_URL}/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/retry/stream`,
      {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: turnBody(null, options),
      },
    );
    return parseTurnStream(response, "流式重试失败", handlers);
  },
};
