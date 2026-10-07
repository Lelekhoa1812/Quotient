/**
 * Motivation vs Logic
 * Motivation: Pirulen and Montserrat must be self-hosted. The shell wordmark
 * is the only place the product name is set in the display face. The tab icon
 * is Axion's mark.
 * Logic: next/font/local emits the woff2 files from this app. CSS variables
 * carry the families into the global sheet.
 */
import type { Metadata } from "next";
import localFont from "next/font/local";
import Script from "next/script";
import { Shell } from "@/components/shell";
import "./globals.css";

const montserrat = localFont({
  src: [
    { path: "../fonts/montserrat-400.woff2", weight: "400", style: "normal" },
    { path: "../fonts/montserrat-600.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-montserrat",
  display: "swap",
  adjustFontFallback: "Arial",
});

const pirulen = localFont({
  src: "../fonts/pirulen-subset.woff2",
  weight: "400",
  style: "normal",
  variable: "--font-pirulen",
  display: "swap",
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: { default: "Quotient", template: "%s · Quotient" },
  description: "Quotient meeting intelligence",
  icons: {
    icon: [{ url: "/mark.jpg", type: "image/jpeg", sizes: "200x200" }],
    apple: [{ url: "/mark.jpg", type: "image/jpeg", sizes: "200x200" }],
    shortcut: ["/mark.jpg"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${montserrat.variable} ${pirulen.variable}`}>
      <body>
        <Script id="quotient-theme" strategy="beforeInteractive">
          {`try{var t=localStorage.getItem("quotient-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}catch(e){}`}
        </Script>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
