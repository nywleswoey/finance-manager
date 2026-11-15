import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // `@/x` is `src/x`: a module under src/modules/*/ names a shared piece without counting `../`
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { outDir: "dist" },
  server: { proxy: { "/api": "http://localhost:8000", "/ingest": "http://localhost:8000" } },
});
