import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // Load every variable, not only VITE_*: the routing key must stay on the dev
  // server and never be inlined into the bundle.
  const env = loadEnv(mode, ".", "");
  const routingKey = env.DGIS_ROUTING_KEY || env.VITE_2GIS_DIRECTIONS_KEY || env.VITE_2GIS_KEY || "";

  return {
    plugins: [react()],
    server: {
      host: "localhost",
      port: 5173,
      proxy: {
        "/api": { target: env.API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true },
        // Same contract as nginx in Docker: strip the prefix, add the key.
        "/dgis-routing": {
          target: "https://routing.api.2gis.com",
          changeOrigin: true,
          rewrite: (path) => {
            const upstream = path.replace(/^\/dgis-routing/, "");
            return `${upstream}${upstream.indexOf("?") >= 0 ? "&" : "?"}key=${encodeURIComponent(routingKey)}`;
          },
        },
      },
    },
  };
});
