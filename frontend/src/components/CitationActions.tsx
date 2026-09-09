"use client";

import { useEffect } from "react";
import { api } from "@/lib/api";

const KB_NAME_TO_ID: Record<string, string> = {
  "公共制度": "kb_public",
  "HR 知识库": "kb_hr",
  "产品知识库": "kb_product",
  "销售知识库": "kb_sales",
  "售后知识库": "kb_service",
};

/**
 * Progressive enhancement for the existing citation cards.
 * Keeping this cross-cutting action here avoids coupling source-file transport to the chat UI.
 */
export default function CitationActions() {
  useEffect(() => {
    let stopped = false;

    const decorate = () => {
      if (stopped) return;
      document.querySelectorAll<HTMLElement>(".source-card").forEach((card) => {
        if (card.dataset.sourceActionReady === "1") return;
        const fileName = card.querySelector("strong")?.textContent?.trim();
        const kbName = card.querySelector<HTMLElement>(".kb-tag")?.textContent?.trim();
        const kbId = kbName ? KB_NAME_TO_ID[kbName] : undefined;
        if (!fileName || !kbId) return;

        const body = card.querySelector("div:last-child");
        if (!body) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "link-btn nexuskb-source-open";
        button.textContent = "查看原文";
        button.style.marginTop = "6px";
        button.addEventListener("click", async () => {
          button.disabled = true;
          const old = button.textContent;
          button.textContent = "打开中…";
          try {
            await api.openSource(kbId, fileName);
          } catch (error) {
            window.alert(error instanceof Error ? error.message : "来源文件打开失败");
          } finally {
            button.disabled = false;
            button.textContent = old;
          }
        });
        body.appendChild(button);
        card.dataset.sourceActionReady = "1";
      });
    };

    decorate();
    const observer = new MutationObserver(decorate);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      stopped = true;
      observer.disconnect();
    };
  }, []);

  return null;
}
