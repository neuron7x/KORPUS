import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const localChromium = process.env.KORPUS_CHROMIUM_PATH ?? "/snap/bin/chromium";
const liveBaseURL = process.env.KORPUS_LIVE_WEB_URL;

export default defineConfig({
  testDir: "./tests",
  outputDir: liveBaseURL
    ? "../../var/web-act/live-boundary-playwright"
    : "../../var/web-act/playwright",
  reporter: [
    ["line"],
    [
      "junit",
      {
        outputFile: liveBaseURL
          ? "../../var/web-act/live-boundary-junit.xml"
          : "../../var/web-act/browser-junit.xml",
      },
    ],
  ],
  forbidOnly: true,
  retries: 0,
  workers: 1,
  use: {
    baseURL: liveBaseURL ?? "http://127.0.0.1:3177",
    browserName: "chromium",
    launchOptions: existsSync(localChromium)
      ? { executablePath: localChromium }
      : {},
    trace: liveBaseURL ? "off" : "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: liveBaseURL ? undefined : {
    command: "npm run build && PORT=3177 node scripts/serve.mjs dist",
    port: 3177,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
