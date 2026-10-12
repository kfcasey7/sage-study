import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, run the backend (python -m sage.dev) and `npm run dev`; API calls are proxied.
export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: true } },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 6000,
    target: "es2021",
  },
  worker: { format: "es" },
});
