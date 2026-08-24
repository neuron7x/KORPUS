import {mkdir, mkdtemp, readFile, rm, writeFile} from "node:fs/promises";
import {spawn} from "node:child_process";
import {dirname, join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {tmpdir} from "node:os";
import process from "node:process";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = resolve(SCRIPT_DIR, "..");
const ROOT = resolve(WEB_ROOT, "../..");
const PUBLIC = join(WEB_ROOT, "public");
const REPORT = process.env.KORPUS_BROWSER_E2E_REPORT ?? join(ROOT, "var/browser-e2e-report.json");
const BROWSER = process.env.KORPUS_BROWSER_BIN ?? "/usr/bin/chromium";
const TIMEOUT_MS = 15_000;
const ANSWER_XSS = '<img id="pwn" src=x onerror="window.__KORPUS_PWNED=1">';
const CITATION_XSS = '<svg id="citation-pwn" onload="window.__KORPUS_PWNED=2"></svg>';
const UUID_A = "11111111-1111-4111-8111-111111111111";
const UUID_B = "22222222-2222-4222-8222-222222222222";
const UUID_C = "33333333-3333-4333-8333-333333333333";

class CDP {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
  }
  async open() {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP websocket open timeout")), TIMEOUT_MS);
      this.socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, {once:true});
      this.socket.addEventListener("error", event => { clearTimeout(timer); reject(event.error ?? new Error("CDP websocket error")); }, {once:true});
    });
    this.socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
      else pending.resolve(message.result ?? {});
    });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject, method});
      this.socket.send(JSON.stringify({id, method, params}));
    });
  }
  async evaluate(expression) {
    const response = await this.send("Runtime.evaluate", {expression, awaitPromise:true, returnByValue:true});
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.exception?.description ?? response.exceptionDetails.text ?? "browser evaluation failed");
    }
    return response.result?.value;
  }
  close() { this.socket.close(); }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitFor(cdp, expression, label, timeout = TIMEOUT_MS) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(`Boolean(${expression})`)) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error(`timeout waiting for ${label}`);
}

async function commandOutput(command, args, cwd = ROOT) {
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, {cwd, stdio:["ignore","pipe","pipe"]});
    let out = "", err = "";
    child.stdout.on("data", chunk => { out += chunk; });
    child.stderr.on("data", chunk => { err += chunk; });
    child.once("exit", code => code === 0 ? resolve(out.trim()) : reject(new Error(err || `${command} exit ${code}`)));
  });
}

async function browserVersion() { return commandOutput(BROWSER, ["--version"]); }

async function waitForFile(path) {
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    try { await readFile(path); return; } catch { await new Promise(resolve => setTimeout(resolve, 50)); }
  }
  throw new Error(`timeout waiting for ${path}`);
}

async function waitForExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  let exited = false;
  const done = new Promise(resolve => child.once("exit", () => { exited = true; resolve(); }));
  await Promise.race([done, new Promise(resolve => setTimeout(resolve, 2000))]);
  if (!exited) child.kill("SIGKILL");
  if (!exited) await done;
}

