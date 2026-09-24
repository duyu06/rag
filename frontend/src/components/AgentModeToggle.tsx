"use client";

import { useEffect, useState } from "react";
import { AgentMode, agentModePreference, session } from "@/lib/api";

const MODES: Array<{ value: AgentMode; label: string; hint: string }> = [
  { value: "local", label: "本地", hint: "只允许企业知识库工具；问题不会发送到公共搜索服务" },
  { value: "auto", label: "自动", hint: "由 Ornith 判断使用企业检索、联网搜索或直接回答" },
  { value: "web", label: "联网", hint: "允许企业检索与网页搜索，并优先处理时效性和外部信息" },
];

export default function AgentModeToggle({ embedded = false }: { embedded?: boolean }) {
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
      className={embedded ? "agent-mode-toggle embedded" : "agent-mode-toggle"}
      aria-label="智能体运行模式"
    >
      {MODES.map((item) => {
        const active = item.value === mode;
        return (
          <button
            key={item.value}
            type="button"
            title={item.hint}
            aria-pressed={active}
            onClick={() => {
              agentModePreference.set(item.value);
              setMode(item.value);
            }}
            className={active ? "active" : ""}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
