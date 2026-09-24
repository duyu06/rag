"use client";

import { ReactNode, useEffect, useRef } from "react";

/* ============================================================
   Shared primitives — one kit for every page (acceptance §13)
   ============================================================ */

export type Tone = "ok" | "warn" | "err" | "info" | "idle" | "ink";

// Display-layer translation only: enum values and API payloads stay English.
const STATUS_LABELS: Record<string, string> = {
  READY: "就绪",
  INDEXING: "索引中",
  PROCESSING: "处理中",
  FAILED: "失败",
  DISABLED: "已停用",
  ENABLED: "已启用",
  ONLINE: "在线",
  OFFLINE: "离线",
  DEGRADED: "降级",
  RUNNING: "进行中",
  WAITING: "等待",
  DONE: "完成",
  COMPLETE: "完成",
  COMPLETED: "已完成",
  OK: "正常",
  HEALTHY: "健康",
  PASS: "通过",
  ERROR: "错误",
  OPERATIONAL: "正常",
  PENDING: "待处理",
  DENIED: "已拒绝",
  GRANTED: "通过",
  SUCCESS: "成功",
  ARCHIVED: "已归档",
  ACTIVE: "正常",
  UNKNOWN: "未知",
  HIT: "命中",
  MISS: "未命中",
};

export function statusLabel(label: string): string {
  return STATUS_LABELS[label.toUpperCase()] ?? label;
}

const DEPARTMENT_LABELS: Record<string, string> = {
  ALL: "全企业",
  HR: "人事",
  PRODUCT: "产品",
  SALES: "销售",
  SERVICE: "售后",
};

export function departmentLabel(department?: string | null): string | undefined {
  if (!department) return undefined;
  return DEPARTMENT_LABELS[department.toUpperCase()] ?? department;
}

export function statusTone(status?: string | null): Tone {
  switch ((status || "").toUpperCase()) {
    case "READY":
    case "ONLINE":
    case "COMPLETE":
    case "HEALTHY":
    case "OK":
    case "PASS":
    case "OPERATIONAL":
    case "DONE":
      return "ok";
    case "INDEXING":
    case "PROCESSING":
    case "RUNNING":
    case "DEGRADED":
    case "PENDING":
      return "warn";
    case "FAILED":
    case "ERROR":
    case "OFFLINE":
    case "DENIED":
      return "err";
    default:
      return "idle";
  }
}

export function Kicker({ children, accent = false }: { children: ReactNode; accent?: boolean }) {
  return <span className={accent ? "kicker kicker--accent" : "kicker"}>{children}</span>;
}

export function PageHeader({
  kicker,
  title,
  desc,
  actions,
}: {
  kicker: string;
  title: string;
  desc?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <Kicker>{kicker}</Kicker>
      <div className="title-row">
        <h1>{title}</h1>
        {actions && <div className="actions-row">{actions}</div>}
      </div>
      {desc && <p className="desc">{desc}</p>}
    </header>
  );
}

export function Status({ label, tone }: { label: string; tone?: Tone }) {
  return <span className={`status status--${tone || statusTone(label)}`}>{statusLabel(label)}</span>;
}

export function Stat({ value, label, big = false }: { value: ReactNode; label: string; big?: boolean }) {
  return (
    <div className={big ? "stat stat--big" : "stat"}>
      <div className="v num">{value}</div>
      <div className="k">{label}</div>
    </div>
  );
}

