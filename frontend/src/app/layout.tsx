import type { Metadata } from "next";
import AdminQuickLinks from "@/components/AdminQuickLinks";
import AgentModeToggle from "@/components/AgentModeToggle";
import CitationActions from "@/components/CitationActions";
import ConversationExperience from "@/components/ConversationExperience";
import DashboardMetrics from "@/components/DashboardMetrics";
import DemoTools from "@/components/DemoTools";
import "./globals.css";

export const metadata: Metadata = {
  title: "yaoke",
  description: "yaoke · 企业 AI 知识与 Agent 平台",
  icons: {
    icon: "/yaoke-logo.webp",
    shortcut: "/yaoke-logo.webp",
    apple: "/yaoke-logo.webp",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        {children}
        <ConversationExperience />
        <AdminQuickLinks />
        <CitationActions />
        <DashboardMetrics />
        <DemoTools />
        <AgentModeToggle />
      </body>
    </html>
  );
}
