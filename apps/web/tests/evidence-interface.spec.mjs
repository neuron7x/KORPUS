import { expect, test } from "@playwright/test";
import axe from "axe-core";

const identity = {
  subject: "conference-verifier",
  clearance: 0,
  roles: ["user"],
};

async function routeIdentity(page, body = identity) {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

test("keyboard-only query renders escaped evidence and preserves CSRF", async ({
  page,
}) => {
  await routeIdentity(page);
  let received;
  await page.route("**/api/v1/answers", async (route) => {
    received = route.request();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "answered",
        text: "Перевірена відповідь <img src=x onerror=window.__xss=1>",
        retrieval_score: 0.75,
        evidence_coverage: 1,
        corpus_release: "test-release",
        limitations: ["Лабораторний приклад"],
        citations: [
          {
            title: "Безпечне джерело <script>window.__xss=1</script>",
            revision: "1",
            page: "1<img src=x onerror=window.__xss=1>",
            quote: "Точна цитата",
            source_hash: "a".repeat(64),
            span_id: "span-test",
          },
        ],
      }),
    });
  });
  await page.goto("/");
  await page.evaluate(() => {
    document.cookie =
      "__Host-korpus_csrf=test-csrf; Secure; Path=/; SameSite=Strict";
  });
  await page
    .getByLabel("Запит до контрольованого корпусу")
    .fill("Перевірити журнал");
  await page
    .getByLabel("Запит до контрольованого корпусу")
    .press("Control+Enter");
  await expect(
    page.getByRole("heading", { name: "Доказова відповідь" }),
  ).toBeVisible();
  expect(await page.evaluate(() => window.__xss)).toBeUndefined();
  expect(received.headers()["x-csrf-token"]).toBe("test-csrf");
  expect(JSON.parse(received.postData()).text).toBe("Перевірити журнал");
});

test("identity failure remains explicit and stores no authority", async ({
  page,
  context,
}) => {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({ status: 401, body: "" }),
  );
  await page.goto("/");
  await expect(page.getByText("Не автентифіковано.")).toBeVisible();
  const state = await context.storageState();
  expect(state.origins).toEqual([]);
});

test("mobile layout reflows without horizontal disclosure", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeIdentity(page);
  await page.goto("/");
  const geometry = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(geometry.content).toBeLessThanOrEqual(geometry.viewport);
  await expect(page.getByRole("heading", { name: /Перевірити/ })).toBeVisible();
});

test("document has no serious automated accessibility violations", async ({
  page,
}) => {
  await routeIdentity(page);
  await page.goto("/");
  await page.addScriptTag({ content: axe.source });
  const results = await page.evaluate(async () =>
    window.axe.run(document, {
      resultTypes: ["violations"],
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
      },
    }),
  );
  const serious = results.violations.filter((item) =>
    ["serious", "critical"].includes(item.impact),
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});

test("a stalled answer request fails closed after the bounded timeout", async ({
  page,
}) => {
  await page.clock.install();
  await routeIdentity(page);
  await page.route("**/api/v1/answers", () => new Promise(() => {}));
  await page.goto("/");
  await page
    .getByLabel("Запит до контрольованого корпусу")
    .fill("Завислий запит");
  await page.getByRole("button", { name: /Знайти доказ/ }).click();
  await page.clock.fastForward(16_000);
  await expect(page.getByRole("heading", { name: "Помилка" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Знайти доказ/ }),
  ).toBeEnabled();
});

test("installed shell remains usable offline without substituting HTML for assets", async ({
  page,
  context,
}) => {
  await routeIdentity(page);
  await page.goto("/");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      await new Promise((resolve) =>
        navigator.serviceWorker.addEventListener("controllerchange", resolve, {
          once: true,
        }),
      );
    }
  });
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: /Перевірити/ })).toBeVisible();
  const missingAsset = await page.evaluate(async () => {
    try {
      const response = await fetch("/not-a-shell-asset.css");
      return { ok: response.ok, type: response.headers.get("content-type") };
    } catch {
      return { ok: false, type: null };
    }
  });
  expect(missingAsset.ok).toBe(false);
  expect(missingAsset.type ?? "").not.toContain("text/html");
});

test("a superseded request cannot overwrite or abort the latest result", async ({
  page,
}) => {
  await routeIdentity(page);
  let firstRequestSeen;
  const firstSeen = new Promise((resolve) => {
    firstRequestSeen = resolve;
  });
  await page.route("**/api/v1/answers", async (route) => {
    const text = JSON.parse(route.request().postData()).text;
    if (text === "перший") {
      firstRequestSeen();
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "answered",
        text: text === "перший" ? "застарілий результат" : "актуальний результат",
        retrieval_score: 1,
        evidence_coverage: 1,
        corpus_release: "test-release",
        limitations: [],
        citations: [],
      }),
    });
  });
  await page.goto("/");
  const input = page.getByLabel("Запит до контрольованого корпусу");
  await input.fill("перший");
  await page.getByRole("button", { name: /Знайти доказ/ }).click();
  await firstSeen;
  await input.fill("другий");
  await input.press("Control+Enter");
  await expect(page.getByText("актуальний результат")).toBeVisible();
  await page.waitForTimeout(600);
  await expect(page.getByText("застарілий результат")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Знайти доказ/ })).toBeEnabled();
});
