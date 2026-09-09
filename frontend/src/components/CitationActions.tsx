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

function webUrlFromCard(card: HTMLElement): string | null {
  const kbName = card.querySelector<HTMLElement>(".kb-tag")?.textContent?.trim() || "";
  if (!kbName.startsWith("Web ·")) return null;
  const text = card.querySelector("p")?.textContent || "";
  const match = text.match(/https?:\/\/[^\s]+/i);
  if (!match) return null;
  try {
    const url = new URL(match[0]);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

/**
 * Progressive enhancement for citation cards.
 * Enterprise evidence re-checks backend KB ACL before opening a source file.
 * Web evidence only links to the already sanitized public URL returned by the backend.
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
        const body = card.querySelector("div:last-child");
        if (!body || !fileName) return;

        const webUrl = webUrlFromCard(card);
        if (webUrl) {
          const link = document.createElement("a");
          link.className = "link-btn yaoke-web-source-open";
          link.textContent = "打开网页";
          link.href = webUrl;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.style.display = "inline-block";
          link.style.marginTop = "6px";
          body.appendChild(link);
          card.dataset.sourceActionReady = "1";
          return;
        }

        const kbId = kbName ? KB_NAME_TO_ID[kbName] : undefined;
        if (!kbId) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "link-btn yaoke-source-open";
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
