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
  schema: "korpus.web-api-live-boundary.v2",
  act_id: "KORPUS-ACT-09",
  candidate_commit: "a".repeat(40),
  started_at_utc: "2026-08-01T00:00:00.000Z",
  finished_at_utc: "2026-08-01T00:00:01.000Z",
  images: {
    api: `sha256:${"b".repeat(64)}`,
    web: `sha256:${"c".repeat(64)}`,
  },
  topology: "chromium -> nginx -> fastapi -> sqlite",
  database: { mode: "sqlite" },
  cases: {
    anonymous_identity: 401,
    jwt_identity: 200,
    answer: 200,
    forged_token: 401,
    security_headers: "PASS",
    browser_authority_storage: "EMPTY",
    evidence_marker: "NOT_APPLICABLE",
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
]) {
  test(`rejects ${name}`, async () => {
    const report = validReport();
    mutate(report);
    assert.notEqual(await validate(report), 0);
  });
}
