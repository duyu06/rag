"use client";

import { useEffect, useState } from "react";
import { accessRoleName, api, AuditEvent, hasPermission, KnowledgeBase, UserRow } from "@/lib/api";
import {
  DataTable,
  EmptyState,
  ErrorState,
  Kicker,
  Modal,
  PageHeader,
  RestrictedPanel,
  SkeletonRows,
  Status,
  TRow,
  Tabs,
  departmentLabel,
  fmtTime,
} from "@/components/ui";
import { ViewProps } from "@/lib/nav";

const OPS = ["READ", "ASK", "SEARCH", "DOWNLOAD", "EDIT", "DELETE", "ADMIN"];
const ROLE_MATRIX: Record<string, string[]> = {
  ADMIN: OPS,
  SALES: ["READ", "ASK", "SEARCH", "DOWNLOAD"],
  HR: ["READ", "ASK", "SEARCH", "DOWNLOAD"],
  USER: ["READ", "ASK", "SEARCH"],
  VIEWER: ["READ", "SEARCH"],
};

/* 显示层译名：矩阵列名与审计动作值是两套语境（SEARCH 在矩阵里是"检索"，在审计动作里是"搜索"）。 */
const OP_LABELS: Record<string, string> = {
  READ: "读取",
  ASK: "问答",
  SEARCH: "检索",
  DOWNLOAD: "下载",
  EDIT: "编辑",
  DELETE: "删除",
  ADMIN: "管理",
};
const ROLE_LABELS: Record<string, string> = {
  ADMIN: "管理员",
  SALES: "销售",
  HR: "人事",
  USER: "普通用户",
  VIEWER: "访客",
};
const ACTION_LABELS: Record<string, string> = {
  LOGIN: "登录",
  LOGOUT: "登出",
  SIGN_IN: "登录",
  SIGN_OUT: "登出",
  AUTHORIZATION: "授权",
  ACCESS: "访问",
  ACCESS_REQUEST: "权限申请",
  QUERY: "问答",
  ASK: "问答",
  SEARCH: "搜索",
  RETRIEVAL_DEBUG: "检索调试",
  SOURCE_VIEW: "查看来源",
  UPLOAD: "上传",
  INGEST: "文档入库",
  DOWNLOAD: "下载",
  DELETE: "删除",
  DOCUMENT_MOVE: "文档移动",
  DOCUMENT_ENABLE: "文档启用",
  DOCUMENT_DISABLE: "文档停用",
  DOCUMENT_REINDEX: "重建索引",
  EVALUATION: "RAG 评测",
  EVAL_FAILURE_TRIAGE: "评测失败归类",
  FEEDBACK: "回答反馈",
  DEMO_INIT: "初始化演示数据",
  DEMO_RESET: "重置演示数据",
  TOOL_CALL: "工具调用",
  TOOL_RESULT: "工具结果",
};

function roleLabel(role?: string | null) {
  if (!role) return "—";
  return ROLE_LABELS[role.toUpperCase()] ?? role;
}

function actionLabel(action?: string | null) {
  if (!action) return "—";
  return ACTION_LABELS[action.toUpperCase()] ?? action;
}

// GRANTED 不在 <Status> 的内置词表里，需在显示层补译；其余交给 Status 内部映射。
function auditStatusLabel(status?: string | null) {
  const key = (status || "OK").toUpperCase();
  return key === "GRANTED" ? "通过" : key;
}

// ACTIVE 同样不在内置词表里：正常 / 已停用（DISABLED 与 Status 内置译法一致）。
const MEMBER_STATUS_LABELS: Record<string, string> = { ACTIVE: "正常", DISABLED: "已停用" };

function memberStatusLabel(status?: string | null) {
  const key = (status || "ACTIVE").toUpperCase();
  return MEMBER_STATUS_LABELS[key] ?? key;
}

type Tab = "members" | "permissions" | "audit";

