import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Context Router",
  description: "项目上下文与数据库 MCP 管理工作台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
