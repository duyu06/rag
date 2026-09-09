const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";

export type Source = {
  file_name: string;
  page?: number | null;
  content_preview: string;
  relevance_score?: number | null;
};

export type DocumentItem = {
  file_name: string;
  file_type: string;
  file_size_kb: number;
  upload_date: string;
  chunk_count: number;
};

export type DebugResult = {
  file_name?: string;
  page?: number | null;
  content: string;
  vector_score: number;
  bm25_score: number;
  hybrid_score: number;
  rerank_score?: number | null;
};

export const api = {
  async health() {
    const response = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!response.ok) throw new Error("健康检查失败");
    return response.json();
  },

  async stats() {
    const response = await fetch(`${API_BASE_URL}/stats`, { cache: "no-store" });
    if (!response.ok) throw new Error("统计数据加载失败");
    return response.json();
  },

  async documents(): Promise<{ documents: DocumentItem[]; total_documents: number; total_chunks: number }> {
    const response = await fetch(`${API_BASE_URL}/documents`, { cache: "no-store" });
    if (!response.ok) throw new Error("文档列表加载失败");
    return response.json();
  },

  async upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE_URL}/ingest`, { method: "POST", body: form });
    if (!response.ok) throw new Error((await response.json()).detail || "上传失败");
    return response.json();
  },

  async deleteDocument(fileName: string) {
    const response = await fetch(`${API_BASE_URL}/documents/${encodeURIComponent(fileName)}`, { method: "DELETE" });
    if (!response.ok) throw new Error("删除失败");
    return response.json();
  },

  async debug(query: string, mode: "vector" | "bm25" | "hybrid", rerank: boolean) {
    const response = await fetch(`${API_BASE_URL}/retrieval/debug`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, mode, top_k: 8, rerank }),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "检索失败");
    return response.json() as Promise<{ results: DebugResult[] }>;
  },

  async queryStream(
    question: string,
    rerank: boolean,
    handlers: { onSources: (sources: Source[]) => void; onToken: (text: string) => void; onDone: () => void },
  ) {
    const response = await fetch(`${API_BASE_URL}/query/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, k: 5, include_sources: true, use_hybrid_search: true, use_reranking: rerank }),
    });
    if (!response.ok || !response.body) throw new Error("问答请求失败");

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
};
