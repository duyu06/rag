"use client";

import { useEffect, useState } from "react";
import { AgentMode, agentModePreference, session } from "@/lib/api";

const MODES: Array<{ value: AgentMode; label: string; hint: string }> = [
  { value: "local", label: "本地", hint: "只允许企业知识库工具；问题不会发送到公共搜索服务" },
  { value: "auto", label: "自动", hint: "由 Ornith 判断使用企业检索、联网搜索或直接回答" },
  { value: "web", label: "联网", hint: "允许企业检索和 Web Search，并优先处理当前/外部信息" },
];

export default function AgentModeToggle() {
  const [visible, setVisible] = useState(false);
  const [mode, setMode] = useState<AgentMode>("auto");

  useEffect(() => {
    const sync = () => {
      setVisible(session.hasToken());
      setMode(agentModePreference.get());
    };
    sync();
    window.addEventListener("yaoke-auth", sync);
    window.addEventListener(agentModePreference.event, sync);
    return () => {
      window.removeEventListener("yaoke-auth", sync);
      window.removeEventListener(agentModePreference.event, sync);
    };
  }, []);

  if (!visible) return null;

  return (
    <div
      aria-label="Agent 运行模式"
      style={{
        position: "fixed",
        left: 18,
        bottom: 18,
        zIndex: 1001,
        display: "flex",
        gap: 4,
        padding: 4,
        border: "1px solid #d0d5dd",
        borderRadius: 12,
        background: "rgba(255,255,255,.96)",
        boxShadow: "0 8px 24px rgba(16,24,40,.12)",
      }}
    >
      {MODES.map((item) => {
        const active = item.value === mode;
        return (
          <button
            key={item.value}
            type="button"
            title={item.hint}
            onClick={() => {
              agentModePreference.set(item.value);
              setMode(item.value);
            }}
            style={{
              border: active ? "1px solid #1570ef" : "1px solid transparent",
              borderRadius: 8,
              padding: "7px 10px",
              background: active ? "#eff8ff" : "transparent",
              color: active ? "#175cd3" : "#475467",
              fontSize: 12,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
