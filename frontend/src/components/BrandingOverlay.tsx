"use client";

import { useEffect } from "react";

const BRAND_NAME = "yaoke";
const LOGO_URL = "/yaoke-logo.webp";

function replaceBrandText(root: ParentNode = document.body) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    if (current.nodeValue?.includes("NexusKB")) nodes.push(current as Text);
    current = walker.nextNode();
  }
  nodes.forEach((node) => {
    node.nodeValue = node.nodeValue?.replaceAll("NexusKB", BRAND_NAME) ?? node.nodeValue;
  });
}

function decorateLogoMarks(root: ParentNode = document.body) {
  root.querySelectorAll<HTMLElement>(".brand-mark, .large-mark").forEach((element) => {
    if (element.dataset.yaokeLogoReady === "1") return;
    element.textContent = "";
    element.style.backgroundImage = `url(${LOGO_URL})`;
    element.style.backgroundRepeat = "no-repeat";
    element.style.backgroundPosition = "center";
    element.style.backgroundSize = "contain";
    element.style.backgroundColor = "#fff";
    element.style.borderRadius = "10px";
    element.setAttribute("role", "img");
    element.setAttribute("aria-label", "yaoke logo");
    element.dataset.yaokeLogoReady = "1";
  });
}

export default function BrandingOverlay() {
  useEffect(() => {
    let scheduled = false;
    const apply = () => {
      scheduled = false;
      replaceBrandText();
      decorateLogoMarks();
    };
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      queueMicrotask(apply);
    };

    apply();
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, []);

  return null;
}
