import type { Metadata } from "next";
import CitationActions from "@/components/CitationActions";
import DashboardMetrics from "@/components/DashboardMetrics";
import DemoTools from "@/components/DemoTools";
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
        <CitationActions />
        <DashboardMetrics />
        <DemoTools />
      </body>
    </html>
  );
}
