import { defineConfig } from "@playwright/test"
import base from "./playwright.config"

export default defineConfig({
  ...base,
  testMatch: process.env.TL203_FULL_SUITE === "1" ? undefined : "fetch-polish.spec.ts",
  workers: 1,
  outputDir: "../tmp/fetch-polish-tests",
  use: { ...base.use, baseURL: "http://127.0.0.1:5203" },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5203 --strictPort",
    url: "http://127.0.0.1:5203/login",
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
