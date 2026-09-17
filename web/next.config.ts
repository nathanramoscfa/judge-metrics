// web/next.config.ts
// `output: "standalone"` emits the self-contained server that
// infra/docker/web.Dockerfile copies into the runtime image. The web tier
// sets no cookies, loads no third-party script, and sends only the headers
// below on top of Next.js defaults.
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
