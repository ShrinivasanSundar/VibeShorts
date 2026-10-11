import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "../components/providers";

const bodyFont = localFont({
  src: [
    { path: "./fonts/dm-sans-400.ttf", weight: "400" },
    { path: "./fonts/dm-sans-500.ttf", weight: "500" },
    { path: "./fonts/dm-sans-600.ttf", weight: "600" },
    { path: "./fonts/dm-sans-700.ttf", weight: "700" },
  ], variable: "--font-body", display: "swap",
});
const headingFont = localFont({
  src: [
    { path: "./fonts/space-grotesk-400.ttf", weight: "400" },
    { path: "./fonts/space-grotesk-500.ttf", weight: "500" },
    { path: "./fonts/space-grotesk-600.ttf", weight: "600" },
    { path: "./fonts/space-grotesk-700.ttf", weight: "700" },
  ], variable: "--font-heading", display: "swap",
});

export const metadata: Metadata = { title: "VibeShortsAI — Your creative studio", description: "Turn your ideas into cinematic AI shorts. Your workspace for stories, visual explainers, and product videos." };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en" className={`${bodyFont.variable} ${headingFont.variable}`}><body><Providers>{children}</Providers></body></html>;
}
