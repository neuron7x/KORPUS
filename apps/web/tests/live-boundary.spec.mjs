import { expect, test } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import axe from "axe-core";

const token = process.env.KORPUS_LIVE_BEARER_TOKEN;
const candidateCommit = process.env.KORPUS_LIVE_CANDIDATE_COMMIT;
const apiImageDigest = process.env.KORPUS_LIVE_API_IMAGE_DIGEST;
const webImageDigest = process.env.KORPUS_LIVE_WEB_IMAGE_DIGEST;
const database = JSON.parse(process.env.KORPUS_LIVE_DATABASE_RECEIPT ?? "{}");
const query = process.env.KORPUS_LIVE_QUERY;
const expectedEvidence = process.env.KORPUS_LIVE_EXPECTED_EVIDENCE;
const playwrightPackage = JSON.parse(
  await readFile(new URL("../node_modules/@playwright/test/package.json", import.meta.url), "utf8"),
);

test("@live browser traverses nginx and the real API without storing authority", async ({
  browser,
  page,
  context,
}) => {
  test.skip(!token, "KORPUS_LIVE_BEARER_TOKEN is required for the composed live gate");
  const startedAt = new Date();
  await page.addInitScript(() => {
    window.__korpusLiveMetrics = { cls: 0 };
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__korpusLiveMetrics.cls += entry.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
  await page.addInitScript({ content: axe.source });
  expect(candidateCommit).toMatch(/^[0-9a-f]{40}$/);
  expect(apiImageDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(webImageDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  const browserEnvironment = {
    engine: "chromium",
    version: browser.version(),
    playwright_version: playwrightPackage.version,
    user_agent: await page.evaluate(() => navigator.userAgent),
    device_scale_factor: await page.evaluate(() => window.devicePixelRatio),
    context: "EPHEMERAL_COLD",
  };
  const responses = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/")) responses.push(response);
  });

  await page.goto("/", { waitUntil: "load" });
  await page.getByText("Developer bearer fallback").click();
  await page.getByLabel("Короткоживучий access token").fill(token);
  await page.getByRole("button", { name: "Перевірити", exact: true }).click();
  await expect(page.locator("#identity-state")).toContainText("live-boundary-user");

  const input = page.getByLabel("Запит до контрольованого корпусу");
  await input.fill(query ?? "перевірити відсутність непідтверджених доказів");
  const answerStarted = Date.now();
  await page.getByRole("button", { name: /Знайти доказ/ }).click();
  await expect(page.locator("#result")).toBeVisible();
  await expect(page.locator("#result")).toContainText(/Доказова відповідь|Відмова/);
  if (expectedEvidence) {
    await expect(page.locator("#result")).toContainText(expectedEvidence);
  }
  const answerDurationMs = Date.now() - answerStarted;

  const accessibility = await page.evaluate(async () => {
    const results = await window.axe.run(document, {
      resultTypes: ["violations"],
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
      },
    });
    return {
      serious: results.violations.filter((item) => item.impact === "serious").length,
      critical: results.violations.filter((item) => item.impact === "critical").length,
    };
  });
  expect(accessibility).toEqual({ serious: 0, critical: 0 });

  await page.setViewportSize({ width: 390, height: 844 });
  const quality = await page.evaluate((measuredAnswerDurationMs) => {
    const navigation = performance.getEntriesByType("navigation")[0];
    const lcpEntries = performance.getEntriesByType("largest-contentful-paint");
    const lcp = lcpEntries.at(-1)?.startTime;
    if (!Number.isFinite(lcp)) throw new Error("largest-contentful-paint is unavailable");
    const transferredBytes = performance
      .getEntriesByType("resource")
      .filter((entry) => new URL(entry.name).origin === location.origin)
      .reduce((total, entry) => total + entry.transferSize, 0);
    return {
      layout: {
        viewport_width_css_px: document.documentElement.clientWidth,
        content_width_css_px: document.documentElement.scrollWidth,
        horizontal_overflow_css_px: Math.max(
          0,
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
      },
      performance: {
        measurement: "ANCHORED_LOCAL",
        navigation_ms: navigation.loadEventEnd,
        lcp_ms: lcp,
        cls: window.__korpusLiveMetrics.cls,
        answer_ms: measuredAnswerDurationMs,
        same_origin_transfer_bytes: transferredBytes,
        external_origins: [
          ...new Set(
            performance
              .getEntriesByType("resource")
              .map((entry) => new URL(entry.name).origin)
              .filter((origin) => origin !== location.origin),
          ),
        ],
      },
    };
  }, answerDurationMs);
  expect(quality.layout.horizontal_overflow_css_px).toBe(0);
  expect(quality.performance.external_origins).toEqual([]);
  expect(quality.performance.navigation_ms).toBeLessThanOrEqual(5_000);
  expect(quality.performance.lcp_ms).toBeLessThanOrEqual(4_000);
  expect(quality.performance.cls).toBeLessThanOrEqual(0.1);
  expect(quality.performance.answer_ms).toBeLessThanOrEqual(10_000);
  expect(quality.performance.same_origin_transfer_bytes).toBeLessThanOrEqual(150_000);

  const anonymous = responses.find(
    (response) =>
      response.url().endsWith("/api/v1/auth/me") && response.status() === 401,
  );
  expect(anonymous).toBeTruthy();
  const successful = responses.filter(
    (response) =>
      response.status() === 200 &&
      ["/api/v1/auth/me", "/api/v1/answers"].some((path) =>
        response.url().endsWith(path),
      ),
  );
  expect(successful).toHaveLength(2);
  for (const response of [anonymous, ...successful]) {
    expect(response.headers()["x-request-id"]).toBeTruthy();
    expect(response.headers()["x-content-type-options"]).toBe("nosniff");
    expect(response.headers()["referrer-policy"]).toBe("no-referrer");
    expect(response.headers()["cache-control"]).toBe("no-store");
  }
  const state = await context.storageState();
  expect(state.origins).toEqual([]);
  expect(state.cookies).toEqual([]);

  await page.getByLabel("Короткоживучий access token").fill("invalid-token");
  await page.getByRole("button", { name: "Перевірити", exact: true }).click();
  await expect(page.locator("#identity-state")).toContainText("Відмова: API 401");
  expect(
    responses.find(
      (response) =>
        response.url().endsWith("/api/v1/auth/me") && response.status() === 401,
    ),
  ).toBeTruthy();

  const output = new URL("../../../var/web-act/web-api-live-boundary.json", import.meta.url);
  await mkdir(new URL(".", output), { recursive: true });
  await writeFile(
    output,
    `${JSON.stringify(
      {
        schema: "korpus.web-api-live-boundary.v5",
        act_id: "KORPUS-ACT-09",
        quality_act_id: "KORPUS-ACT-13",
        candidate_commit: candidateCommit,
        started_at_utc: startedAt.toISOString(),
        finished_at_utc: new Date().toISOString(),
        images: {
          api: apiImageDigest,
          web: webImageDigest,
        },
        topology: `chromium -> nginx -> fastapi -> ${database.mode}`,
        database,
        browser: browserEnvironment,
        cases: {
          anonymous_identity: 401,
          jwt_identity: 200,
          answer: 200,
          forged_token: 401,
          security_headers: "PASS",
          browser_authority_storage: "EMPTY",
          evidence_marker: expectedEvidence ? "PASS" : "NOT_APPLICABLE",
        },
        quality: {
          accessibility,
          ...quality,
          budgets: {
            navigation_ms: 5_000,
            lcp_ms: 4_000,
            cls: 0.1,
            answer_ms: 10_000,
            same_origin_transfer_bytes: 150_000,
          },
        },
        limitations: [
          database.mode === "postgres"
            ? "This exercises JWT request identity and PostgreSQL RLS, not production OIDC."
            : "SQLite is not evidence for PostgreSQL RLS behavior.",
          "Ephemeral JWT mode is not production OIDC evidence.",
          "Independent post-change verification is required.",
        ],
        production_authorized: false,
        verdict: "PASS_WITH_CAVEATS",
      },
      null,
      2,
    )}\n`,
    { mode: 0o600 },
  );
});
