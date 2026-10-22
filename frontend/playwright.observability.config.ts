import { defineConfig } from "@playwright/test"
import { tmpdir } from "node:os"
import { join } from "node:path"
import base from "./playwright.config"

const output = join(tmpdir(), `talisman-observability-${process.pid}`)

export default defineConfig({
  ...base,
  testDir: "./tests/observability",
  use: { ...base.use, baseURL: "http://127.0.0.1:5179" },
  webServer: {
    command: `npm run build -- --outDir ${output} && npm run preview -- --host 127.0.0.1 --port 5179 --strictPort --outDir ${output}`,
    url: "http://127.0.0.1:5179/login",
    reuseExistingServer: false,
    env: {
      VITE_SENTRY_DSN: "https://public@sentry.invalid/123",
      VITE_SENTRY_ENABLED: "true",
      VITE_SENTRY_TRACES_SAMPLE_RATE: "1",
      VITE_SENTRY_ENVIRONMENT: "test",
      VITE_SENTRY_RELEASE: "tl-179-browser-test",
    },
  },
})
