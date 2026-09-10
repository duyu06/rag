"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, KnowledgeBase, Source } from "@/lib/api";
import {
  activeConversationPreference,
  Conversation,
  ConversationMessage,
  ConversationSummary,
  conversationApi,
} from "@/lib/conversations";

const suggestions = [
  "广州普通员工出差住宿标准是多少？",
  "退款超过 500 元需要谁审批？",
  "X100 产品保修期多久？",
  "销售折扣超过多少需要主管审批？",
];

function compactTime(value: string) {
  try {
    return new Date(value).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function latestAssistant(messages: ConversationMessage[]) {
  return [...messages].reverse().find((item) => item.role === "assistant") || null;
}

export default function ConversationChatPanel({
  selectedKb,
  bases,
}: {
  selectedKb: string;
  bases: KnowledgeBase[];
}) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [rerank, setRerank] = useState(false);
  const [error, setError] = useState("");
  const [selectedMessageId, setSelectedMessageId] = useState("");
  const initialSelectedKb = useRef(selectedKb);

  const selectedName = selectedKb === "all"
    ? "全部可访问知识库"
    : bases.find((item) => item.id === selectedKb)?.name || selectedKb;

  const reloadList = useCallback(async () => {
    const rows = await conversationApi.list();
    setItems(rows);
    return rows;
  }, []);

  const openConversation = useCallback(async (id: string) => {
    const detail = await conversationApi.get(id);
    setConversation(detail);
    activeConversationPreference.set(detail.id);
    const last = latestAssistant(detail.messages);
    setSelectedMessageId(last?.id || "");
    return detail;
  }, []);

  const createConversation = useCallback(async () => {
    setError("");
    const created = await conversationApi.create(selectedKb);
    setConversation(created);
    activeConversationPreference.set(created.id);
    setSelectedMessageId("");
    setInput("");
    await reloadList();
    return created;
  }, [reloadList, selectedKb]);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const rows = await reloadList();
        if (cancelled) return;
        const preferred = activeConversationPreference.get();
        const candidate = rows.find((item) => item.id === preferred)?.id || rows[0]?.id;
        if (candidate) {
          await openConversation(candidate);
        } else {
          const created = await conversationApi.create(initialSelectedKb.current);
          if (cancelled) return;
          setConversation(created);
          activeConversationPreference.set(created.id);
          setSelectedMessageId("");
          await reloadList();
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "会话加载失败");
      }
    };
    void boot();
    return () => {
      cancelled = true;
    };
  }, [openConversation, reloadList]);

  const selectedSources: Source[] = useMemo(() => {
    if (!conversation) return [];
    const selected = conversation.messages.find((item) => item.id === selectedMessageId);
    if (selected?.role === "assistant") return selected.sources || [];
    return latestAssistant(conversation.messages)?.sources || [];
  }, [conversation, selectedMessageId]);

  const send = async (preset?: string) => {
    const question = (preset ?? input).trim();
    if (!question || running) return;
    setRunning(true);
    setError("");
    setInput("");

    let active = conversation;
    try {
      if (!active) active = await createConversation();
      const now = new Date().toISOString();
      const optimisticUser: ConversationMessage = {
        id: `pending-user-${Date.now()}`,
        conversation_id: active.id,
        role: "user",
        content: question,
        status: "completed",
        created_at: now,
        sources: [],
      };
      const optimisticAssistant: ConversationMessage = {
        id: `pending-assistant-${Date.now()}`,
        conversation_id: active.id,
        role: "assistant",
        content: "",
        status: "generating",
        created_at: now,
        sources: [],
      };
      setConversation({
        ...active,
        messages: [...active.messages, optimisticUser, optimisticAssistant],
      });
      setSelectedMessageId(optimisticAssistant.id);

      const result = await conversationApi.send(active.id, question, {
        knowledgeBaseId: selectedKb,
        rerank,
      });
      setConversation(result.conversation);
      const last = latestAssistant(result.conversation.messages);
      setSelectedMessageId(last?.id || "");
      await reloadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
      if (active?.id) {
        try {
          await openConversation(active.id);
          await reloadList();
        } catch {
          // Keep the original error visible.
        }
      }
    } finally {
      setRunning(false);
    }
  };

  const removeConversation = async (item: ConversationSummary) => {
    if (!confirm(`确认删除会话“${item.title}”？`)) return;
    setError("");
    try {
      await conversationApi.remove(item.id);
      const rows = await reloadList();
      if (conversation?.id === item.id) {
        const next = rows[0];
        if (next) await openConversation(next.id);
        else await createConversation();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除会话失败");
    }
  };

  const renameConversation = async (item: ConversationSummary) => {
    const value = prompt("会话名称", item.title)?.trim();
    if (!value || value === item.title) return;
    try {
      const updated = await conversationApi.rename(item.id, value);
      if (conversation?.id === item.id) setConversation(updated);
      await reloadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  };

  const openSource = async (source: Source) => {
    if (source.source_type === "web" && source.url) {
      window.open(source.url, "_blank", "noopener,noreferrer");
      return;
    }
    if (source.knowledge_base_id && source.file_name) {
      try {
        await api.openSource(source.knowledge_base_id, source.file_name);
      } catch (e) {
        setError(e instanceof Error ? e.message : "来源文件打开失败");
      }
    }
  };

  return (
    <section
      aria-label="持久化 AI 会话"
      style={{
        display: "grid",
        gridTemplateColumns: "230px minmax(0, 1fr) 310px",
        gap: 16,
        minHeight: "calc(100vh - 150px)",
      }}
    >
      <aside className="panel" style={{ padding: 12, overflow: "hidden" }}>
        <button className="primary full" onClick={() => void createConversation()} disabled={running}>
          ＋ 新建会话
        </button>
        <div style={{ marginTop: 12, display: "grid", gap: 7, maxHeight: "calc(100vh - 230px)", overflowY: "auto" }}>
          {items.map((item) => {
            const active = conversation?.id === item.id;
            return (
              <div
                key={item.id}
                style={{
                  border: active ? "1px solid #1570ef" : "1px solid #eaecf0",
                  borderRadius: 10,
                  background: active ? "#eff8ff" : "#fff",
                  padding: 9,
                }}
              >
                <button
                  type="button"
                  onClick={() => void openConversation(item.id)}
                  style={{ width: "100%", textAlign: "left", border: 0, background: "transparent", cursor: "pointer", padding: 0 }}
                >
                  <strong style={{ display: "block", color: "#101828", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</strong>
                  <span style={{ display: "block", marginTop: 4, color: "#667085", fontSize: 11 }}>{item.message_count} 条消息 · {compactTime(item.updated_at)}</span>
                </button>
                <div style={{ marginTop: 7, display: "flex", gap: 8 }}>
                  <button className="link-btn" onClick={() => void renameConversation(item)}>重命名</button>
                  <button className="danger-link" onClick={() => void removeConversation(item)}>删除</button>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      <div className="chat-main panel" style={{ minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div className="chat-title">
          <div>
            <span className="assistant-logo">AI</span>
            <div>
              <h3>{conversation?.title || "企业知识助手"}</h3>
              <p>检索范围：{selectedName} · 历史已持久化</p>
            </div>
          </div>
          <label className="switch-label">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />启用 Rerank
          </label>
        </div>

        {error && <div className="notice danger" style={{ margin: "8px 0" }}>{error}</div>}

        <div style={{ flex: 1, minHeight: 360, overflowY: "auto", padding: "8px 0 18px" }}>
          {!conversation?.messages.length && !running ? (
            <div className="chat-empty">
              <img className="large-mark" src="/yaoke-logo.webp" alt="yaoke" style={{ objectFit: "contain", background: "#fff" }} />
              <h2>今天想查什么企业知识？</h2>
              <p>当前会话会保存在服务端 SQLite，刷新或重新打开网页后仍可恢复。</p>
              <div className="suggestions">
                {suggestions.map((item) => <button key={item} onClick={() => void send(item)}>{item}</button>)}
              </div>
            </div>
          ) : (
            <div className="conversation" style={{ display: "grid", gap: 12 }}>
              {(conversation?.messages || []).map((message) => (
                <div
                  key={message.id}
                  className={message.role === "user" ? "message user-message" : "message ai-message"}
                  onClick={() => message.role === "assistant" && setSelectedMessageId(message.id)}
                  style={{
                    cursor: message.role === "assistant" ? "pointer" : "default",
                    outline: message.id === selectedMessageId ? "2px solid rgba(21,112,239,.18)" : "none",
                  }}
                >
                  {message.status === "generating" ? (
                    <span className="typing">正在执行权限过滤与知识检索…</span>
                  ) : (
                    message.content
                  )}
                  {message.status === "failed" && <small style={{ display: "block", marginTop: 7 }}>生成失败，可重新发送原问题。</small>}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="输入问题；Enter 发送，Shift+Enter 换行"
          />
          <button className="primary" disabled={running || !input.trim()} onClick={() => void send()}>
            {running ? "处理中" : "发送"}
          </button>
        </div>
      </div>

      <aside className="source-panel panel" style={{ minWidth: 0 }}>
        <div className="panel-head">
          <div>
            <h3>引用来源</h3>
            <p>{selectedSources.length ? `${selectedSources.length} 个证据来源` : "点击 AI 消息查看该条回答的依据"}</p>
          </div>
        </div>
        {selectedSources.map((source, index) => (
          <article
            className="source-card"
            key={`${source.citation_index || index}-${source.file_name}-${source.url || ""}`}
            onClick={() => void openSource(source)}
            style={{ cursor: source.url || source.knowledge_base_id ? "pointer" : "default" }}
          >
            <div className="source-number">{source.citation_index || index + 1}</div>
            <div>
              <strong>{source.title || source.file_name}</strong>
              <span className="kb-tag">
                {source.source_type === "web" ? `Web${source.domain ? ` · ${source.domain}` : ""}` : source.knowledge_base_name || "企业知识库"}
              </span>
              <span>
                {source.page ? `第 ${source.page} 页 · ` : ""}
                匹配度 {source.relevance_score == null ? "—" : `${Math.round(source.relevance_score * 100)}%`}
              </span>
              <p>{source.content_preview}</p>
            </div>
          </article>
        ))}
        {!selectedSources.length && <div className="empty-state"><span>◇</span><p>暂无引用</p></div>}
      </aside>
    </section>
  );
}
