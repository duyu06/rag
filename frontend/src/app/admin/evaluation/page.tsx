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
      <strong style={{ fontFamily: "var(--sans)", fontSize: 18 }}>评测运行已并入评测板块</strong>
      <span style={{ color: "rgba(255,255,255,0.5)" }}>正在跳转到 07 评测…</span>
    </div>
  );
}
