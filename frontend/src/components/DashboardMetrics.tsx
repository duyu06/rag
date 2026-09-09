"use client";

import { useEffect } from "react";
import { api, session } from "@/lib/api";

/**
 * Hydrates the fourth dashboard metric with real usage data without duplicating
 * the dashboard component's data-loading lifecycle.
 */
export default function DashboardMetrics() {
  useEffect(() => {
    let active = true;
    let timer: number | undefined;

    const hydrate = async () => {
      if (!active || !session.hasToken()) return;
      const cards = Array.from(document.querySelectorAll<HTMLElement>(".metric-grid .metric-card"));
      const target = cards.find((card) => {
        const label = card.querySelector("span")?.textContent?.trim();
        return label === "系统状态" || label === "今日查询";
      });
      if (!target) return;

      try {
        const stats = await api.stats("all");
        if (!active) return;
        const label = target.querySelector("span");
        const value = target.querySelector("strong");
        const desc = target.querySelector("small");
        if (label) label.textContent = "今日查询";
        if (value) value.textContent = String(stats?.today_queries ?? 0);
        if (desc) {
          desc.textContent = `平均 ${Math.round(stats?.avg_query_latency_ms ?? 0)} ms · 拒绝 ${stats?.denied_access ?? 0}`;
        }
      } catch {
        // Dashboard remains usable with its original system-status metric when telemetry is offline.
      }
    };

    const observer = new MutationObserver(() => void hydrate());
    observer.observe(document.body, { childList: true, subtree: true });
    void hydrate();
    timer = window.setInterval(() => void hydrate(), 15_000);
    const authHandler = () => void hydrate();
    window.addEventListener("nexuskb-auth", authHandler);

    return () => {
      active = false;
      observer.disconnect();
      if (timer) window.clearInterval(timer);
      window.removeEventListener("nexuskb-auth", authHandler);
    };
  }, []);

  return null;
}
