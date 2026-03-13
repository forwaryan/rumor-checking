import path from "node:path";
import type { NextConfig } from "next";

const backendProxyTarget = (process.env.BACKEND_PROXY_TARGET ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  experimental: {
    externalDir: true,
  },
  outputFileTracingRoot: path.join(process.cwd(), ".."),
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendProxyTarget}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
