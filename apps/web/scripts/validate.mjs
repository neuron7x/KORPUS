import { readFile, stat } from "node:fs/promises";
const required = ["public/index.html","public/app.js","public/styles.css","public/manifest.webmanifest","public/sw.js"];
for (const file of required) {
  const info = await stat(new URL(`../${file}`, import.meta.url));
  if (!info.isFile() || info.size === 0) throw new Error(`invalid web asset: ${file}`);
}
const html = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
if (!html.includes('id="query-form"') || !html.includes('/app.js')) throw new Error("web shell contract failed");
JSON.parse(await readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"));
console.log("web validation passed");
