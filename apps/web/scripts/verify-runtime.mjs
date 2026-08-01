import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  const value = process.argv[index + 1];
  if (!key?.startsWith("--") || value === undefined)
    throw new Error(`invalid argument near ${key ?? "<end>"}`);
  args.set(key.slice(2), value);
}
const base = new URL(args.get("base-url") ?? "http://127.0.0.1:8080");
if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password)
  throw new Error("base URL must be credential-free HTTP(S)");
const output = resolve(
  args.get("output") ?? "../../var/web-act/web-runtime-assurance.json",
);
const startedAt = new Date();
const candidateCommit = process.env.KORPUS_CANDIDATE_COMMIT ?? "UNSPECIFIED";
const imageDigest = process.env.KORPUS_WEB_IMAGE_DIGEST ?? "UNSPECIFIED";
const nginxVersion = process.env.KORPUS_NGINX_VERSION ?? "UNSPECIFIED";

const securityHeaders = {
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "no-referrer",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "cross-origin-opener-policy": "same-origin",
  "cross-origin-resource-policy": "same-origin",
  "content-security-policy": "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
};
const cases = [
  { path: "/", status: 200, contentType: "text/html", cache: "no-store" },
  { path: "/index.html", status: 200, contentType: "text/html", cache: "no-store" },
  { path: "/config.js", status: 200, contentType: "application/javascript", cache: "no-store" },
  { path: "/sw.js", status: 200, contentType: "application/javascript", cache: "no-cache" },
  { path: "/styles.css", status: 200, contentType: "text/css", cache: "public, max-age=300" },
  { path: "/route-that-does-not-exist", status: 200, contentType: "text/html", cache: "no-store", accept: "text/html" },
  { path: "/asset-that-does-not-exist.css", status: 404, contentType: "text/html", cache: null },
  { path: "/healthz", status: 200, contentType: "application/json", cache: null },
];

const failures = [];
for (const [name, value] of Object.entries({ candidateCommit, imageDigest, nginxVersion })) {
  if (value === "UNSPECIFIED") failures.push(`CANDIDATE_IDENTITY:${name}`);
}
const results = [];
for (const expected of cases) {
  let response;
  try {
    response = await fetch(new URL(expected.path, base), {
      headers: expected.accept ? { Accept: expected.accept } : {},
      redirect: "manual",
      signal: AbortSignal.timeout(5_000),
    });
  } catch (error) {
    failures.push(`${expected.path}:FETCH:${error instanceof Error ? error.name : "UNKNOWN"}`);
    results.push({ ...expected, observed_status: null, headers: {}, failures: ["FETCH_FAILED"] });
    continue;
  }
  const headers = Object.fromEntries(
    [...Object.keys(securityHeaders), "cache-control", "content-type", "server"].map(
      name => [name, response.headers.get(name)],
    ),
  );
  const caseFailures = [];
  if (response.status !== expected.status)
    caseFailures.push(`HTTP_STATUS:${response.status}`);
  if (!headers["content-type"]?.startsWith(expected.contentType))
    caseFailures.push(`CONTENT_TYPE:${headers["content-type"] ?? "missing"}`);
  if (expected.cache !== null && headers["cache-control"] !== expected.cache)
    caseFailures.push(`CACHE_CONTROL:${headers["cache-control"] ?? "missing"}`);
  for (const [name, value] of Object.entries(securityHeaders)) {
    if (headers[name] !== value) caseFailures.push(`SECURITY_HEADER:${name}`);
  }
  if (headers.server !== "nginx") caseFailures.push(`SERVER_DISCLOSURE:${headers.server ?? "missing"}`);
  failures.push(...caseFailures.map(failure => `${expected.path}:${failure}`));
  results.push({ ...expected, observed_status: response.status, headers, failures: caseFailures });
  await response.arrayBuffer();
}

const report = {
  schema: "korpus.web-runtime-assurance.v1",
  act_id: "KORPUS-ACT-04",
  candidate_commit: candidateCommit,
  started_at_utc: startedAt.toISOString(),
  finished_at_utc: new Date().toISOString(),
  environment: {
    base_origin: base.origin,
    node_version: process.version,
    image: process.env.KORPUS_WEB_IMAGE ?? "UNSPECIFIED",
    image_digest: imageDigest,
    nginx_version: nginxVersion,
  },
  cases: results,
  failures,
  production_authorized: false,
  verdict: failures.length === 0 ? "PASS_WITH_CAVEATS" : "FAIL",
  caveat: "Independent post-change verification is required.",
};
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
console.log(`web runtime assurance ${report.verdict}: ${output}`);
if (failures.length > 0) {
  for (const failure of failures) console.error(failure);
  process.exitCode = 1;
}