export default function GovernanceView({ user, bases, setNotice }: ViewProps) {
  const isAdmin = hasPermission(user, "system:operate");
  const [tab, setTab] = useState<Tab>("members");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [requestOpen, setRequestOpen] = useState(false);
  const [resource, setResource] = useState("kb:hr_private");
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setError("");
      try {
        const [userData, auditData] = await Promise.all([
          api.users().catch(() => ({ users: [] as UserRow[] })),
          api.audit(50),
        ]);
        if (cancelled) return;
        setUsers(userData.users || []);
        setAudit(auditData.events || []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "治理数据加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const submitRequest = async () => {
    setSending(true);
    try {
      await api.requestAccess({ resource, policy: "role→kb ACL", reason });
      setNotice("权限申请已记录 · 管理员将在治理视图中审核");
      setRequestOpen(false);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "权限申请失败", "err");
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PageHeader
        kicker="09 治理 — 身份 · 访问控制 · 审计"
        title="治理"
        desc="成员、角色 → 操作矩阵与知识库可见范围。受限提示必须说明资源、策略与原因，绝不出现裸“无权限”。"
        actions={!isAdmin ? <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRequestOpen(true)}>申请权限</button> : undefined}
      />

      {error && <div className="mb-6"><ErrorState title="治理数据加载失败" what={error} cause="审计接口不可用。" next="重试，或到“系统”视图查看服务状态。" actions={<button type="button" className="btn btn--ghost btn--sm" onClick={() => location.reload()}>重新加载</button>} /></div>}
      {loading && <SkeletonRows rows={5} />}

      <Tabs
        items={[
          { key: "members", label: "成员", count: users.length || undefined },
          { key: "permissions", label: "权限" },
          { key: "audit", label: "审计记录", count: audit.length || undefined },
        ]}
        active={tab}
        onChange={setTab}
      />

      {!loading && tab === "members" && (
        <>
          {!isAdmin && (
            <div className="mb-6">
              <RestrictedPanel
                resource="成员目录（完整）"
                policy="“治理 → 成员”需要 system:operate 权限"
                reason="你的角色只能看到共享目录摘要；调整角色属于管理员权限范围。"
                onRequest={() => setRequestOpen(true)}
                requesting={sending}
              />
            </div>
          )}
          <DataTable cols="64px 160px 160px 120px 120px 110px 140px" head={["#", "用户名", "显示名", "角色", "部门", "状态", "最近登录"]}>
            {users.map((row, index) => (
              <TRow key={row.username} cols="64px 160px 160px 120px 120px 110px 140px">
                <span className="cell-mono">{String(index + 1).padStart(2, "0")}</span>
                <span className="primary-col"><b>{row.username}</b></span>
                <span>{row.display_name}</span>
                <span className="cell-mono">{roleLabel(row.role)}</span>
                <span className="cell-mono">{row.department || "—"}</span>
                <span><Status label={memberStatusLabel(row.status)} tone={row.status === "DISABLED" ? "idle" : "ok"} /></span>
                <span className="cell-mono">{fmtTime(row.last_login)}</span>
              </TRow>
            ))}
            {!users.length && <TRow cols="1fr"><EmptyState code="成员 / 0" title="成员目录未开放。" desc="/auth/users 接口尚未提供，或对当前角色隐藏。" /></TRow>}
          </DataTable>
        </>
      )}

      {!loading && tab === "permissions" && (
        <>
          <div className="split">
            <section className="panel" aria-label="角色 → 操作矩阵">
              <div className="panel-head"><div><h3>角色 → 操作矩阵</h3><div className="sub">在任何检索之前由服务端强制校验；导航与其保持一致</div></div></div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr>
                    <th className="kicker" style={{ textAlign: "left", padding: "10px var(--s6)", borderBottom: "1px solid var(--line)" }}>角色</th>
                    {OPS.map((op) => <th key={op} className="kicker" style={{ padding: "10px 4px", borderBottom: "1px solid var(--line)" }}>{OP_LABELS[op] ?? op}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(ROLE_MATRIX).map(([role, ops]) => (
                    <tr key={role} style={{ background: user.role === role ? "var(--accent-soft)" : undefined }}>
                      <td style={{ padding: "10px var(--s6)", borderBottom: "1px solid var(--line)", fontFamily: "var(--mono)", fontSize: 12 }}>{roleLabel(role)}{user.role === role && <span className="kicker" style={{ marginLeft: 8 }}>本人</span>}</td>
                      {OPS.map((op) => (
                        <td key={op} style={{ textAlign: "center", borderBottom: "1px solid var(--line)", fontFamily: "var(--mono)", fontSize: 12, color: ops.includes(op) ? "var(--ink)" : "var(--ink-24)" }}>
                          {ops.includes(op) ? "是" : "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="metrics"><Kicker>租户 → 部门 → 知识库 → 文档 → 元数据过滤 · 权限拒绝一律以“已拒绝”记入审计</Kicker></div>
            </section>

            <aside className="panel" aria-label="知识库可见范围">
              <div className="panel-head"><div><h3>知识库访问控制</h3><div className="sub">{accessRoleName(user)}可见的知识库</div></div></div>
              {bases.map((base: KnowledgeBase) => (
                <div key={base.id} className="tr" style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 12, padding: "12px var(--s6)", borderBottom: "1px solid var(--line)" }}>
                  <div>
                    <b style={{ fontSize: 13 }}>{base.name}</b>
                    <div className="meta">{departmentLabel(base.department)} · {base.id}</div>
                  </div>
                  <Status label="读取·检索·问答" tone="ink" />
                </div>
              ))}
              <div className="metrics"><Kicker>无权限 = 分块永不进入候选集（检索前过滤）</Kicker></div>
            </aside>
          </div>
        </>
      )}

      {!loading && tab === "audit" && (
        <DataTable cols="150px 130px 90px 150px 110px minmax(200px,1.6fr)" head={["时间", "用户", "角色", "操作", "状态", "对象"]}>
          {audit.map((event, index) => (
            <TRow key={index} cols="150px 130px 90px 150px 110px minmax(200px,1.6fr)">
              <span className="cell-mono">{fmtTime(event.timestamp)}</span>
              <span className="cell-mono">{event.username}</span>
              <span className="cell-mono">{roleLabel(event.role)}</span>
              <span className="cell-mono">{actionLabel(event.action)}</span>
              <span><Status label={auditStatusLabel(event.status)} tone={event.status === "DENIED" ? "err" : undefined} /></span>
              <span className="cell-mono" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{event.query || event.detail || event.knowledge_base_id || "—"}</span>
            </TRow>
          ))}
          {!audit.length && <TRow cols="1fr"><EmptyState code="审计 / 0" title="暂无审计事件。" desc="登录、检索、问答、下载、删除与配置变更都会记录在这里。" /></TRow>}
        </DataTable>
      )}

      {requestOpen && (
        <Modal
          kicker="权限申请"
          title="申请额外权限"
          onClose={() => setRequestOpen(false)}
          footer={
            <>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRequestOpen(false)}>取消</button>
              <button type="button" className="btn btn--primary btn--sm" disabled={sending || !reason.trim()} onClick={() => void submitRequest()}>{sending ? "提交中…" : "提交申请"}</button>
            </>
          }
        >
          <div className="form-grid">
            <div className="field">
              <label htmlFor="req-res">资源</label>
              <select id="req-res" className="select" value={resource} onChange={(e) => setResource(e.target.value)}>
                <option value="kb:hr_private">知识库 · 人事</option>
                <option value="kb:sales_ops">知识库 · 销售运营</option>
                <option value="op:knowledge:manage">操作 · 编辑 / 上传</option>
                <option value="op:system:operate">操作 · 管理控制台</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="req-reason">业务理由</label>
              <textarea id="req-reason" className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="说明为什么需要这项权限、需要多久…" />
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
