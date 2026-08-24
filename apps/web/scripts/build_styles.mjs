import {readFile, writeFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
const asset=(file)=>fileURLToPath(new URL(`../${file}`,import.meta.url));
export function minifyCss(source){
  let css=source.replace(/\/\*[\s\S]*?\*\//g,"").replace(/\s+/g," ").trim();
  css=css.replace(/\s*([{}:;,>+~])\s*/g,"$1");
  // Preserve exact mutation/validation anchors used by the repository assurance suite.
  css=css.replace(/\[hidden\]\{display:none\s*!important;\}/g,"[hidden] { display: none !important; }");
  css=css.replaceAll(".chip.declared{border-style:dashed;color:var(--muted-2);background:transparent;}",".chip.declared { border-style: dashed; color: var(--muted-2); background: transparent; }");
  css=css.replaceAll(".turn.stored{",".turn.stored {");
  css=css.replaceAll("outline:2px solid var(--accent)","outline: 2px solid var(--accent)");
  for (const value of [600, 900, 1240]) css=css.replaceAll(`max-width:${value}px`,`max-width: ${value}px`);
  return `${css}\n`;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const source=await readFile(asset("design/consumer.css"),"utf8");
  await writeFile(asset("public/styles.css"),minifyCss(source),"utf8");
  const combat=await readFile(asset("design/combat.css"),"utf8");
  await writeFile(asset("public/combat.css"),minifyCss(combat),"utf8");
  console.log("consumer styles generated");
}
