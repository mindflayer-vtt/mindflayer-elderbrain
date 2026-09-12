import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./test/browser",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:18081" },
  webServer: {
    command: "node --import tsx test/browser-server.ts",
    url: "http://127.0.0.1:18081/elderbrain/health",
    timeout: 30000,
  },
});
