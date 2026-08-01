import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const validator = fileURLToPath(
  new URL("../scripts/validate-runtime-report.mjs", import.meta.url),
);
const paths = [
  "/",
  "/index.html",
  "/config.js",
  "/sw.js",
  "/styles.css",
  "/route-that-does-not-exist",
  "/asset-that-does-not-exist.css",
  "/healthz",
];
const validReport = () => ({
  schema: "korpus.web-runtime-assurance.v1",
  act_id: "KORPUS-ACT-04",
  candidate_commit: "a".repeat(40),
  started_at_utc: "2026-08-01T00:00:00.000Z",
  finished_at_utc: "2026-08-01T00:00:01.000Z",
  environment: {
    image_digest: `sha256:${"b".repeat(64)}`,
    nginx_version: "nginx/1.29.8",
  },
  cases: paths.map(path => ({ path, failures: [] })),
  failures: [],
  production_authorized: false,
  verdict: "PASS_WITH_CAVEATS",
});

async function validate(report) {
  const directory = await mkdtemp(join(tmpdir(), "korpus-runtime-report-"));
  const reportPath = join(directory, "report.json");
  await writeFile(reportPath, JSON.stringify(report));
  const result = spawnSync(process.execPath, [validator, reportPath], {
    encoding: "utf8",
  });
  await rm(directory, { recursive: true, force: true });
  return result;
}

test("accepts a complete self-verifier report", async () => {
  assert.equal((await validate(validReport())).status, 0);
});

for (const [name, mutate] of [
  ["nonempty failures", report => report.failures.push("FORGED")],
  ["missing case", report => report.cases.pop()],
  ["production authorization", report => { report.production_authorized = true; }],
  ["unbound image", report => { report.environment.image_digest = "UNSPECIFIED"; }],
]) {
  test(`rejects ${name}`, async () => {
    const report = validReport();
    mutate(report);
    assert.notEqual((await validate(report)).status, 0);
  });
}
