import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {minifyCss} from "../scripts/build_styles.mjs";
const asset=(file)=>fileURLToPath(new URL(`../${file}`,import.meta.url));
const read=(file)=>readFile(asset(file),"utf8");
test("approved truth surface is integrated into the real consumer shell", async()=>{
  const html=await read("public/index.html");
  for(const marker of ["pixel-wordmark","МАРШРУТ ВІДПОВІДІ","quick-action","id=\"query-form\""]) assert.match(html,new RegExp(marker));
  assert.doesNotMatch(html,/OFFLINE INTERFACE PROTOTYPE|mock evidence/i);
  assert.doesNotMatch(html,/<script(?![^>]*src=)/i);
});
test("approved palette and reduced motion are delivery contracts", async()=>{
  const tokens=await read("public/tokens.css"); const css=await read("public/styles.css");
  assert.match(tokens,/--bg: #010101;/); assert.match(tokens,/--accent: #c75550;/);
  assert.match(css,/prefers-reduced-motion:reduce/); assert.match(css,/\.quick-action\{min-height:var\(--target-min\)/);
});
test("quick actions only prefill the canonical query composer", async()=>{
  const app=await read("public/app.js");
  assert.match(app,/query\.value = action\.dataset\.template/);
  assert.doesNotMatch(app,/quick-action[\s\S]{0,500}fetch\(/);
});
test("conversation navigation starts collapsed", async()=>{
  const app=await read("public/app.js"); assert.match(app,/conversationsPanel\.open = false/);
});
test("visual noise is progressively disclosed without removing function", async()=>{
  const html=await read("public/index.html"); const app=await read("public/app.js"); const css=await read("design/consumer.css");
  assert.match(html,/id="mobile-nav"[^>]*hidden/); assert.match(app,/\$\("mobile-nav"\)\.hidden = false/);
  assert.doesNotMatch(html,/class="right-rail"/); assert.doesNotMatch(css,/\.right-rail/);
  assert.match(css,/#product\[data-chat-state="READY"\] \.trace-path/);
  assert.doesNotMatch(html,/class="entry-lockup"|class="hero-proof"|class="empty-trust"/);
  assert.match(html,/class="mobile-more"/); assert.match(css,/\.ask-section\{position:sticky/);
  assert.match(html,/<details id="standing"[^>]*status-disclosure/);
  assert.match(html,/<details id="evidence-trace"/);
  assert.equal((html.match(/class="quick-action"/g) ?? []).length,3);
  assert.match(app,/class="primary-evidence"/);
  assert.match(app,/class="additional-evidence"/);
});
test("canonical and combat themes share one functional surface", async()=>{
  const html=await read("public/index.html"); const app=await read("public/app.js"); const source=await read("design/combat.css"); const radar=await read("public/combat_scene.js");
  assert.match(html,/id="theme-toggle"[^>]*aria-pressed="false"/);
  assert.match(app,/document\.documentElement\.dataset\.theme/);
  assert.match(app,/sessionStorage\.setItem\("korpus-theme", combat/);
  assert.match(app,/import\("\.\/combat_scene\.js"\)/);
  assert.match(source,/html\[data-theme="combat"\]/);
  assert.match(source,/@keyframes combat-ignite/);
  assert.match(source,/@media\(prefers-reduced-motion:reduce\)/);
  assert.match(radar,/korpus:radar/); assert.match(radar,/source_hash/); assert.doesNotMatch(radar,/combat-radar-status|fillText/);
  assert.match(radar,/HOSTILE_BLIPS/); assert.match(radar,/}, 1400\)/); assert.match(radar,/hostile\.visible = !hostile\.visible/); assert.match(radar,/hostile\.count === 5 \? 3/);
  assert.match(source,/repeating-linear-gradient\(117deg/); assert.match(source,/background-clip:text/); assert.match(source,/image-rendering:pixelated/);
  assert.doesNotMatch(radar,/Math\.random/);
  assert.doesNotMatch(html,/combat[^>]+href=/i);
});
test("KORPUS TRACE projects the canonical chat state machine", async()=>{
  const html=await read("public/index.html"); const app=await read("public/app.js"); const trace=await read("public/trace.js");
  assert.match(html,/id="evidence-trace"[^>]+KORPUS TRACE/);
  assert.match(trace,/KORPUS TRACE/); assert.match(trace,/data-trace-stage="\$\{key\}"/); assert.match(trace,/aria-live="polite"/);
  assert.match(app,/import\("\.\/trace\.js"\)/);
  assert.match(app,/renderTraceState\(machine\.state\)/);
  assert.match(trace,/FAIL_CLOSED: \[3,/);
});
test("Decision Field is lazy, source-bound, and counterfactual", async()=>{
  const app=await read("public/app.js"); const field=await read("public/decision_field.js"); const css=await read("design/decision_field.css");
  assert.match(app,/import\("\.\/decision_field\.js"\)/);
  assert.match(field,/evidence_coverage/); assert.match(field,/answer\.citations/); assert.match(field,/answer\.limitations/);
  assert.match(field,/Що змінить цей вердикт/); assert.match(field,/НЕ ЙМОВІРНІСТЬ/);
  assert.match(field,/document\.createElement\("details"\)/);
  assert.doesNotMatch(field,/Math\.random|confidence|probability/i);
  assert.match(css,/\.decision-field/); assert.match(css,/@media\(max-width:700px\)/);
});
test("delivery CSS is generated from the readable approved source", async()=>{
  assert.equal(await read("public/styles.css"),minifyCss(await read("design/consumer.css")));
});
test("CSS minification preserves required calc addition whitespace",()=>{
  assert.equal(minifyCss(".x { bottom: calc(64px + env(safe-area-inset-bottom)); }"),".x{bottom:calc(64px + env(safe-area-inset-bottom));}\n");
});
