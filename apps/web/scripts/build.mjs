import { cp, rm, mkdir } from "node:fs/promises";
const source = new URL("../public", import.meta.url);
const destination = new URL("../dist", import.meta.url);
await rm(destination, {recursive:true,force:true});
await mkdir(destination, {recursive:true});
await cp(source, destination, {recursive:true});
console.log("web build completed");
