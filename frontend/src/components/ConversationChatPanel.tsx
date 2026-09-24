"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, KnowledgeBase, Source } from "@/lib/api";
import AgentModeToggle from "@/components/AgentModeToggle";
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
  canWrite,
  canUseAgent,
}: {
  selectedKb: string;
  bases: KnowledgeBase[];
  canWrite: boolean;
  canUseAgent: boolean;
}) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [rerank, setRerank] = useState(false);
  const [error, setError] = useState("");
  const [selectedMessageId, setSelectedMessageId] = useState("");
  const [initialLoading, setInitialLoading] = useState(true);
  const [phase, setPhase] = useState<"idle" | "connecting" | "retrieving" | "generating" | "finalizing">("idle");
  const [phaseMessage, setPhaseMessage] = useState("");
  const initialSelectedKb = useRef(selectedKb);

  const applyServerStatus = useCallback((serverPhase: string, message: string) => {
    if (serverPhase === "retrieving") setPhase("retrieving");
    else if (serverPhase === "generating") setPhase("generating");
    else setPhase("connecting");
    setPhaseMessage(message);
  }, []);

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
    if (!canWrite) throw new Error("当前账号只有会话只读权限");
    setError("");
    const created = await conversationApi.create(selectedKb);
    setConversation(created);
    activeConversationPreference.set(created.id);
    setSelectedMessageId("");
    setInput("");
    await reloadList();
    return created;
  }, [canWrite, reloadList, selectedKb]);

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
        } else if (canWrite) {
          const created = await conversationApi.create(initialSelectedKb.current);
          if (cancelled) return;
          setConversation(created);
          activeConversationPreference.set(created.id);
          setSelectedMessageId("");
          await reloadList();
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "会话加载失败");
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    };
    void boot();
    return () => {
      cancelled = true;
    };
  }, [canWrite, openConversation, reloadList]);

  const selectedSources: Source[] = useMemo(() => {
    if (!conversation) return [];
    const selected = conversation.messages.find((item) => item.id === selectedMessageId);
    if (selected?.role === "assistant") return selected.sources || [];
    return latestAssistant(conversation.messages)?.sources || [];
  }, [conversation, selectedMessageId]);

  const send = async (preset?: string) => {
    const question = (preset ?? input).trim();
    if (!question || running || !canWrite) return;
    setRunning(true);
    setPhase("connecting");
    setPhaseMessage("正在建立安全连接");
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
      const optimisticAssistantId = optimisticAssistant.id;
      setConversation({
        ...active,
        messages: [...active.messages, optimisticUser, optimisticAssistant],
      });
      setSelectedMessageId(optimisticAssistant.id);
      setPhase("retrieving");
      setPhaseMessage("正在等待授权检索");

      const result = await conversationApi.sendStream(
        active.id,
        question,
        {
          knowledgeBaseId: selectedKb,
          rerank,
        },
        {
          onStatus: applyServerStatus,
          onToken: (text) => {
            setPhase("generating");
            setPhaseMessage("已找到依据，正在组织回答");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === optimisticAssistantId
                  ? { ...item, content: item.content + text }
                  : item,
              ),
            } : current);
          },
          onSources: (sources) => {
            setPhase("generating");
            setPhaseMessage("已找到依据，正在组织回答");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === optimisticAssistantId ? { ...item, sources } : item,
              ),
            } : current);
          },
        },
      );
      setPhase("finalizing");
      setPhaseMessage("正在保存回答与引用");
      setConversation(result.conversation);
      setSelectedMessageId(result.message.id);
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
      setPhase("idle");
      setPhaseMessage("");
    }
  };

  const retryMessage = async (message: ConversationMessage) => {
    if (!conversation || running || message.role !== "assistant" || message.status !== "failed") return;
    const active = conversation;
    setRunning(true);
    setPhase("retrieving");
    setPhaseMessage("正在重新检索授权知识");
    setError("");
    setSelectedMessageId(message.id);
    setConversation({
      ...active,
      messages: active.messages.map((item) =>
        item.id === message.id
          ? { ...item, status: "generating", content: "", sources: [] }
          : item,
      ),
    });

    try {
      const result = await conversationApi.retryStream(
        active.id,
        message.id,
        {
          knowledgeBaseId: selectedKb,
          rerank,
        },
        {
          onStatus: applyServerStatus,
          onToken: (text) => {
            setPhase("generating");
            setPhaseMessage("已找到依据，正在组织回答");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === message.id ? { ...item, content: item.content + text } : item,
              ),
            } : current);
          },
          onSources: (sources) => {
            setPhase("generating");
            setPhaseMessage("已找到依据，正在组织回答");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === message.id ? { ...item, sources } : item,
              ),
            } : current);
          },
        },
      );
      setPhase("finalizing");
      setPhaseMessage("正在保存回答与引用");
      setConversation(result.conversation);
      setSelectedMessageId(result.message.id);
      await reloadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重试失败");
      try {
        await openConversation(active.id);
        await reloadList();
      } catch {
        // Keep the original retry error visible.
      }
    } finally {
      setRunning(false);
      setPhase("idle");
      setPhaseMessage("");
    }
  };

  const removeConversation = async (item: ConversationSummary) => {
    if (!confirm(`确认删除会话“${item.title}”？`)) return;
    setError("");
    setItems((current) => current.filter((row) => row.id !== item.id));
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
      await reloadList().catch(() => undefined);
    }
  };

  const renameConversation = async (item: ConversationSummary) => {
    const value = prompt("会话名称", item.title)?.trim();
    if (!value || value === item.title) return;
    setItems((current) => current.map((row) => row.id === item.id ? { ...row, title: value } : row));
    try {
      const updated = await conversationApi.rename(item.id, value);
      if (conversation?.id === item.id) setConversation(updated);
      await reloadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
      await reloadList().catch(() => undefined);
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
    <section className="conversation-shell" aria-label="持久化 AI 会话">
      <aside className="conversation-history panel">
        {canWrite && <button className="primary full" onClick={() => void createConversation()} disabled={running}>
          ＋ 新建会话
        </button>}
        <div className="conversation-history-list">
          {initialLoading && [0, 1, 2].map((item) => <div className="skeleton conversation-skeleton" key={item} />)}
          {items.map((item) => {
            const active = conversation?.id === item.id;
            return (
              <div key={item.id} className={active ? "conversation-history-item active" : "conversation-history-item"}>
                <button
                  type="button"
                  className="conversation-history-open"
                  onClick={() => void openConversation(item.id)}
                >
                  <strong>{item.title}</strong>
                  <span>{item.message_count} 条消息 · {compactTime(item.updated_at)}</span>
                </button>
                <div className="conversation-history-actions">
                  {canWrite && <button className="link-btn" onClick={() => void renameConversation(item)}>重命名</button>}
                  {canWrite && <button className="danger-link" onClick={() => void removeConversation(item)}>删除</button>}
                </div>
              </div>
            );
          })}
          {!initialLoading && items.length === 0 && <p className="history-empty">暂无可查看的会话</p>}
        </div>
      </aside>

      <div className="conversation-chat-main chat-main panel">
        <div className="chat-title">
          <div>
            <span className="assistant-logo">AI</span>
            <div>
              <h3>{conversation?.title || "企业知识助手"}</h3>
              <p>检索范围：{selectedName} · 历史已持久化 · 本地模式支持原生流式输出</p>
            </div>
          </div>
          <div className="chat-controls">
            {canUseAgent && <AgentModeToggle embedded />}
            <label className="switch-label">
              <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} disabled={!canWrite} />启用重排序
            </label>
          </div>
        </div>

        {error && <div className="notice danger conversation-error" role="alert"><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="关闭错误">×</button></div>}
        {running && <div className="generation-status" role="status" aria-live="polite"><i />{phaseMessage || (phase === "connecting" ? "正在建立安全连接" : phase === "retrieving" ? "正在执行权限过滤与知识检索" : phase === "generating" ? "已找到依据，正在组织回答" : "正在保存回答与引用")}</div>}

        <div className="conversation-message-list">
          {initialLoading ? (
            <div className="chat-loading" aria-label="正在恢复会话"><div className="skeleton message-skeleton short" /><div className="skeleton message-skeleton" /><div className="skeleton message-skeleton short" /></div>
          ) : !conversation?.messages.length && !running ? (
            <div className="chat-empty">
              <span className="large-mark" aria-hidden="true">Y</span>
              <h2>{canWrite ? "今天想查什么企业知识？" : "暂无可查看的会话"}</h2>
              <p>{canWrite ? "回答只会使用当前账号有权访问的知识，并附上可核验来源。" : "当前账号只有读取权限，已有会话会显示在左侧。"}</p>
              {canWrite && <div className="suggestions">
                {suggestions.map((item) => <button key={item} onClick={() => void send(item)}>{item}</button>)}
              </div>}
            </div>
          ) : (
            <div className="conversation persistent-conversation">
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
                  {message.status === "generating"
                    ? (message.content || <span className="typing">正在执行权限过滤与知识检索…</span>)
                    : message.content}
                  {message.status === "failed" && (
                    <div className="conversation-retry">
                      <small>本条回答生成失败。</small>
                      <button
                        type="button"
                        className="link-btn"
                        disabled={running}
                        onClick={(event) => {
                          event.stopPropagation();
                          void retryMessage(message);
                        }}
                      >
                        重试
                      </button>
                    </div>
                  )}
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
            placeholder={canWrite ? "输入问题；Enter 发送，Shift+Enter 换行" : "当前账号只有会话只读权限"}
            disabled={!canWrite}
            aria-label="向企业知识助手提问"
          />
          <button className="primary" disabled={!canWrite || running || !input.trim()} onClick={() => void send()}>
            {running ? "生成中" : "发送"}
          </button>
        </div>
      </div>

      <aside className="conversation-sources source-panel panel">
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
                {source.source_type === "web" ? `网页${source.domain ? ` · ${source.domain}` : ""}` : source.knowledge_base_name || "企业知识库"}
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
