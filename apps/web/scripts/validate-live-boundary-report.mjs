import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const path = resolve(
  process.argv[2] ?? "../../var/web-act/web-api-live-boundary.json",
);
const report = JSON.parse(await readFile(path, "utf8"));
const fail = (message) => {
  throw new Error(`invalid web/API live-boundary evidence: ${message}`);
};
if (report.schema !== "korpus.web-api-live-boundary.v3") fail("schema");
if (report.act_id !== "KORPUS-ACT-09") fail("act_id");
if (!/^[0-9a-f]{40}$/.test(report.candidate_commit ?? "")) fail("candidate_commit");
for (const name of ["api", "web"]) {
  if (!/^sha256:[0-9a-f]{64}$/.test(report.images?.[name] ?? ""))
    fail(`${name}_image_digest`);
}
const expectedCases = {
  anonymous_identity: 401,
  jwt_identity: 200,
  answer: 200,
  forged_token: 401,
  security_headers: "PASS",
  browser_authority_storage: "EMPTY",
  evidence_marker: report.database?.mode === "postgres" ? "PASS" : "NOT_APPLICABLE",
};
if (JSON.stringify(report.cases) !== JSON.stringify(expectedCases)) fail("cases");
if (report.quality?.accessibility?.serious !== 0) fail("accessibility_serious");
if (report.quality?.accessibility?.critical !== 0) fail("accessibility_critical");
if (report.quality?.layout?.viewport_width_css_px !== 390) fail("layout_viewport");
if (report.quality?.layout?.horizontal_overflow_css_px !== 0) fail("layout_overflow");
if (report.quality?.performance?.measurement !== "ANCHORED_LOCAL")
  fail("performance_measurement");
if (JSON.stringify(report.quality?.performance?.external_origins) !== "[]")
  fail("external_origins");
for (const metric of [
  "navigation_ms",
  "lcp_ms",
  "cls",
  "answer_ms",
  "same_origin_transfer_bytes",
]) {
  const value = report.quality?.performance?.[metric];
  const budget = report.quality?.budgets?.[metric];
  if (!Number.isFinite(value) || value < 0) fail(`${metric}_value`);
  if (!Number.isFinite(budget) || budget <= 0) fail(`${metric}_budget`);
  if (value > budget) fail(`${metric}_exceeded`);
}
if (report.database?.mode === "postgres") {
  if (report.topology !== "chromium -> nginx -> fastapi -> postgres") fail("topology");
  if (!/^sha256:[0-9a-f]{64}$/.test(report.database.image_digest ?? ""))
    fail("postgres_image_digest");
  if (!report.database.server_version || !report.database.pgvector_version)
    fail("postgres_versions");
  if (!Array.isArray(report.database.alembic_heads) || report.database.alembic_heads.length !== 1)
    fail("alembic_heads");
} else if (report.database?.mode !== "sqlite") {
  fail("database_mode");
}
if (report.production_authorized !== false) fail("production_authorized");
if (report.verdict !== "PASS_WITH_CAVEATS") fail("verdict");
if (!Array.isArray(report.limitations) || report.limitations.length < 3)
  fail("limitations");
if (Date.parse(report.finished_at_utc) < Date.parse(report.started_at_utc))
  fail("time_ordering");
const serialized = JSON.stringify(report);
if (/Bearer |eyJ[A-Za-z0-9_-]+\./.test(serialized)) fail("token_disclosure");
console.log(`web/API live-boundary evidence valid: ${path}`);
