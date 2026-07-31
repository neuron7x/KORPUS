import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
const root = normalize(join(process.cwd(), process.argv[2] ?? "public"));
const mime = {".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".json":"application/json",".webmanifest":"application/manifest+json"};
createServer(async (request,response) => {
  try {
    const raw = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
    let path = normalize(join(root, raw === "/" ? "index.html" : raw));
    if (!path.startsWith(root)) throw new Error("path traversal");
    try { if ((await stat(path)).isDirectory()) path = join(path,"index.html"); } catch { path = join(root,"index.html"); }
    response.writeHead(200,{"Content-Type":mime[extname(path)] ?? "application/octet-stream","Cache-Control":"no-store"});
    response.end(await readFile(path));
  } catch { response.writeHead(404); response.end("not found"); }
}).listen(3000,"127.0.0.1",()=>console.log("KORPUS web http://127.0.0.1:3000"));
