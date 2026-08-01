import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const path = resolve(process.argv[2] ?? "../../var/web-act/web-runtime-assurance.json");
const report = JSON.parse(await readFile(path, "utf8"));
const expectedPaths = [
  "/",
  "/index.html",
  "/config.js",
  "/sw.js",
  "/styles.css",
  "/route-that-does-not-exist",
  "/asset-that-does-not-exist.css",
  "/healthz",
];
const fail = (message) => {
  throw new Error(`invalid runtime assurance: ${message}`);
};
if (report.schema !== "korpus.web-runtime-assurance.v1") fail("schema");
if (report.act_id !== "KORPUS-ACT-04") fail("act_id");
if (!/^[0-9a-f]{40}$/.test(report.candidate_commit ?? "")) fail("candidate_commit");
if (!/^sha256:[0-9a-f]{64}$/.test(report.environment?.image_digest ?? "")) fail("image_digest");
if (!/^nginx\/\d+\.\d+\.\d+$/.test(report.environment?.nginx_version ?? "")) fail("nginx_version");
if (report.production_authorized !== false) fail("production_authorized");
if (report.verdict !== "PASS_WITH_CAVEATS") fail("self-verdict");
if (!Array.isArray(report.failures) || report.failures.length !== 0) fail("failures");
if (!Array.isArray(report.cases) || report.cases.length !== expectedPaths.length)
  fail("case count");
for (const [index, expectedPath] of expectedPaths.entries()) {
  const item = report.cases[index];
  if (item?.path !== expectedPath) fail(`case path ${index}`);
  if (!Array.isArray(item.failures) || item.failures.length !== 0)
    fail(`case failures ${expectedPath}`);
}
if (Date.parse(report.finished_at_utc) < Date.parse(report.started_at_utc))
  fail("time ordering");
console.log(`web runtime assurance report valid: ${path}`);
