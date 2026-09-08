import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "追番助手",
  description: "放送日历 · 季度新番 · 追番清单 · AI 推荐",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const navItems = [
    { href: "/", label: "放送日历" },
    { href: "/seasons", label: "季度新番" },
    { href: "/tracking", label: "我的追番" },
    { href: "/recommend", label: "AI 推荐" },
  ];
  return (
    <html
      lang="zh-CN"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <header
          style={{
            borderBottom: "1px solid #E4E3DD",
            background: "#FFFFFF",
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <nav
            style={{
              maxWidth: 960,
              margin: "0 auto",
              padding: "0 16px",
              display: "flex",
              gap: 20,
              alignItems: "center",
              height: 48,
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 15 }}>追番助手</span>
            {navItems.map((item) => (
              <a
                key={item.href}
                href={item.href}
                style={{ fontSize: 14, color: "#4B5563", textDecoration: "none" }}
              >
                {item.label}
              </a>
            ))}
          </nav>
        </header>
        <main style={{ flex: 1 }}>{children}</main>
      </body>
    </html>
  );
}
