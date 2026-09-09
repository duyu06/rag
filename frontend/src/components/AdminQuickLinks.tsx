"use client";

import { useCallback, useEffect, useState } from "react";
import { api, session, User } from "@/lib/api";

export default function AdminQuickLinks() {
  const [user, setUser] = useState<User | null>(null);

  const sync = useCallback(async () => {
    if (!session.hasToken()) {
      setUser(null);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    void sync();
    window.addEventListener("nexuskb-auth", sync);
    return () => window.removeEventListener("nexuskb-auth", sync);
  }, [sync]);

  if (user?.role !== "ADMIN") return null;

  return (
    <nav style={{ position: "fixed", right: 18, top: 88, zIndex: 998, display: "flex", gap: 6 }} aria-label="管理员快捷入口">
      <a href="/admin/agent" style={linkStyle}>Agent Trace</a>
      <a href="/admin/evaluation" style={linkStyle}>四路评测</a>
      <a href="/admin/audit" style={linkStyle}>审计日志</a>
    </nav>
  );
}

const linkStyle: React.CSSProperties = {
  padding: "7px 10px",
  borderRadius: 8,
  border: "1px solid #d0d5dd",
  background: "rgba(255,255,255,.94)",
  color: "#344054",
  textDecoration: "none",
  fontSize: 11,
  boxShadow: "0 6px 18px rgba(16,24,40,.08)",
};
