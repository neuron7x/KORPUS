import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {minifyCss} from "../scripts/build_styles.mjs";
const asset=(file)=>fileURLToPath(new URL(`../${file}`,import.meta.url));
const read=(file)=>readFile(asset(file),"utf8");
test("approved truth surface is integrated into the real consumer shell", async()=>{
  const html=await read("public/index.html");
  for(const marker of ["pixel-wordmark","PREMIUM TRUST ARCHITECTURE","APPROVED SOURCES","FAIL CLOSED","quick-action","id=\"query-form\""]) assert.match(html,new RegExp(marker));
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
test("canonical and combat themes share one functional surface", async()=>{
  const html=await read("public/index.html"); const app=await read("public/app.js"); const source=await read("design/combat.css");
  assert.match(html,/id="theme-toggle"[^>]*aria-pressed="false"/);
  assert.match(app,/document\.documentElement\.dataset\.theme/);
  assert.match(app,/sessionStorage\.setItem\("korpus-theme", combat/);
  assert.match(source,/html\[data-theme="combat"\]/);
  assert.doesNotMatch(html,/combat[^>]+href=/i);
});
test("delivery CSS is generated from the readable approved source", async()=>{
  assert.equal(await read("public/styles.css"),minifyCss(await read("design/consumer.css")));
});
