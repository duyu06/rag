"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, hasPermission, Source, User } from "@/lib/api";
import {
  Conversation,
  ConversationMessage,
  ConversationSummary,
  conversationApi,
  activeConversationPreference,
} from "@/lib/conversations";
import {
  EmptyState,
  ErrorState,
  Kicker,
  Kv,
  MetricStrip,
  Modal,
  PageHeader,
  PipelineStep,
  SkeletonRows,
  Status,
  StepState,
  fmtMs,
  fmtScore,
  fmtTime,
  highlight,
} from "@/components/ui";
import { evidenceQuality, findConflicts, QualityLevel, SourceConflict } from "@/lib/evidence";
import { ViewPayload, ViewProps } from "@/lib/nav";

/* 展示用流水线名称：与后端 phase（"retrieving" / "generating"）无关，
   流水线进度按数组下标推进，因此这里可以直接中文化。 */
const PIPELINE_STEPS = [
  "查询改写",
  "向量检索",
  "关键词检索（BM25）",
  "重排序",
  "生成回答",
];

/* 证据质量：level 是枚举（驱动 CSS 类名），label 仅用于展示。 */
const QUALITY_LABELS: Record<QualityLevel, string> = {
  strong: "证据充分",
  moderate: "证据有限",
  review: "需人工核对",
};

const suggestions = [
  "广州出差住宿标准是什么？",
  "退款超过 500 元需要谁审批？",
  "X100 产品保修期多久？",
];

function latestAssistant(messages: ConversationMessage[]) {
  return [...messages].reverse().find((item) => item.role === "assistant") || null;
}

function pairTurns(messages: ConversationMessage[]) {
  const turns: { user?: ConversationMessage; assistant?: ConversationMessage }[] = [];
  for (const message of messages) {
    if (message.role === "user") turns.push({ user: message });
    else if (message.role === "assistant") {
      const last = turns[turns.length - 1];
      if (last && !last.assistant) last.assistant = message;
      else turns.push({ assistant: message });
    }
  }
  return turns;
}