export function Kv({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Rule() {
  return <hr className="rule" />;
}

export function Tabs<T extends string>({
  items,
  active,
  onChange,
}: {
  items: { key: T; label: string; count?: number }[];
  active: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <button
          key={item.key}
          role="tab"
          type="button"
          aria-selected={active === item.key}
          className={active === item.key ? "tab on" : "tab"}
          onClick={() => onChange(item.key)}
        >
          {item.label}
          {item.count != null && <span className="count">{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function FilterChips<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label?: string;
  options: { key: T; label: string }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="filters" role="group" aria-label={label}>
      {label && <span className="kicker">{label}</span>}
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          className={value === option.key ? "chip on" : "chip"}
          onClick={() => onChange(option.key)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ---------- Table (grid driven, 48px rows) ---------- */
export function DataTable({
  cols,
  head,
  children,
  footer,
}: {
  cols: string;
  head: ReactNode[];
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section className="panel table">
      <div className="thead" style={{ gridTemplateColumns: cols }}>
        {head.map((cell, index) => (
          <span key={index}>{cell}</span>
        ))}
      </div>
      {children}
      {footer}
    </section>
  );
}

export function TRow({
  cols,
  children,
  onClick,
  selected = false,
  label,
}: {
  cols: string;
  children: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  label?: string;
}) {
  const cls = selected ? "tr selected" : "tr";
  if (onClick) {
    return (
      <div className={cls} style={{ gridTemplateColumns: cols }} data-clickable role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => { if (e.key === "Enter") onClick(); }} aria-label={label}>
        {children}
      </div>
    );
  }
  return (
    <div className={cls} style={{ gridTemplateColumns: cols }}>
      {children}
    </div>
  );
}

/* ---------- Pipeline / Trace / Ranking ---------- */
export type StepState = "done" | "running" | "waiting" | "failed";

export function PipelineStep({
  index,
  name,
  detail,
  state,
  cause,
  actions,
}: {
  index: number;
  name: string;
  detail?: ReactNode;
  state: StepState;
  cause?: string;
  actions?: ReactNode;
}) {
  const stateLabel = { done: "完成", running: "进行中", waiting: "等待", failed: "失败" }[state];
  const tone: Tone = state === "done" ? "ok" : state === "running" ? "info" : state === "failed" ? "err" : "idle";
  return (
    <div className={`pipe-step ${state}`}>
      <span className="n">{String(index).padStart(2, "0")}</span>
      <div className="name">
        {name}
        {detail && <small>{detail}</small>}
        {cause && <div className="cause">{cause}</div>}
      </div>
      <div className="actions-row">
        {actions}
        <Status label={stateLabel} tone={tone} />
      </div>
    </div>
  );
}

export function TraceRow({
  index,
  name,
  ms,
  maxMs,
}: {
  index: number;
  name: string;
  ms: number;
  maxMs: number;
}) {
  const ratio = maxMs > 0 ? Math.max(2, Math.round((ms / maxMs) * 100)) : 0;
  return (
    <div className={ms === maxMs && ms > 0 ? "trace-row hot" : "trace-row"}>
      <span className="n">{String(index).padStart(2, "0")}</span>
      <span className="nm">{name}</span>
      <span className="bar" aria-hidden="true"><i style={{ width: `${ratio}%` }} /></span>
      <span className="ms">{fmtMs(ms)}</span>
    </div>
  );
}

export function RankRow({
  index,
  name,
  meta,
  score,
  hit,
  onClick,
}: {
  index: number;
  name: string;
  meta?: string;
  score?: string;
  hit?: boolean | null;
  onClick?: () => void;
}) {
  const cls = hit == null ? "rank" : hit ? "rank hit" : "rank";
  const Comp: "div" | "button" = onClick ? "button" : "div";
  return (
    <Comp className={cls} type={onClick ? "button" : undefined} onClick={onClick} style={{ width: "100%", textAlign: "left" }}>
      <span className="n">{String(index).padStart(2, "0")}</span>
      <span className="nm">
        {name}
        {meta && <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}> · {meta}</span>}
      </span>
      <span className="sc">{score ?? "—"}</span>
      <span className="flag">{hit == null ? "" : hit ? "命中" : "未命中"}</span>
    </Comp>
  );
}

export function MetricStrip({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="metrics">
      {items.map(([label, value]) => (
        <div className="m" key={label}>
          <span>{label}</span>
          <b>{value}</b>
        </div>
      ))}
    </div>
  );
}

/* ---------- Evidence ---------- */
export function highlight(text: string, terms: string[]) {
  const clean = terms.filter((term) => term.trim().length >= 2);
  if (!clean.length) return <>{text}</>;
  const pattern = new RegExp(`(${clean.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        part && pattern.test(part) && index % 2 === 1 ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>,
      )}
    </>
  );
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/* ---------- States ---------- */
export function EmptyState({
  code,
  title,
  desc,
  action,
}: {
  code: string;
  title: string;
  desc: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <Kicker>{code}</Kicker>
      <h3 style={{ marginTop: 12 }}>{title}</h3>
      <p>{desc}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title,
  what,
  cause,
  next,
  actions,
}: {
  title: string;
  what: string;
  cause?: string;
  next?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="error-state" role="alert">
      <div className="t">{title}</div>
      <p>{what}</p>
      {cause && <p><span className="mono">原因 · </span>{cause}</p>}
      {next && <p><span className="mono">下一步 · </span>{next}</p>}
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skel skel-row" key={index} style={{ opacity: 1 - index * 0.12 }} />
      ))}
    </div>
  );
}

export function RestrictedPanel({
  resource,
  policy,
  reason,
  onRequest,
  requesting,
}: {
  resource: string;
  policy: string;
  reason: string;
  onRequest?: () => void;
  requesting?: boolean;
}) {
  return (
    <div className="restricted">
      <Kicker>访问受限</Kicker>
      <div className="t" style={{ marginTop: 8 }}>你当前没有访问该资源的权限。</div>
      <Kv
        items={[
          ["资源", resource],
          ["策略", policy],
          ["原因", reason],
        ]}
      />
      {onRequest && (
        <button type="button" className="btn btn--primary" onClick={onRequest} disabled={requesting}>
          {requesting ? "申请已发送" : "申请权限"}
        </button>
      )}
    </div>
  );
}

/* ---------- Modal ---------- */
export function Modal({
  title,
  kicker,
  onClose,
  children,
  footer,
}: {
  title: string;
  kicker?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" ref={ref}>
        {kicker && <Kicker>{kicker}</Kicker>}
        <h2 style={{ marginTop: kicker ? 8 : 0 }}>{title}</h2>
        {children}
        {footer && <div className="modal-actions">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------- Formatting ---------- */
export function fmtMs(ms?: number | null) {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function fmtNum(value?: number | null) {
  return value == null ? "—" : value.toLocaleString("en-US");
}

export function fmtScore(value?: number | null) {
  return value == null ? "—" : value.toFixed(3);
}

export function fmtTime(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return value;
  }
}

export function relTime(value?: string | null) {
  if (!value) return "—";
  const diff = Date.now() - new Date(value).getTime();
  if (Number.isNaN(diff)) return value;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}
