"use client";

import { useEffect, useState } from "react";
import { session } from "@/lib/api";

const WEB_SEARCH_KEY = "nexuskb_web_search_enabled";
const WEB_SEARCH_MARKER = "[[NEXUS_WEB_SEARCH]]";
const WEB_SEARCH_EVENT = "nexuskb-web-search";

function preferenceEnabled() {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(WEB_SEARCH_KEY) === "1";
}

function setPreference(value: boolean) {
  localStorage.setItem(WEB_SEARCH_KEY, value ? "1" : "0");
  window.dispatchEvent(new Event(WEB_SEARCH_EVENT));
}

function shouldDecorateRequest(input: RequestInfo | URL) {
  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  return url.includes("/api/query") && !url.includes("/api/retrieval/");
}

export default function WebSearchToggle() {
  const [visible, setVisible] = useState(false);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const sync = () => {
      setVisible(session.hasToken());
      setEnabled(preferenceEnabled());
    };
    sync();
    window.addEventListener("nexuskb-auth", sync);
    window.addEventListener(WEB_SEARCH_EVENT, sync);
    return () => {
      window.removeEventListener("nexuskb-auth", sync);
      window.removeEventListener(WEB_SEARCH_EVENT, sync);
    };
  }, []);

  useEffect(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      if (!preferenceEnabled() || !shouldDecorateRequest(input) || typeof init?.body !== "string") {
        return originalFetch(input, init);
      }
      try {
        const payload = JSON.parse(init.body);
        if (typeof payload.question === "string" && !payload.question.startsWith(WEB_SEARCH_MARKER)) {
          const nextInit: RequestInit = {
            ...init,
            body: JSON.stringify({
              ...payload,
              question: `${WEB_SEARCH_MARKER} ${payload.question}`,
            }),
          };
          return originalFetch(input, nextInit);
        }
      } catch {
        // Non-JSON request: leave it untouched.
      }
      return originalFetch(input, init);
    };
    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  if (!visible) return null;

  const toggle = () => {
    const next = !enabled;
    setPreference(next);
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
