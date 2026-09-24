import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "yaoke · 企业知识操作系统",
  description: "yaoke · 企业知识库：问答 / 检索 / 证据 / 评测 / 治理",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        {children}
      </body>
    </html>
  );
}
