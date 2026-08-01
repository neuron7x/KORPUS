import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const localChromium = process.env.KORPUS_CHROMIUM_PATH ?? "/snap/bin/chromium";

export default defineConfig({
  testDir: "./tests",
  outputDir: "../../var/web-act/playwright",
  reporter: [
    ["line"],
    ["junit", { outputFile: "../../var/web-act/browser-junit.xml" }],
  ],
  forbidOnly: true,
  retries: 0,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3177",
    browserName: "chromium",
    launchOptions: existsSync(localChromium)
      ? { executablePath: localChromium }
      : {},
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run build && PORT=3177 node scripts/serve.mjs dist",
    port: 3177,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