function mockFetchSource() {
  const answerXss = JSON.stringify(ANSWER_XSS);
  const citationXss = JSON.stringify(CITATION_XSS);
  return `globalThis.fetch = async (input, options={}) => {
    const url = String(input);
    const route = new URL(url, "https://korpus.invalid").pathname;
    const response = (status, payload, headers={}) => new Response(JSON.stringify(payload), {
      status, headers:{"content-type":"application/json", ...headers}
    });
    if (route === "/api/v1/client/bootstrap") return response(200, {
      release:"v0.9.7", api_version:"v1",
      identity:{subject:"browser-e2e", clearance:3, roles:["admin"], corpora:["public"], compartments:[]},
      effective_permissions:["account:manage","answer:read","audit:read","audit:verify","document:approve","document:ingest","document:list","document:review","document:review_metadata","training:manage"],
      capabilities:{browser_auth_enabled:true,subscription_required:true,offline_pack_enabled:false,ingestion_mode:"synchronous"}
    });
    if (route === "/api/v1/inference/status") return response(200, {enabled:false, provider:"disabled", model:"none", answer_authority:"evidence"});
    if (route === "/api/v1/account") return response(200, {id:"${UUID_A}", auth_subject:"browser-e2e", email:"browser@example.invalid", display_name:"Browser E2E", status:"active", created_at:"2026-08-11T00:00:00Z"});
    if (route === "/api/v1/subscription") return response(200, {subscription_status:"active", enforced:true, plan_code:"e2e"});
    if (route === "/api/v1/plans") return response(200, []);
    if (route === "/api/v1/conversations" && (options.method ?? "GET") === "GET") return response(200, {items:[], has_more:false, next_offset:null});
    if (route === "/api/v1/conversations" && options.method === "POST") return response(503, {detail:"conversation fixture deliberately unavailable"});
    if (route === "/api/v1/answers" && options.method === "POST") {
      const body = options.body ? JSON.parse(options.body) : {};
      if (String(body.text ?? "").includes("throttle")) return response(429, {detail:{reason:"subject_share_exhausted", detail:"Ліміт одночасних запитів цього користувача вичерпано"}}, {"retry-after":"1"});
      return response(200, {
        id:"${UUID_A}", status:"answered", text:"Безпечна відповідь " + ${answerXss},
        opening:"Підтверджено контрольованим джерелом.", retrieval_score:0.91,
        evidence_coverage:1, query_coverage:1, decision_reason:"evidence_supported",
        calibration_id:"browser-e2e", corpus_release:"browser-fixture-r1",
        limitations:["Межа " + ${citationXss}], citations:[{
          document_id:"${UUID_A}", version_id:"${UUID_B}", span_id:"${UUID_C}",
          title:"Джерело " + ${citationXss}, revision:"r1", quote:"Цитата " + ${citationXss},
          quote_start:0, quote_end:20, quote_hash:"${"b".repeat(64)}", source_hash:"${"a".repeat(64)}", page:7, section:"§ 4"
        }]
      });
    }
    return response(404, {detail:"browser fixture route absent: " + (options.method ?? "GET") + " " + route});
  };`;
}

