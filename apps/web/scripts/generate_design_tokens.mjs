import {readFile,writeFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {renderTokensCss} from "./design_system.mjs";
const asset=(file)=>fileURLToPath(new URL(`../${file}`,import.meta.url));
const tokens=JSON.parse(await readFile(asset("design/tokens.json"),"utf8"));
await writeFile(asset("public/tokens.css"),renderTokensCss(tokens),"utf8");
console.log("design tokens generated");
