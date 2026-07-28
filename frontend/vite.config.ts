import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Read .env from the repo root, not frontend/, so there is one env file for
  // the whole project (docker compose already loads that same file). Only
  // VITE_-prefixed vars are ever exposed to client code, so the backend secrets
  // living alongside them (ORCID_CLIENT_SECRET, ANTHROPIC_API_KEY, …) stay out
  // of the bundle.
  envDir: "..",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
