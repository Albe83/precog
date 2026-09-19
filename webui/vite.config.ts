import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

export default defineConfig({
  resolve: {
    alias: {
      // Consume the SDK source directly (single source of truth in the monorepo).
      "@precog/sdk": fileURLToPath(new URL("../packages/sdk-ts/src/index.ts", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Dev: forward API calls to the local API (same-origin from the browser).
    proxy: { "/v1": "http://localhost:8000" },
  },
});
