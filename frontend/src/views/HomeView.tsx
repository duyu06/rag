"use client";

import { useEffect, useState } from "react";
import { api, hasPermission, SystemStatus, User } from "@/lib/api";
import { conversationApi, ConversationSummary } from "@/lib/conversations";
import { Kicker, Status, fmtNum, fmtTime, statusTone } from "@/components/ui";
import { ViewProps } from "@/lib/nav";

// ui.tsx 的内置中文映射未覆盖这几个探测态词（该文件冻结），在视图层补齐；
// 后端健康值本身是协议枚举，比较逻辑仍用英文。
const SYS_STATUS_ZH: Record<string, string> = {
  UNKNOWN: "未知",
  PROBING: "探测中",
  PROBE: "探测中",
};

function SystemStatusChip({ value }: { value?: string | null }) {
  const key = (value || "").toUpperCase();
  return <Status label={SYS_STATUS_ZH[key] ?? key} tone={statusTone(key)} />;
}

export default function HomeView({ user, bases, selectedKb, setSelectedKb, navigate }: ViewProps) {
  const [query, setQuery] = useState("");
  const [recent, setRecent] = useState<ConversationSummary[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    if (hasPermission(user, "conversation:read")) {
      conversationApi.list().then((rows) => setRecent(rows.slice(0, 5))).catch(() => undefined);
    }
    api.stats(selectedKb).then(setStats).catch(() => undefined);
    api.systemStatus().then(setStatus).catch(() => undefined);
  }, [user, selectedKb]);

  const submit = () => {
    const q = query.trim();
    if (!q) { navigate("ask"); return; }
    navigate("search", { query: q });
  };

  const health = status?.llm?.status?.toUpperCase();
  const llmLabel = status ? (health === "ONLINE" || health === "HEALTHY" ? "ONLINE" : health || "UNKNOWN") : "PROBING";

  return (
    <div className="home">
      <div style={{ minWidth: 0 }}>
        <section className="home-hero">
          <Kicker accent>企业知识操作系统</Kicker>
          <h1 className="display display--xl" style={{ marginTop: "var(--s4)" }}>向企业提问。</h1>
          <p className="muted" style={{ marginTop: "var(--s4)", maxWidth: 640 }}>
            按权限过滤的检索覆盖 {fmtNum(stats?.knowledge_bases ?? bases.length)} 个知识库、{fmtNum(stats?.total_documents)} 份文档、
            {fmtNum(stats?.total_chunks)} 个已索引切片。检索用来找文档，问答用来给出带引用的回答。
          </p>

          <form className="home-search" onSubmit={(e) => { e.preventDefault(); submit(); }}>
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="输入查询 — ⏎ 直接检索，或点「问答」获取带引用的回答"
              aria-label="向企业知识提问或检索"
            />
            <span className="hint">
              <button type="button" className="btn-link" style={{ marginRight: 12 }} onClick={() => { const q = query.trim(); navigate("ask", q ? { query: q } : undefined); }}>问答 →</button>
              ⌘K
            </span>
          </form>

          <div className="quick-row">
            <button type="button" className={selectedKb === "all" ? "chip on" : "chip"} onClick={() => setSelectedKb("all")}>全部知识</button>
            {bases.slice(0, 5).map((base) => (
              <button key={base.id} type="button" className={selectedKb === base.id ? "chip on" : "chip"} onClick={() => { setSelectedKb(base.id); navigate("search"); }}>
                {base.name.toUpperCase()}
              </button>
            ))}
          </div>

          <section className="recent">
            <Kicker>最近会话</Kicker>
            <div className="mt-4">
              {recent.length === 0 && <p className="muted" style={{ fontSize: 13 }}>还没有会话 — 从问答开始。</p>}
              {recent.map((item, index) => (
                <div key={item.id} className="recent-item" onClick={() => navigate("ask", { conversationId: item.id })} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate("ask", { conversationId: item.id })}>
                  <span className="n">{String(index + 1).padStart(2, "0")}</span>
                  <div style={{ minWidth: 0 }}>
                    <b>{item.title}</b>
                    <div className="meta">{item.message_count} 条消息 · {fmtTime(item.updated_at)}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="count-row">
            <div><div className="num" style={{ fontSize: 28 }}>{fmtNum(stats?.total_documents ?? 0)}</div><Kicker>文档</Kicker></div>
            <div><div className="num" style={{ fontSize: 28 }}>{fmtNum(stats?.total_chunks ?? 0)}</div><Kicker>切片</Kicker></div>
            <div><div className="num" style={{ fontSize: 28 }}>{fmtNum(stats?.knowledge_bases ?? bases.length)}</div><Kicker>知识库</Kicker></div>
            <div><div className="num" style={{ fontSize: 28 }}>{fmtNum(stats?.daily_active_users ?? "—")}</div><Kicker>今日活跃</Kicker></div>
          </section>
        </section>
      </div>

      <aside className="rail" aria-label="系统状态栏">
        <Kicker>系统</Kicker>
        <div className="row"><span>大模型</span><SystemStatusChip value={llmLabel} /></div>
        <div className="row"><span>向量化模型</span><SystemStatusChip value={status?.embedding?.status || "PROBE"} /></div>
        <div className="row"><span>向量库</span><SystemStatusChip value={status?.vector_db?.status || "PROBE"} /></div>
        <div className="row"><span>构建版本</span><b>P1.8</b></div>
        <div className="row"><span>当前用户</span><b>{user.username}</b></div>
        <div className="row" style={{ marginTop: "var(--s4)" }}><b style={{ color: "var(--ink)" }}>来源 → 知识 → 检索 → 证据 → 回答 → 反馈 → 评测 → 改进</b></div>
      </aside>
    </div>
  );
}