export default function AskView({ user, bases, selectedKb, navigate, payload }: ViewProps) {
  const canAsk = hasPermission(user, "conversation:write") && hasPermission(user, "agent:run") && hasPermission(user, "knowledge:query");
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [rerank, setRerank] = useState(false);
  const [error, setError] = useState("");
  const [steps, setSteps] = useState<StepState[] | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState("");
  const [focusedSource, setFocusedSource] = useState<number | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [feedbackModal, setFeedbackModal] = useState<ConversationMessage | null>(null);
  const [feedbackCategory, setFeedbackCategory] = useState("answer");
  const [feedbackDetail, setFeedbackDetail] = useState("");
  const [feedbackSent, setFeedbackSent] = useState<Record<string, string>>({});
  const [lastTraceId, setLastTraceId] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const reloadList = useCallback(async () => {
    const rows = await conversationApi.list().catch(() => [] as ConversationSummary[]);
    setItems(rows);
    return rows;
  }, []);

  const openConversation = useCallback(async (id: string) => {
    const detail = await conversationApi.get(id);
    setConversation(detail);
    activeConversationPreference.set(detail.id);
    setSelectedMessageId(latestAssistant(detail.messages)?.id || "");
    return detail;
  }, []);

  const createConversation = useCallback(async () => {
    const created = await conversationApi.create(selectedKb);
    setConversation(created);
    activeConversationPreference.set(created.id);
    setSelectedMessageId("");
    await reloadList();
    return created;
  }, [reloadList, selectedKb]);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const rows = await reloadList();
        if (cancelled) return;
        const wanted = (payload as ViewPayload | undefined)?.conversationId
          || activeConversationPreference.get();
        const candidate = rows.find((item) => item.id === wanted)?.id || rows[0]?.id;
        if (candidate) await openConversation(candidate);
        else if (canAsk) {
          const created = await conversationApi.create(selectedKb);
          if (cancelled) return;
          setConversation(created);
          activeConversationPreference.set(created.id);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "会话加载失败");
      } finally {
        if (!cancelled) setInitialLoading(false);
      }
    };
    void boot();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-ask when arriving from Home with a query
  const autoAsked = useRef("");
  useEffect(() => {
    const q = payload?.query;
    if (q && conversation && autoAsked.current !== q + conversation.id) {
      autoAsked.current = q + conversation.id;
      void send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation, payload?.query]);

  const advance = useCallback((index: number, state: StepState) => {
    setSteps((current) => {
      const next = (current || PIPELINE_STEPS.map(() => "waiting" as StepState)).slice() as StepState[];
      next[index] = state;
      return next;
    });
  }, []);

  const startPipeline = useCallback(() => {
    setSteps(PIPELINE_STEPS.map((_, index) => (index === 0 ? "running" : "waiting")));
  }, []);

  const send = async (preset?: string) => {
    const question = (preset ?? input).trim();
    if (!question || running || !canAsk) return;
    setRunning(true);
    setError("");
    setInput("");
    startPipeline();

    let active = conversation;
    try {
      if (!active) active = await createConversation();
      const now = new Date().toISOString();
      const optimisticUser: ConversationMessage = {
        id: `pending-user-${Date.now()}`, conversation_id: active.id, role: "user",
        content: question, status: "completed", created_at: now, sources: [],
      };
      const optimisticAssistant: ConversationMessage = {
        id: `pending-assistant-${Date.now()}`, conversation_id: active.id, role: "assistant",
        content: "", status: "generating", created_at: now, sources: [],
      };
      const pendingId = optimisticAssistant.id;
      setConversation({ ...active, messages: [...active.messages, optimisticUser, optimisticAssistant] });
      setSelectedMessageId(pendingId);
      advance(0, "done");
      advance(1, "running");
      advance(2, "running");

      const result = await conversationApi.sendStream(active.id, question,
        { knowledgeBaseId: selectedKb, rerank },
        {
          onStatus: (phase) => {
            if (phase === "retrieving") { advance(0, "done"); advance(1, "running"); advance(2, "running"); }
            if (phase === "generating") { advance(1, "done"); advance(2, "done"); advance(3, rerank ? "running" : "done"); advance(4, "running"); }
          },
          onToken: (text) => {
            advance(1, "done"); advance(2, "done"); advance(3, "done"); advance(4, "running");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === pendingId ? { ...item, content: item.content + text } : item),
            } : current);
          },
          onSources: (sources) => {
            advance(1, "done"); advance(2, "done"); advance(3, "done");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === pendingId ? { ...item, sources } : item),
            } : current);
          },
          onTrace: (traceId) => setLastTraceId(traceId),
        },
      );
      setSteps(PIPELINE_STEPS.map(() => "done"));
      setConversation(result.conversation);
      setSelectedMessageId(result.message.id);
      if (result.trace_id) setLastTraceId(String(result.trace_id));
      await reloadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
      setSteps((current) => {
        const next = (current || PIPELINE_STEPS.map(() => "waiting")).slice() as StepState[];
        const firstRunning = next.indexOf("running");
        if (firstRunning >= 0) next[firstRunning] = "failed";
        return next;
      });
      if (active?.id) await openConversation(active.id).catch(() => undefined);
    } finally {
      setRunning(false);
      window.setTimeout(() => setSteps(null), 900);
      textareaRef.current?.focus();
    }
  };

  const retryMessage = async (message: ConversationMessage) => {
    if (!conversation || running || message.status !== "failed") return;
    const active = conversation;
    setRunning(true);
    startPipeline();
    setSelectedMessageId(message.id);
    setConversation({
      ...active,
      messages: active.messages.map((item) =>
        item.id === message.id ? { ...item, status: "generating", content: "", sources: [] } : item),
    });
    try {
      const result = await conversationApi.retryStream(active.id, message.id,
        { knowledgeBaseId: selectedKb, rerank },
        {
          onToken: (text) => {
            advance(4, "running");
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === message.id ? { ...item, content: item.content + text } : item),
            } : current);
          },
          onSources: (sources) => {
            setConversation((current) => current ? {
              ...current,
              messages: current.messages.map((item) =>
                item.id === message.id ? { ...item, sources } : item),
            } : current);
          },
          onTrace: (traceId) => setLastTraceId(traceId),
        },
      );
      setSteps(PIPELINE_STEPS.map(() => "done"));
      setConversation(result.conversation);
      setSelectedMessageId(result.message.id);
      await reloadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重试失败");
      await openConversation(active.id).catch(() => undefined);
    } finally {
      setRunning(false);
      window.setTimeout(() => setSteps(null), 900);
    }
  };

  const submitFeedback = async (message: ConversationMessage, verdict: "up" | "down") => {
    const turn = pairTurns(conversation?.messages || []).find((item) => item.assistant?.id === message.id);
    const question = turn?.user?.content || "";
    try {
      if (verdict === "down") {
        setFeedbackModal(message);
        return;
      }
      await api.feedback({ conversation_id: message.conversation_id, message_id: message.id, question, verdict });
      setFeedbackSent((current) => ({ ...current, [message.id]: "up" }));
    } catch {
      setFeedbackSent((current) => ({ ...current, [message.id]: "recorded-fallback" }));
    }
  };

  const confirmNegativeFeedback = async () => {
    if (!feedbackModal) return;
    const turn = pairTurns(conversation?.messages || []).find((item) => item.assistant?.id === feedbackModal.id);
    try {
      await api.feedback({
        conversation_id: feedbackModal.conversation_id,
        message_id: feedbackModal.id,
        question: turn?.user?.content || "",
        verdict: "down",
        category: feedbackCategory,
        detail: feedbackDetail,
      });
      setFeedbackSent((current) => ({ ...current, [feedbackModal.id]: "down" }));
      setFeedbackModal(null);
      setFeedbackDetail("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "反馈提交失败（后端端点未启用）");
      setFeedbackModal(null);
    }
  };

  const selectedMessage = conversation?.messages.find((item) => item.id === selectedMessageId) || null;
  const selectedSources: Source[] = useMemo(() => {
    if (!conversation) return [];
    if (selectedMessage?.role === "assistant") return selectedMessage.sources || [];
    return latestAssistant(conversation.messages)?.sources || [];
  }, [conversation, selectedMessage]);
  const conflicts: SourceConflict[] = useMemo(() => findConflicts(selectedSources), [selectedSources]);
  const quality = useMemo(() => evidenceQuality(selectedSources, conflicts), [selectedSources, conflicts]);

  const openOriginal = async (source: Source) => {
    if (source.source_type === "web" && source.url) {
      window.open(source.url, "_blank", "noopener,noreferrer");
      return;
    }
    if (source.knowledge_base_id && source.file_name) {
      try { await api.openSource(source.knowledge_base_id, source.file_name); }
      catch (e) { setError(e instanceof Error ? e.message : "来源文件打开失败"); }
    }
  };

  const terms = useMemo(() => {
    const turn = pairTurns(conversation?.messages || [])
      .find((item) => item.assistant?.id === (selectedMessage?.role === "assistant" ? selectedMessage.id : ""));
    return (turn?.user?.content || "").split(/[\s，。？?；;：:、]+/).filter((t) => t.length >= 2);
  }, [conversation, selectedMessage]);

  const renderAnswer = (text: string) => {
    const parts = text.split(/(\[\d{1,2}\])/g);
    return parts.map((part, index) => {
      const match = part.match(/^\[(\d{1,2})\]$/);
      if (match) {
        const n = Number(match[1]);
        return (
          <button
            key={index}
            type="button"
            className={focusedSource === n ? "cite flash" : "cite"}
            aria-label={`证据 ${n}`}
            onClick={() => setFocusedSource(n)}
          >
            {n}
          </button>
        );
      }
      return <span key={index}>{part}</span>;
    });
  };

  const turns = pairTurns(conversation?.messages || []);
  const scopedName = selectedKb === "all" ? "全部知识库" : bases.find((b) => b.id === selectedKb)?.name || selectedKb;

  return (
    <>
      <PageHeader
        kicker="02 问答 · 获取有依据的回答"
        title="问答"
        desc={`回答只使用当前账号有权访问的知识。检索范围：${scopedName}。`}
        actions={
          <div className="actions-row">
            <select
              className="select"
              style={{ minWidth: 200, maxWidth: 260 }}
              aria-label="选择会话"
              value={conversation?.id || ""}
              onChange={(e) => e.target.value && void openConversation(e.target.value)}
            >
              {items.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.message_count} 条</option>)}
            </select>
            {canAsk && <button type="button" className="btn btn--ghost btn--sm" onClick={() => void createConversation()}>新建会话</button>}
          </div>
        }
      />

      {error && (
        <div style={{ marginBottom: "var(--s6)" }}>
          <ErrorState
            title="问答请求失败"
            what={error}
            cause="后端拒绝或中断了本次请求。"
            next="重试这条消息，或在顶栏确认知识范围。"
            actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => setError("")}>关闭提示</button>}
          />
        </div>
      )}

      <div className="ask">
        <div style={{ minWidth: 0 }}>
          {steps && (
            <section className="panel" aria-label="检索流水线" style={{ marginBottom: "var(--s6)" }}>
              <div className="panel-head"><div><h3>检索流水线</h3><div className="sub">本次请求的实时阶段</div></div>{running && <Status label="PROCESSING" tone="warn" />}</div>
              <div className="pipe">
                {PIPELINE_STEPS.map((name, index) => (
                  <PipelineStep key={name} index={index + 1} name={name} state={steps[index] || "waiting"} />
                ))}
              </div>
            </section>
          )}

          <div className="thread" aria-live="polite">
            {initialLoading && <SkeletonRows rows={4} />}
            {!initialLoading && !turns.length && !running && (
              <EmptyState
                code="02 问答 · 尚无会话"
                title="向企业知识提问。"
                desc={canAsk ? "每条回答都附带引用、原文片段与证据质量，可一键打开来源。" : "该账号为只读权限，问答功能已停用。"}
              />
            )}
            {turns.map((turn, index) => (
              <article className="turn" key={turn.assistant?.id || turn.user?.id || index} style={{ paddingBottom: "var(--s8)", borderBottom: index < turns.length - 1 ? "1px solid var(--line)" : undefined }}>
                <div className="q-block">
                  <div className="k">问题 {String(index + 1).padStart(2, "0")}</div>
                  <div className="q">{turn.user?.content || "—"}</div>
                </div>
                {turn.assistant ? (
                  <div
                    className={turn.assistant.content ? "a-block" : "a-block pending"}
                    onClick={() => turn.assistant && setSelectedMessageId(turn.assistant.id)}
                    style={{ cursor: "pointer" }}
                  >
                    {turn.assistant.status === "generating" && !turn.assistant.content
                      ? "正在检索有权访问的知识并组织回答…"
                      : renderAnswer(turn.assistant.content || "")}
                    {turn.assistant.status === "failed" && (
                      <div style={{ marginTop: "var(--s3)" }}>
                        <Status label="FAILED" tone="err" />
                        <button type="button" className="btn-link" style={{ marginLeft: 12 }} disabled={running} onClick={(e) => { e.stopPropagation(); void retryMessage(turn.assistant!); }}>
                          重试这条回答
                        </button>
                      </div>
                    )}
                  </div>
                ) : null}
                {turn.assistant?.status === "completed" && (
                  <div className="actions-row" style={{ marginTop: "var(--s4)" }}>
                    <Kicker>回答反馈</Kicker>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      disabled={Boolean(feedbackSent[turn.assistant.id])}
                      onClick={() => void submitFeedback(turn.assistant!, "up")}
                    >
                      {feedbackSent[turn.assistant.id] === "up" ? "已记录反馈 · 有帮助" : "有帮助"}
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      disabled={Boolean(feedbackSent[turn.assistant.id])}
                      onClick={() => void submitFeedback(turn.assistant!, "down")}
                    >
                      {feedbackSent[turn.assistant.id] === "down" ? "已记录反馈 · 有问题" : "反馈问题"}
                    </button>
                  </div>
                )}
                {index === turns.length - 1 && !running && (
                  <div className="followups">
                    <div className="k">追问建议</div>
                    {suggestions.filter((item) => item !== turn.user?.content).slice(0, 3).map((item) => (
                      <button key={item} type="button" onClick={() => void send(item)}>{item}</button>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </div>

          <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
            <textarea
              ref={textareaRef}
              className="textarea"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
              placeholder={canAsk ? "提出问题——Enter 发送，Shift+Enter 换行" : "只读账号：问答功能已停用"}
              disabled={!canAsk || running}
              aria-label="向企业知识助手提问"
              style={{ minHeight: 56 }}
            />
            <div className="actions-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
              <button type="submit" className="btn btn--primary" disabled={!canAsk || running || !input.trim()}>
                {running ? "生成中…" : "提问"}
              </button>
              <label className="check" style={{ minHeight: 24, fontSize: 11 }}>
                <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} disabled={running} />
                重排序
              </label>
            </div>
          </form>
        </div>

        <aside className="inspector panel" aria-label="证据面板">
          <div className="insp-head">
            <h3>证据</h3>
            <span className={`quality`}>
              <span className={`level level--${quality.level}`}>{QUALITY_LABELS[quality.level]}</span>
            </span>
          </div>

          {conflicts.length > 0 && (
            <div className="conflict" role="alert">
              <div className="t">来源冲突 · 需人工核对</div>
              {conflicts.map((conflict) => (
                <p key={conflict.metric}>
                  {conflict.metric}：<b>{conflict.values.join(" 对比 ")}</b>，出现在 {conflict.documents.join("、")}
                </p>
              ))}
            </div>
          )}

          <div className="insp-sec">
            <div className="k">证据质量</div>
            <MetricStrip
              items={[
                ["支撑分块", quality.supportingChunks],
                ["支撑文档", quality.supportingDocuments],
                ["引用覆盖率", `${Math.round(quality.citationCoverage * 100)}%`],
                ["最高得分", fmtScore(quality.topScore)],
              ]}
            />
            <div className="v" style={{ marginTop: 8, fontSize: 12, color: "var(--ink-60)" }}>
              {quality.noEvidence
                ? "本条回答没有附带知识库证据。"
                : quality.webOnly
                  ? "回答依赖公开网页来源，内部使用前请先核实。"
                  : `得分来自${quality.reranked ? "重排序 + 检索" : "检索"}；不使用伪置信度百分比。`}
            </div>
          </div>

          {selectedSources.length === 0 && (
            <div className="insp-sec"><EmptyState code="02 问答 · 暂无证据" title="还没有引用" desc="提出一个问题，然后点击某条回答，即可在此查看它的来源。" /></div>
          )}
          {selectedSources.map((source, index) => {
            const n = source.citation_index || index + 1;
            return (
              <div
                className="evid"
                key={`${n}-${source.file_name}-${index}`}
                style={focusedSource === n ? { background: "var(--accent-soft)" } : undefined}
              >
                <div className="evid-top">
                  <span className="evid-num">[{n}]</span>
                  <span className="evid-title">{source.title || source.file_name}</span>
                </div>
                <div className="evid-meta">
                  <span>{source.source_type === "web" ? `网页 · ${source.domain || "外部来源"}` : source.knowledge_base_name || source.knowledge_base_id || "企业知识库"}</span>
                  {source.page ? <span>第 {source.page} 页</span> : null}
                  <span>得分 {fmtScore(source.relevance_score)}</span>
                </div>
                <p className="evid-quote">{highlight(source.content_preview || "", terms)}</p>
                <div className="evid-actions">
                  <button type="button" className="btn-link" onClick={() => void openOriginal(source)}>查看原文</button>
                  {source.knowledge_base_id ? (
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => navigate("knowledge", { fileName: source.file_name, knowledgeBaseId: source.knowledge_base_id })}
                    >
                      查看上下文
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}

          <div className="insp-sec">
            <div className="k">请求信息</div>
            <div className="v v--mono" style={{ marginTop: 8 }}>
              <Kv
                items={[
                  ["更新时间", fmtTime(selectedMessage?.created_at)],
                  ["响应耗时", selectedMessage?.latency_ms != null ? fmtMs(selectedMessage.latency_ms) : "—"],
                  ["状态", selectedMessage ? <Status label={(selectedMessage.status || "COMPLETED").toUpperCase()} /> : "—"],
                ]}
              />
            </div>
            {lastTraceId && (
              <button type="button" className="btn btn--ghost btn--sm mt-2" onClick={() => navigate("trace", { traceId: lastTraceId })}>
                查看请求追踪 · {lastTraceId.slice(0, 8)}
              </button>
            )}
          </div>
        </aside>
      </div>

      {feedbackModal && (
        <Modal
          kicker="反馈 · 失败信号"
          title="哪里出了问题？"
          onClose={() => setFeedbackModal(null)}
          footer={
            <>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setFeedbackModal(null)}>取消</button>
              <button type="button" className="btn btn--primary btn--sm" onClick={() => void confirmNegativeFeedback()}>提交至运营</button>
            </>
          }
        >
          <div className="form-grid">
            <div className="field">
              <label htmlFor="fb-cat">类别</label>
              <select id="fb-cat" className="select" value={feedbackCategory} onChange={(e) => setFeedbackCategory(e.target.value)}>
                <option value="answer">回答 —— 有误或不完整</option>
                <option value="retrieval">检索 —— 没找到正确的文档</option>
                <option value="citation">引用 —— 证据与结论不匹配</option>
                <option value="conflict">冲突 —— 来源互相矛盾</option>
                <option value="other">其他</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="fb-detail">详细说明</label>
              <textarea id="fb-detail" className="textarea" value={feedbackDetail} onChange={(e) => setFeedbackDetail(e.target.value)} placeholder="你期望的答案是什么？" />
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
