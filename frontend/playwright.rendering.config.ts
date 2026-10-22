import { defineConfig } from "@playwright/test"
import base from "./playwright.config"

const production = process.env.TL198_PRODUCTION === "1"
const port = production ? 5298 : 5198
const outDir = process.env.TL198_DIST ?? "dist"

export default defineConfig({
  ...base,
  testMatch: process.env.TL198_FULL_SUITE === "1" ? undefined : "rendering-hygiene.spec.ts",
  workers: 1,
  outputDir: process.env.TL198_OUTPUT ?? "../tmp/rendering-tests",
  use: {
    ...base.use,
    baseURL: `http://127.0.0.1:${port}`,
    // Trace snapshots walk the entire chart DOM on every action. Keep that
    // instrumentation out of production interaction measurements.
    trace: production ? "off" : "retain-on-failure",
    video: production ? "off" : "retain-on-failure",
    screenshot: production ? "off" : "only-on-failure",
  },
  webServer: {
    command: `npm run ${production ? "preview" : "dev"} -- --host 127.0.0.1 --port ${port} --strictPort${production ? ` --outDir ${outDir}` : ""}`,
    url: `http://127.0.0.1:${port}/login`,
    reuseExistingServer: false,
  },
})
