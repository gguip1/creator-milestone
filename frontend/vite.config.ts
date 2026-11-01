import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The FastAPI backend serves /api; in production both share one origin.
    proxy: { "/api": "http://localhost:8000" },
  },
});
