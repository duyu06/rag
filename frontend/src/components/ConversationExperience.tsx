"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import ConversationChatPanel from "@/components/ConversationChatPanel";
import { KnowledgeBase } from "@/lib/api";

function readKnowledgeSelector(): { selectedKb: string; bases: KnowledgeBase[]; signature: string } {
  const select = document.querySelector<HTMLSelectElement>(".kb-filter select");
  if (!select) return { selectedKb: "all", bases: [], signature: "missing" };
  const bases: KnowledgeBase[] = Array.from(select.options)
    .filter((option) => option.value && option.value !== "all")
    .map((option) => ({
      id: option.value,
      name: option.textContent?.trim() || option.value,
      description: "",
      department: "",
    }));
  const selectedKb = select.value || "all";
  const signature = `${selectedKb}|${bases.map((item) => `${item.id}:${item.name}`).join("|")}`;
  return { selectedKb, bases, signature };
}

export default function ConversationExperience() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [selectedKb, setSelectedKb] = useState("all");
  const [bases, setBases] = useState<KnowledgeBase[]>([]);

  useEffect(() => {
    let currentOldChat: HTMLElement | null = null;
    let currentHost: HTMLElement | null = null;
    let currentSelect: HTMLSelectElement | null = null;
    let selectorSignature = "";

    const syncSelector = () => {
      const value = readKnowledgeSelector();
      if (value.signature === selectorSignature) return;
      selectorSignature = value.signature;
      setSelectedKb(value.selectedKb);
      setBases(value.bases);
    };

    const attach = () => {
      const oldChat = document.querySelector<HTMLElement>(".chat-layout");
      const select = document.querySelector<HTMLSelectElement>(".kb-filter select");

      if (select !== currentSelect) {
        currentSelect?.removeEventListener("change", syncSelector);
        currentSelect = select;
        currentSelect?.addEventListener("change", syncSelector);
        selectorSignature = "";
      }
      syncSelector();

      if (!oldChat) {
        if (currentHost && !currentHost.isConnected) {
          setHost(null);
          currentHost = null;
          currentOldChat = null;
        }
        return;
      }
      if (oldChat === currentOldChat && currentHost?.isConnected) return;

      if (currentOldChat) currentOldChat.style.removeProperty("display");
      currentHost?.remove();

      currentOldChat = oldChat;
      oldChat.style.display = "none";
      const wrapper = oldChat.parentElement;
      if (!wrapper) return;

      currentHost = document.createElement("div");
      currentHost.dataset.yaokeConversationHost = "true";
      wrapper.appendChild(currentHost);
      setHost(currentHost);
    };

    attach();
    const observer = new MutationObserver(attach);
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      currentSelect?.removeEventListener("change", syncSelector);
      if (currentOldChat) currentOldChat.style.removeProperty("display");
      currentHost?.remove();
    };
  }, []);

  if (!host) return null;
  return createPortal(
    <ConversationChatPanel selectedKb={selectedKb} bases={bases} />,
    host,
  );
}
