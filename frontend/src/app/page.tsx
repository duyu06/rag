"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AskView from "@/views/AskView";
import EvaluationView from "@/views/EvaluationView";
import GovernanceView from "@/views/GovernanceView";
import HomeView from "@/views/HomeView";
import KnowledgeView from "@/views/KnowledgeView";
import OperationsView from "@/views/OperationsView";
import RetrievalView from "@/views/RetrievalView";
import SearchView from "@/views/SearchView";
import SystemView from "@/views/SystemView";
import TraceView from "@/views/TraceView";
import { Kicker } from "@/components/ui";
import {
  api,
  accessRoleName,
  hasPermission,
  KnowledgeBase,
  session,
  User,
} from "@/lib/api";
import { findNavItem, visibleSections, ViewKey, ViewPayload } from "@/lib/nav";

const roleNames: Record<User["role"], string> = {
  ADMIN: "管理员",
  SALES: "销售",
  HR: "人事",
  USER: "普通用户",
  VIEWER: "访客",
};

function identityLabel(user: User) {
  const platform = accessRoleName(user);
  const business = roleNames[user.role];
  return platform === business ? platform : `${platform} · ${business}`;
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [view, setView] = useState<ViewKey>("home");
  const [payload, setPayload] = useState<ViewPayload | undefined>(undefined);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedKb, setSelectedKb] = useState("all");
  const [notice, setNoticeState] = useState<{ message: string; kind: "info" | "err" } | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const boot = async () => {
      if (!session.hasToken()) {
        setBooting(false);
        return;
      }
      try {
        setUser(await api.me());
      } catch {
        session.clear();
      } finally {
        setBooting(false);
      }
    };
    void boot();
  }, []);

  useEffect(() => {
    if (!user) return;
    if (!hasPermission(user, "knowledge:read")) {
      setBases([]);
      return;
    }
    let cancelled = false;
    api
      .knowledgeBases()
      .then((value) => {
        if (!cancelled) setBases(value);
      })
      .catch(() => {
        if (!cancelled) setBases([]);
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const sections = useMemo(() => visibleSections(user), [user]);

  useEffect(() => {
    if (!user) return;
    const allowed = sections.flatMap((section) => section.items.map((item) => item.key));
    if (!allowed.includes(view)) setView("home");
  }, [user, sections, view]);

  const navigate = useCallback((next: ViewKey, withPayload?: ViewPayload) => {
    setView(next);
    setPayload(withPayload);
    if (typeof window !== "undefined") window.scrollTo({ top: 0 });
  }, []);

  const setNotice = useCallback((message: string, kind: "info" | "err" = "info") => {
    setNoticeState({ message, kind });
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNoticeState(null), 6000);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (booting) return <BootScreen />;
  if (!user) {
    return (
      <LoginScreen
        onLogin={(next) => {
          setUser(next);
          setView("home");
          setPayload(undefined);
        }}
      />
    );
  }

  const logout = () => {
    session.clear();
    setUser(null);
    setBases([]);
    setSelectedKb("all");
    setNoticeState(null);
  };

  const crumb = findNavItem(view);
  const sharedProps = {
    user,
    bases,
    selectedKb,
    setSelectedKb,
    navigate,
    setNotice,
    payload,
  };

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">跳到主内容</a>

      <aside className="sidebar">
        <div className="side-brand">
          <span className="mark" aria-hidden="true">Y</span>
          <div>
            <strong>yaoke</strong>
            <span>企业知识操作系统</span>
          </div>
        </div>

        <nav className="nav" aria-label="主导航">
          {sections.map((section) => (
            <div key={section.idx}>
              <div className="nav-label">
                <Kicker>{`${section.idx} ${section.zh}`}</Kicker>
              </div>
              {section.items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={view === item.key ? "nav-item active" : "nav-item"}
                  onClick={() => navigate(item.key)}
                  aria-current={view === item.key ? "page" : undefined}
                >
                  <span className="idx">{item.idx}</span>
                  <span className="txt">{item.zh}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="side-foot">
          <div className="row">
            <span>角色</span>
            <span>{identityLabel(user)}</span>
          </div>
          <div className="row">
            <span>知识范围</span>
            <span>{selectedKb === "all" ? "全部知识库" : selectedKb}</span>
          </div>
          <div className="user-line">
            <span className="avatar" aria-hidden="true">{user.display_name.slice(0, 1)}</span>
            <div className="who">
              <b>{user.display_name}</b>
              <span className="meta">{user.username}</span>
            </div>
            <button type="button" className="btn-link" onClick={logout}>
              登出
            </button>
          </div>
        </div>
      </aside>

      <div className="main-area">
        <header className="top">
          <div className="crumb">
            {crumb ? (
              <>
                <span>{`${crumb.section.idx} ${crumb.section.zh}`}</span>
                <i>/</i>
                <b>{crumb.item.zh}</b>
              </>
            ) : (
              <b>yaoke</b>
            )}
          </div>
          <div className="top-actions">
            {hasPermission(user, "knowledge:read") && bases.length > 0 && (
              <div className="kb-scope">
                <label htmlFor="kb-scope-select">知识库</label>
                <select
                  id="kb-scope-select"
                  value={selectedKb}
                  onChange={(event) => setSelectedKb(event.target.value)}
                >
                  <option value="all">全部可访问知识库</option>
                  {bases.map((base) => (
                    <option key={base.id} value={base.id}>
                      {base.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setPaletteOpen(true)} aria-label="打开全局导航">
              ⌘K
            </button>
          </div>
        </header>

        <main className="content" id="main-content" tabIndex={-1}>
          {notice && (
            <div className={notice.kind === "err" ? "notice notice--err" : "notice"} role="status">
              <span>{notice.message}</span>
              <button type="button" onClick={() => setNoticeState(null)} aria-label="关闭提示">
                ×
              </button>
            </div>
          )}
          {view === "home" && <HomeView {...sharedProps} />}
          {view === "ask" && <AskView {...sharedProps} />}
          {view === "search" && <SearchView {...sharedProps} />}
          {view === "knowledge" && <KnowledgeView {...sharedProps} />}
          {view === "retrieval" && <RetrievalView {...sharedProps} />}
          {view === "trace" && <TraceView {...sharedProps} />}
          {view === "evaluation" && <EvaluationView {...sharedProps} />}
          {view === "operations" && <OperationsView {...sharedProps} />}
          {view === "governance" && <GovernanceView {...sharedProps} />}
          {view === "system" && <SystemView {...sharedProps} />}
        </main>
      </div>

      {paletteOpen && (
        <CommandPalette
          user={user}
          onClose={() => setPaletteOpen(false)}
          onJump={(key) => {
            setPaletteOpen(false);
            navigate(key);
          }}
        />
      )}
    </div>
  );
}

function CommandPalette({
  user,
  onClose,
  onJump,
}: {
  user: User;
  onClose: () => void;
  onJump: (key: ViewKey) => void;
}) {
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const query = filter.trim().toLowerCase();
  const sections = visibleSections(user)
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) =>
          !query ||
          item.zh.toLowerCase().includes(query) ||
          section.zh.toLowerCase().includes(query),
      ),
    }))
    .filter((section) => section.items.length > 0);

  return (
    <div
      className="modal-backdrop"
      style={{ alignItems: "flex-start" }}
      role="dialog"
      aria-modal="true"
      aria-label="全局导航"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="palette">
        <input
          ref={ref}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="跳转到… 输入首页 / 问答 / 检索 / 知识库 / 请求追踪"
          aria-label="过滤导航项"
        />
        <div style={{ maxHeight: "50vh", overflowY: "auto", paddingBottom: 8 }}>
          {sections.map((section) => (
            <div key={section.idx}>
              <div className="grp">
                <Kicker>{`${section.idx} ${section.zh}`}</Kicker>
              </div>
              {section.items.map((item) => (
                <button key={item.key} type="button" className="item" onClick={() => onJump(item.key)}>
                  <span>
                    <span className="mono" style={{ fontSize: 11, color: "var(--ink-40)", marginRight: 10 }}>
                      {item.idx}
                    </span>
                    {item.zh}
                  </span>
                  <span className="keys">
                    <kbd>↵</kbd>
                  </span>
                </button>
              ))}
            </div>
          ))}
          {!sections.length && (
            <div className="grp">
              <span className="meta">无匹配结果</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LoginScreen({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const accounts = [
    { role: "管理员", username: "admin", password: "admin123", access: "全部知识 · 治理 · 系统" },
    { role: "销售", username: "sales01", password: "sales123", access: "公共 / 产品 / 销售 / 售后" },
    { role: "人事", username: "hr01", password: "hr123", access: "公共 / 人事" },
    { role: "普通用户", username: "user", password: "user123", access: "公共知识，可问答" },
    { role: "访客", username: "viewer", password: "viewer123", access: "只读，不可问答" },
  ];

  const submit = async () => {
    setRunning(true);
    setError("");
    try {
      const result = await api.login(username, password);
      onLogin(result.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth-left dark">
        <div className="side-brand" style={{ padding: 0 }}>
          <span className="mark" style={{ background: "#fff", color: "var(--dark)" }} aria-hidden="true">Y</span>
          <div>
            <strong style={{ color: "#fff" }}>yaoke</strong>
            <span style={{ color: "rgba(255,255,255,0.45)" }}>企业知识操作系统</span>
          </div>
        </div>
        <h1 className="display display--xl" style={{ color: "#fff", marginTop: "var(--s16)" }}>
          向企业提问，
          <br />
          答案可溯源。
        </h1>
        <p style={{ color: "rgba(255,255,255,0.6)", maxWidth: 520, marginTop: "var(--s6)", fontSize: 15 }}>
          多知识库隔离 · 检索前访问控制过滤 · 向量 + BM25 混合检索 + 重排序 · 引用可溯源 · 评测与失败闭环。
        </p>
        <div className="flow">
          {["来源", "知识", "检索", "证据", "回答", "反馈", "评测", "改进"].map((step) => (
            <span key={step}>{step}</span>
          ))}
        </div>
      </section>

      <section className="auth-right">
        <form
          className="auth-card"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <Kicker>登录</Kicker>
          <h1>进入演示工作区</h1>
          <p className="muted" style={{ fontSize: 13, marginBottom: "var(--s6)" }}>
            切换角色可验证知识库隔离与权限导航。
          </p>
          <div className="field">
            <label htmlFor="login-user">用户名</label>
            <input
              id="login-user"
              className="input"
              value={username}
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="field mt-4">
            <label htmlFor="login-pass">密码</label>
            <input
              id="login-pass"
              className="input"
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && (
            <p className="mt-4" role="alert" style={{ color: "var(--err)", fontSize: 13 }}>
              {error}
            </p>
          )}
          <button type="submit" className="btn btn--primary btn--full mt-6" disabled={running}>
            {running ? "登录中…" : "登录"}
          </button>

          <div className="mt-8">
            <Kicker>演示账号</Kicker>
            <div style={{ display: "grid", gap: 2, marginTop: "var(--s3)" }}>
              {accounts.map((account) => (
                <button
                  key={account.username}
                  type="button"
                  className={username === account.username ? "nav-item active" : "nav-item"}
                  onClick={() => {
                    setUsername(account.username);
                    setPassword(account.password);
                    setError("");
                  }}
                >
                  <span>{account.role}</span>
                  <span className="zh">{account.username}</span>
                </button>
              ))}
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}

function BootScreen() {
  return (
    <div className="boot" aria-busy="true" aria-label="正在加载工作区">
      <span className="pulse" aria-hidden="true" />
      <strong>yaoke · 企业知识操作系统</strong>
      <span style={{ color: "rgba(255,255,255,0.5)" }}>正在加载工作区…</span>
    </div>
  );
}
