import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const token = process.env.KORPUS_LIVE_BEARER_TOKEN;
const candidateCommit = process.env.KORPUS_LIVE_CANDIDATE_COMMIT;
const apiImageDigest = process.env.KORPUS_LIVE_API_IMAGE_DIGEST;
const webImageDigest = process.env.KORPUS_LIVE_WEB_IMAGE_DIGEST;
const database = JSON.parse(process.env.KORPUS_LIVE_DATABASE_RECEIPT ?? "{}");
const query = process.env.KORPUS_LIVE_QUERY;
const expectedEvidence = process.env.KORPUS_LIVE_EXPECTED_EVIDENCE;

test("@live browser traverses nginx and the real API without storing authority", async ({
  page,
  context,
}) => {
  test.skip(!token, "KORPUS_LIVE_BEARER_TOKEN is required for the composed live gate");
  const startedAt = new Date();
  expect(candidateCommit).toMatch(/^[0-9a-f]{40}$/);
  expect(apiImageDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(webImageDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  const responses = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/")) responses.push(response);
  });

  await page.goto("/");
  await page.getByText("Developer bearer fallback").click();
  await page.getByLabel("Короткоживучий access token").fill(token);
  await page.getByRole("button", { name: "Перевірити", exact: true }).click();
  await expect(page.locator("#identity-state")).toContainText("live-boundary-user");

  const input = page.getByLabel("Запит до контрольованого корпусу");
  await input.fill(query ?? "перевірити відсутність непідтверджених доказів");
  await page.getByRole("button", { name: /Знайти доказ/ }).click();
  await expect(page.locator("#result")).toBeVisible();
  await expect(page.locator("#result")).toContainText(/Доказова відповідь|Відмова/);
  if (expectedEvidence) {
    await expect(page.locator("#result")).toContainText(expectedEvidence);
  }

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
        schema: "korpus.web-api-live-boundary.v2",
        act_id: "KORPUS-ACT-09",
        candidate_commit: candidateCommit,
        started_at_utc: startedAt.toISOString(),
        finished_at_utc: new Date().toISOString(),
        images: {
          api: apiImageDigest,
          web: webImageDigest,
        },
        topology: `chromium -> nginx -> fastapi -> ${database.mode}`,
        database,
        cases: {
          anonymous_identity: 401,
          jwt_identity: 200,
          answer: 200,
          forged_token: 401,
          security_headers: "PASS",
          browser_authority_storage: "EMPTY",
          evidence_marker: expectedEvidence ? "PASS" : "NOT_APPLICABLE",
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
