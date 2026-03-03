import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polybot Dashboard",
  description: "Real-time trading dashboard for Polymarket bot",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-[#080a0e] text-zinc-200 antialiased">
        {children}
      </body>
    </html>
  );
}
