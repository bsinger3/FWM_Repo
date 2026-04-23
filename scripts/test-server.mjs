import { createServer } from "node:http";
import { createReadStream, existsSync } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4173);

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".ts", "text/plain; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".xml", "application/xml; charset=utf-8"],
  [".txt", "text/plain; charset=utf-8"],
  [".svg", "image/svg+xml"],
]);

function send404(res) {
  res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
  res.end("Not found");
}

function resolvePath(urlPath) {
  const cleanPath = decodeURIComponent(urlPath.split("?")[0]);
  const normalized = cleanPath === "/" ? "/index.html" : cleanPath;
  const candidate = path.resolve(rootDir, `.${normalized}`);
  if (!candidate.startsWith(rootDir)) {
    return null;
  }
  return candidate;
}

const server = createServer(async (req, res) => {
  const filePath = resolvePath(req.url || "/");
  if (!filePath || !existsSync(filePath)) {
    send404(res);
    return;
  }

  const fileStats = await stat(filePath);
  if (!fileStats.isFile()) {
    send404(res);
    return;
  }

  const ext = path.extname(filePath);
  res.writeHead(200, {
    "content-type": contentTypes.get(ext) || "application/octet-stream",
    "cache-control": "no-store",
  });
  createReadStream(filePath).pipe(res);
});

server.listen(port, host, () => {
  console.log(`Test server running at http://${host}:${port}`);
});
