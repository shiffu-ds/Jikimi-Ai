// Static export: the FastAPI server serves apps/dashboard/out (no Node process at runtime,
// ~384 MB RAM saved on the 12 GB laptop). In `next dev`, API calls are proxied to :8000.
const isDev = process.env.NODE_ENV !== "production";
const api = process.env.JIKIMI_API_ORIGIN ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const config = {
  output: isDev ? undefined : "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
  ...(isDev
    ? {
        async rewrites() {
          return [
            { source: "/v1/:path*", destination: `${api}/v1/:path*` },
          ];
        },
      }
    : {}),
};

export default config;