async function collectModules(entry) {
  const modules = {};
  async function visit(name) {
    if (modules[name]) return;
    const source = await readFile(join(PUBLIC, name), "utf8");
    const deps = [...source.matchAll(/(?:from\s+|import\s+|import\s*\(\s*)["'](\.\.?\/[^"']+)["']/g)]
      .map(match => match[1]);
    modules[name] = {source, deps:[]};
    for (const spec of deps) {
      const target = resolve(dirname(join(PUBLIC, name)), spec);
      const rel = target.slice(PUBLIC.length + 1).replaceAll("\\", "/");
      modules[name].deps.push([spec, rel]);
      await visit(rel);
    }
  }
  await visit(entry);
  return modules;
}

async function inlinePage(file) {
  let html = await readFile(join(PUBLIC, file), "utf8");
  const styles = [];
  for (const match of html.matchAll(/<link[^>]+rel=["']stylesheet["'][^>]+href=["']([^"']+)["'][^>]*>/g)) {
    const path = match[1].replace(/^\//, "");
    styles.push(await readFile(join(PUBLIC, path), "utf8"));
  }
  html = html
    .replace(/<link[^>]+rel=["']stylesheet["'][^>]*>/g, "")
    .replace(/<link[^>]+rel=["']manifest["'][^>]*>/g, "")
    .replace(/<script[^>]+src=["'][^"']+["'][^>]*><\/script>/g, "")
    .replace("</head>", `<style>${styles.join("\n")}</style></head>`);
  return html;
}

async function loadPage(cdp, htmlFile, moduleEntry) {
  const frameTree = await cdp.send("Page.getFrameTree");
  await cdp.send("Page.setDocumentContent", {frameId:frameTree.frameTree.frame.id, html:await inlinePage(htmlFile)});
  await waitFor(cdp, 'document.readyState === "complete"', `${htmlFile} document content`);
  await cdp.evaluate(`globalThis.KORPUS_CONFIG = Object.freeze({apiUrl:"/api", publicMode:false}); globalThis.__KORPUS_PWNED=0;
    try { void document.cookie; } catch { Object.defineProperty(Document.prototype, "cookie", {configurable:true, get(){return "";}, set(){}}); }
    ${mockFetchSource()}`);
  const modules = await collectModules(moduleEntry);
  await cdp.evaluate(`(async () => {
    const modules = ${JSON.stringify(modules)};
    const urls = {};
    const normal = path => path.split("/").reduce((parts, part) => {
      if (!part || part === ".") return parts;
      if (part === "..") parts.pop(); else parts.push(part);
      return parts;
    }, []).join("/");
    const resolveSpec = (from, spec) => normal(from.split("/").slice(0,-1).concat(spec.split("/")).join("/"));
    const make = name => {
      if (urls[name]) return urls[name];
      const item = modules[name];
      if (!item) throw new Error("module absent: " + name);
      let source = item.source;
      for (const [spec, dep] of item.deps) {
        const depUrl = make(dep);
        source = source.replaceAll('"' + spec + '"', '"' + depUrl + '"').replaceAll("'" + spec + "'", '"' + depUrl + '"');
      }
      urls[name] = URL.createObjectURL(new Blob([source], {type:"text/javascript"}));
      return urls[name];
    };
    const entryUrl = make(${JSON.stringify(moduleEntry)});
    globalThis.__KORPUS_MODULE_URLS = urls;
    await import(entryUrl);
  })()`);
}

async function runCase(name, fn, results) {
  const started = performance.now();
  try {
    await fn();
    results.push({name, status:"PASS", duration_ms:Number((performance.now() - started).toFixed(3))});
  } catch (error) {
    results.push({name, status:"FAIL", duration_ms:Number((performance.now() - started).toFixed(3)), error:String(error?.message ?? error)});
  }
}

async function main() {
  const version = await browserVersion();
  const release = JSON.parse(await readFile(join(ROOT, "apps/api/src/korpus/release.json"), "utf8"));
  let gitHead = null;
  try { gitHead = await commandOutput("git", ["rev-parse", "HEAD"]); } catch { gitHead = null; }
  const profile = await mkdtemp(join(tmpdir(), "korpus-browser-e2e-"));
  const chromium = spawn(BROWSER, [
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--disable-background-networking", "--disable-component-update", "--no-first-run",
    "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
    `--user-data-dir=${profile}`, "about:blank",
  ], {stdio:["ignore","ignore","pipe"]});
  let browserErr = "";
  chromium.stderr.on("data", chunk => { browserErr += chunk; });
  let cdp;
  const results = [];
  try {
    await waitForFile(join(profile, "DevToolsActivePort"));
    const [port] = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).trim().split(/\s+/);
    const pages = await fetch(`http://127.0.0.1:${port}/json/list`).then(response => response.json());
    cdp = new CDP(pages[0].webSocketDebuggerUrl);
    await cdp.open();
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");

    await runCase("consumer_authenticated_boot", async () => {
      await loadPage(cdp, "index.html", "app.js");
      await waitFor(cdp, '!document.getElementById("product").hidden', "authenticated product surface");
      await waitFor(cdp, 'document.getElementById("trace-status")?.textContent', "KORPUS TRACE boot state");
      const state = await cdp.evaluate(`({identity:document.getElementById("identity-state").textContent, entryHidden:document.getElementById("entry").hidden, productHidden:document.getElementById("product").hidden, queryVisible:document.getElementById("query").getBoundingClientRect().height > 0, trace:document.getElementById("trace-status").textContent})`);
      assert(state.identity.includes("browser-e2e"), "server identity was not rendered");
      assert(state.entryHidden && !state.productHidden, "authenticated workspace state is inconsistent");
      assert(state.queryVisible, "authenticated query surface is not visible");
      assert(state.trace.includes("Готовий"), "TRACE did not project the READY state");
    }, results);

    await runCase("trace_explains_the_selected_gate", async () => {
      const text = await cdp.evaluate(`(() => { document.querySelector('[data-trace-stage="access"]').click(); return document.getElementById("trace-explainer").textContent; })()`);
      assert(text.includes("допуск") && text.includes("до початку пошуку"), "TRACE did not explain access-before-retrieval");
    }, results);

    await runCase("combat_theme_is_reversible_and_accessible", async () => {
      await cdp.evaluate(`document.getElementById("theme-toggle").click()`);
      await waitFor(cdp, 'document.getElementById("combat-signal-field")', "combat signal field");
      const combat = await cdp.evaluate(`(() => { const button=document.getElementById("theme-toggle"); return {theme:document.documentElement.dataset.theme, pressed:button.getAttribute("aria-pressed"), label:button.getAttribute("aria-label"), stylesheet:document.getElementById("combat-theme")?.getAttribute("href"), canvas:document.getElementById("combat-signal-field")?.tagName}; })()`);
      assert(combat.theme === "combat" && combat.pressed === "true", "combat theme state was not exposed accessibly");
      assert(combat.label.includes("основну") && combat.stylesheet === "/combat.css" && combat.canvas === "CANVAS", "combat theme did not load its optional visual layer");
      const core = await cdp.evaluate(`(() => { const button=document.getElementById("theme-toggle"); button.click(); return {theme:document.documentElement.dataset.theme, pressed:button.getAttribute("aria-pressed")}; })()`);
      assert(core.theme === "core" && core.pressed === "false", "canonical theme was not restored by the same control");
      assert(!(await cdp.evaluate(`document.getElementById("combat-signal-field")`)), "combat canvas survived after returning to core");
    }, results);

    await runCase("evidence_render_escapes_xss", async () => {
      const probe = await cdp.evaluate(`(async()=>{ const api=await import(globalThis.__KORPUS_MODULE_URLS["api.js"]); try { const value=await api.call("/v1/answers",{method:"POST",body:{text:"probe",declaration:null}}); return {ok:true,status:value.status,text:value.text}; } catch(error) { return {ok:false,name:error?.name,message:error?.message,ctor:error?.constructor?.name,stack:error?.stack}; } })()`);
      assert(probe.ok, `direct API fixture probe failed: ${JSON.stringify(probe)}`);
      await cdp.evaluate(`(() => { const q=document.getElementById("query"); q.value="перевір доказ"; q.dispatchEvent(new Event("input",{bubbles:true})); document.getElementById("query-form").requestSubmit(); })()`);
      await waitFor(cdp, 'document.querySelectorAll("#result .turn").length >= 1 && !document.getElementById("result").hasAttribute("aria-busy")', "evidence answer");
      const state = await cdp.evaluate(`({text:document.querySelector("#result .turn:last-child .answer-text")?.textContent, citation:document.querySelector("#result .turn:last-child .citation blockquote")?.textContent, citationCount:document.querySelectorAll("#result .turn:last-child .citation").length, injected:Boolean(document.querySelector("#pwn, #citation-pwn")), pwned:globalThis.__KORPUS_PWNED ?? 0, trace:document.getElementById("trace-status").textContent, completed:document.querySelectorAll('[data-trace-stage][data-state="done"]').length})`);
      assert(state.text?.includes("<img id=\"pwn\""), `answer XSS payload was not preserved as text: ${JSON.stringify(state)}`);
      assert(state.citation.includes("<svg id=\"citation-pwn\""), "citation XSS payload was not preserved as text");
      assert(state.citationCount === 1, "citation card was not rendered");
      assert(state.trace.includes("завершено") && state.completed === 4, "TRACE did not project the completed route");
      assert(!state.injected && state.pwned === 0, "untrusted answer/citation became executable DOM");
    }, results);

    await runCase("typed_429_is_not_rendered_as_outage", async () => {
      await cdp.evaluate(`(() => { const q=document.getElementById("query"); q.value="throttle перевірка"; q.dispatchEvent(new Event("input",{bubbles:true})); document.getElementById("query-form").requestSubmit(); })()`);
      await waitFor(cdp, 'document.querySelectorAll("#result .turn").length >= 2 && !document.getElementById("result").hasAttribute("aria-busy")', "429 refusal");
      const state = await cdp.evaluate(`({heading:document.querySelector("#result .turn:last-child .verdict h2")?.textContent, reason:document.querySelector("#result .turn:last-child .answer-text")?.textContent})`);
      assert(state.heading === "ВІДМОВА 429", `subject throttle rendered as ${JSON.stringify(state)}`);
      assert(state.reason.includes("Ліміт одночасних запитів"), "typed refusal reason was lost");
    }, results);

    await runCase("mobile_viewport_matrix_is_touch_safe_without_overflow", async () => {
      await cdp.send("Emulation.setTouchEmulationEnabled", {enabled:true, maxTouchPoints:5});
      for (const viewport of [{width:320,height:568}, {width:390,height:844}, {width:844,height:390}]) {
        await cdp.send("Emulation.setDeviceMetricsOverride", {...viewport, deviceScaleFactor:2, mobile:true});
        await loadPage(cdp, "index.html", "app.js");
        await waitFor(cdp, '!document.getElementById("product").hidden', "mobile authenticated product surface");
        const state = await cdp.evaluate(`(() => { const box=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,height:r.height};}; return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,composer:box(".composer"),query:box("#query"),theme:box("#theme-toggle"),nav:[...document.querySelectorAll(".mobile-nav a")].map(node=>node.getBoundingClientRect().height)}; })()`);
        assert(state.scroll <= state.viewport + 1, `${viewport.width}x${viewport.height}: horizontal overflow ${state.scroll}px > ${state.viewport}px`);
        assert(state.composer.left >= -1 && state.composer.right <= state.viewport + 1, `${viewport.width}x${viewport.height}: composer escapes viewport`);
        assert(state.query.height > 0, `${viewport.width}x${viewport.height}: query field is not visible`);
        assert(state.theme.width >= 44 && state.theme.height >= 44, `${viewport.width}x${viewport.height}: theme control is not touch safe`);
        assert(state.nav.every(height => height >= 44), `${viewport.width}x${viewport.height}: mobile navigation is not touch safe`);
      }
      await cdp.send("Emulation.clearDeviceMetricsOverride");
      await cdp.send("Emulation.setTouchEmulationEnabled", {enabled:false});
    }, results);

    await runCase("operator_console_roles_and_preview_gate", async () => {
      await loadPage(cdp, "console.html", "console.js");
      await waitFor(cdp, 'document.getElementById("identity-state").textContent.includes("browser-e2e")', "console identity");
      const tabs = await cdp.evaluate(`[...document.querySelectorAll('[role="tab"]')].filter(n=>!n.hidden).map(n=>n.id)`);
      assert(tabs.length === 5, `admin identity sees ${tabs.length}/5 console tabs`);
      await cdp.evaluate(`(() => { document.getElementById("tab-console-reviewer").click(); const set=(id,value)=>{const n=document.getElementById(id);n.value=value;n.dispatchEvent(new Event("input",{bubbles:true}));n.dispatchEvent(new Event("change",{bubbles:true}));}; set("review-version-id","${UUID_B}"); set("review-target","approved"); set("review-note","Перевірено в browser E2E перед застосуванням рішення."); document.getElementById("review-ack-duplicate").click(); document.getElementById("review-ack-extraction").click(); document.getElementById("review-preview").click(); })()`);
      const state = await cdp.evaluate(`({reviewerVisible:!document.getElementById("console-reviewer").hidden, submitEnabled:!document.getElementById("review-submit").disabled, outcome:document.getElementById("review-result").textContent})`);
      assert(state.reviewerVisible, "reviewer panel did not activate");
      assert(state.submitEnabled, "review submit was not unlocked by a valid preview");
      assert(state.outcome.includes("Буде надіслано") && state.outcome.includes("Наслідок"), "review consequence preview is absent");
    }, results);
  } finally {
    try { cdp?.close(); } catch {}
    chromium.kill("SIGTERM");
    await waitForExit(chromium);
    for (let attempt=0; attempt<5; attempt++) {
      try { await rm(profile,{recursive:true,force:true}); break; }
      catch (error) { if (attempt===4) throw error; await new Promise(resolve=>setTimeout(resolve,100)); }
    }
  }

  const passed = results.filter(item => item.status === "PASS").length;
  const report = {
    schema_version:1, gate:"browser_e2e", environment_class:"LOCAL_BROWSER_POLICY_COMPATIBLE",
    transport_fixture:"browser_fetch_stub", navigation_policy:"system URLBlocklist prevents local HTTP navigation",
    network_navigation_executed:false, same_origin_network_executed:false, oidc_session_executed:false,
    release_version:release.version, release_tag:release.tag, git_head:gitHead, git_context:gitHead?"repository":"gitless_package",
    browser:version, browser_binary:BROWSER, tests:results,
    totals:{tests:results.length, passed, failed:results.length-passed}, status:passed===results.length?"PASS":"FAIL",
    browser_stderr_tail:browserErr.trim().split("\n").slice(-8),
  };
  await mkdir(dirname(REPORT), {recursive:true});
  await writeFile(REPORT, `${JSON.stringify(report,null,2)}\n`);
  process.stdout.write(`${JSON.stringify(report,null,2)}\n`);
  if (report.status !== "PASS") process.exitCode=1;
}

main().catch(async error => {
  const report={schema_version:1,gate:"browser_e2e",status:"FAIL",fatal:String(error?.stack??error)};
  try { await mkdir(dirname(REPORT), {recursive:true}); await writeFile(REPORT,`${JSON.stringify(report,null,2)}\n`); } catch {}
  console.error(error); process.exitCode=1;
});
