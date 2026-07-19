import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "文档树",
  description: "以 AGENTS.md 为入口的递归文档索引",
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

