import type { NextConfig } from "next";

const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").origin;
const emulator = process.env.NEXT_PUBLIC_MODE !== "production";
const csp = [
  "default-src 'self'", "script-src 'self' 'unsafe-inline' https://apis.google.com" + (emulator ? " 'unsafe-eval'" : ""),
  "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob: https://lh3.googleusercontent.com",
  `connect-src 'self' ${apiOrigin} https://*.googleapis.com https://*.firebaseapp.com` +
    (emulator ? " http://127.0.0.1:* http://localhost:* ws://127.0.0.1:*" : ""),
  "media-src 'self' data: blob:", "font-src 'self' data:", "frame-src 'self' blob: data: https://*.firebaseapp.com https://accounts.google.com" + (emulator ? " http://127.0.0.1:9099" : ""),
  "frame-ancestors 'none'", "base-uri 'self'", "object-src 'none'",
].join("; ");

const config: NextConfig = {
  poweredByHeader: false,
  output: "standalone",
  async headers() {
    return [{ source: "/(.*)", headers: [
      { key: "Content-Security-Policy", value: csp },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Cache-Control", value: "no-store" },
    ] }];
  },
};
export default config;
