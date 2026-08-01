import { createHash } from "node:crypto";
import { cp, readFile, rm, mkdir, writeFile } from "node:fs/promises";
const source = new URL("../public", import.meta.url);
const destination = new URL("../dist", import.meta.url);
await rm(destination, {recursive:true,force:true});
await mkdir(destination, {recursive:true});
await cp(source, destination, {recursive:true});
const shellAssets = [
  "index.html",
  "styles.css",
  "app.js",
  "config.js",
  "manifest.webmanifest",
];
const digest = createHash("sha256");
for (const asset of shellAssets) {
  digest.update(asset);
  digest.update(await readFile(new URL(`../public/${asset}`, import.meta.url)));
}
const shellDigest = digest.digest("hex");
const serviceWorkerPath = new URL("../dist/sw.js", import.meta.url);
const serviceWorker = await readFile(serviceWorkerPath, "utf8");
if (!serviceWorker.includes("__SHELL_DIGEST__"))
  throw new Error("service worker cache digest placeholder missing");
await writeFile(
  serviceWorkerPath,
  serviceWorker.replaceAll("__SHELL_DIGEST__", shellDigest),
);
console.log("web build completed");
