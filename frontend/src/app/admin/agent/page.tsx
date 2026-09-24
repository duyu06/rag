"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Kicker } from "@/components/ui";

export default function MovedPage() {
  const router = useRouter();
  useEffect(() => {
    const timer = setTimeout(() => router.replace("/"), 1200);
    return () => clearTimeout(timer);
  }, [router]);
  return (
    <div className="boot" aria-live="polite">
      <Kicker accent>已迁移</Kicker>
      <strong style={{ fontFamily: "var(--sans)", fontSize: 18 }}>智能体追踪已并入工作区</strong>
      <span style={{ color: "rgba(255,255,255,0.5)" }}>正在跳转到 06 请求追踪…</span>
    </div>
  );
}
