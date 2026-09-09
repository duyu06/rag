"use client";

import { useEffect, useState } from "react";
import { session, webSearchPreference } from "@/lib/api";

export default function WebSearchToggle() {
  const [visible, setVisible] = useState(false);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const sync = () => {
      setVisible(session.hasToken());
      setEnabled(webSearchPreference.enabled());
    };
    sync();
    window.addEventListener("nexuskb-auth", sync);
    window.addEventListener("nexuskb-web-search", sync);
    return () => {
      window.removeEventListener("nexuskb-auth", sync);
      window.removeEventListener("nexuskb-web-search", sync);
    };
  }, []);

  if (!visible) return null;

  const toggle = () => {
    const next = !enabled;
    webSearchPreference.set(next);
    setEnabled(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      title={enabled ? "当前提问会同时执行互联网搜索；企业知识库证据仍优先" : "开启后，当前提问会增加互联网搜索证据"}
      style={{
        position: "fixed",
        left: 18,
        bottom: 18,
        zIndex: 1001,
        border: enabled ? "1px solid #1570ef" : "1px solid #d0d5dd",
        borderRadius: 999,
        background: enabled ? "#eff8ff" : "#ffffff",
        color: enabled ? "#175cd3" : "#344054",
        padding: "9px 13px",
        fontSize: 12,
        fontWeight: 700,
        cursor: "pointer",
        boxShadow: "0 8px 24px rgba(16,24,40,.12)",
      }}
    >
      {enabled ? "🌐 联网搜索 · ON" : "🌐 联网搜索 · OFF"}
    </button>
  );
}
