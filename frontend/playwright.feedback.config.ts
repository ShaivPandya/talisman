import { defineConfig } from "@playwright/test"
import base from "./playwright.config"

export default defineConfig({
  ...base,
  testMatch: process.env.TL216_FULL_SUITE === "1" ? undefined : "agent-chat-feedback.spec.ts",
  workers: 1,
  outputDir: "../tmp/feedback-tests",
  use: { ...base.use, baseURL: "http://127.0.0.1:5216" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5216 --strictPort",
    url: "http://127.0.0.1:5216/login",
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
