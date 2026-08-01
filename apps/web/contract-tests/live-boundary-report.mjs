import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const validator = fileURLToPath(
  new URL("../scripts/validate-live-boundary-report.mjs", import.meta.url),
);
const validReport = () => ({
  schema: "korpus.web-api-live-boundary.v5",
  act_id: "KORPUS-ACT-09",
  quality_act_id: "KORPUS-ACT-13",
  candidate_commit: "a".repeat(40),
  started_at_utc: "2026-08-01T00:00:00.000Z",
  finished_at_utc: "2026-08-01T00:00:01.000Z",
  images: {
    api: `sha256:${"b".repeat(64)}`,
    web: `sha256:${"c".repeat(64)}`,
  },
  topology: "chromium -> nginx -> fastapi -> sqlite",
  database: { mode: "sqlite" },
  browser: {
    engine: "chromium",
    version: "140.0.7339.16",
    playwright_version: "1.62.1",
    user_agent: "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36",
    device_scale_factor: 1,
    context: "EPHEMERAL_COLD",
  },
  cases: {
    anonymous_identity: 401,
    jwt_identity: 200,
    answer: 200,
    forged_token: 401,
    security_headers: "PASS",
    browser_authority_storage: "EMPTY",
    evidence_marker: "NOT_APPLICABLE",
  },
  quality: {
    accessibility: { serious: 0, critical: 0 },
    layout: {
      viewport_width_css_px: 390,
      content_width_css_px: 390,
      horizontal_overflow_css_px: 0,
    },
    performance: {
      measurement: "ANCHORED_LOCAL",
      navigation_ms: 100,
      lcp_ms: 90,
      cls: 0,
      answer_ms: 200,
      same_origin_transfer_bytes: 30_000,
      external_origins: [],
    },
    budgets: {
      navigation_ms: 5_000,
      lcp_ms: 4_000,
      cls: 0.1,
      answer_ms: 10_000,
      same_origin_transfer_bytes: 150_000,
    },
  },
  limitations: ["one", "two", "three"],
  production_authorized: false,
  verdict: "PASS_WITH_CAVEATS",
});

async function validate(report) {
  const directory = await mkdtemp(join(tmpdir(), "korpus-live-boundary-"));
  const reportPath = join(directory, "report.json");
  await writeFile(reportPath, JSON.stringify(report));
  const result = spawnSync(process.execPath, [validator, reportPath], {
    encoding: "utf8",
  });
  await rm(directory, { recursive: true, force: true });
  return result.status;
}

test("accepts complete live-boundary evidence", async () => {
  assert.equal(await validate(validReport()), 0);
});

test("accepts a PostgreSQL-bound report with version and migration receipts", async () => {
  const report = validReport();
  report.topology = "chromium -> nginx -> fastapi -> postgres";
  report.database = {
    mode: "postgres",
    image_digest: `sha256:${"d".repeat(64)}`,
    server_version: "17.10",
    pgvector_version: "0.8.5",
    alembic_heads: ["derived-head"],
  };
  report.cases.evidence_marker = "PASS";
  assert.equal(await validate(report), 0);
});

for (const [name, mutate] of [
  ["forged PASS", report => { report.cases.forged_token = 200; }],
  ["missing image binding", report => { report.images.api = "UNSPECIFIED"; }],
  ["production authorization", report => { report.production_authorized = true; }],
  ["token disclosure", report => { report.limitations.push("Bearer secret"); }],
  ["unbound PostgreSQL mode", report => {
    report.database = { mode: "postgres" };
    report.cases.evidence_marker = "PASS";
  }],
  ["serious accessibility violation", report => {
    report.quality.accessibility.serious = 1;
  }],
  ["horizontal overflow", report => {
    report.quality.layout.horizontal_overflow_css_px = 1;
  }],
  ["external browser origin", report => {
    report.quality.performance.external_origins = ["https://tracker.invalid"];
  }],
  ["performance budget breach", report => {
    report.quality.performance.lcp_ms = 4_001;
  }],
  ["non-finite performance metric", report => {
    report.quality.performance.cls = null;
  }],
  ["producer-inflated performance budget", report => {
    report.quality.performance.lcp_ms = 8_000;
    report.quality.budgets.lcp_ms = 9_000;
  }],
  ["substituted browser engine", report => {
    report.browser.engine = "unknown";
  }],
  ["missing browser version", report => {
    report.browser.version = "";
  }],
  ["persistent browser context", report => {
    report.browser.context = "PERSISTENT_WARM";
  }],
  ["missing Playwright provenance", report => {
    report.browser.playwright_version = "";
  }],
  ["unavailable LCP", report => {
    report.quality.performance.lcp_ms = 0;
  }],
  ["unavailable navigation timing", report => {
    report.quality.performance.navigation_ms = 0;
  }],
  ["unavailable answer timing", report => {
    report.quality.performance.answer_ms = 0;
  }],
  ["unavailable transfer measurement", report => {
    report.quality.performance.same_origin_transfer_bytes = 0;
  }],
  ["contradictory content width", report => {
    report.quality.layout.content_width_css_px = 391;
  }],
]) {
  test(`rejects ${name}`, async () => {
    const report = validReport();
    mutate(report);
    assert.notEqual(await validate(report), 0);
  });
}
