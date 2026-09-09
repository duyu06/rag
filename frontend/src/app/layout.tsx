import type { Metadata } from "next";
import AdminQuickLinks from "@/components/AdminQuickLinks";
import CitationActions from "@/components/CitationActions";
import DashboardMetrics from "@/components/DashboardMetrics";
import DemoTools from "@/components/DemoTools";
import WebSearchToggle from "@/components/WebSearchToggle";
import "./globals.css";

export const metadata: Metadata = {
  title: "NexusKB · 企业 AI 知识中台",
  description: "Hybrid RAG Knowledge Platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        {children}
        <AdminQuickLinks />
        <CitationActions />
        <DashboardMetrics />
        <DemoTools />
        <WebSearchToggle />
      </body>
    </html>
  );
}
