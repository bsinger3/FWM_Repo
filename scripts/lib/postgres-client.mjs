import { existsSync } from "node:fs";

const CANDIDATE_BIN_DIRS = [
  process.env.POSTGRES_CLIENT_BIN_DIR,
  "/opt/homebrew/opt/libpq/bin",
  "/usr/local/opt/libpq/bin",
  "/opt/homebrew/bin",
  "/usr/local/bin",
].filter(Boolean);

export function postgresClientTool(name) {
  for (const dir of CANDIDATE_BIN_DIRS) {
    const candidate = `${dir}/${name}`;
    if (existsSync(candidate)) return candidate;
  }
  return name;
}

export function postgresConnectionArgs(databaseUrl) {
  const url = new URL(databaseUrl);
  const dbname = decodeURIComponent(url.pathname.replace(/^\//, "") || "postgres");
  const args = [
    "--host",
    url.hostname,
    "--port",
    url.port || "5432",
    "--username",
    decodeURIComponent(url.username),
    "--dbname",
    dbname,
  ];
  const sslmode = url.searchParams.get("sslmode") || "require";
  const env = {
    PGPASSWORD: decodeURIComponent(url.password),
    PGSSLMODE: sslmode,
  };
  return { args, env };
}

export function redactDatabaseUrl(value) {
  return String(value || "").replace(/:\/\/([^:]+):([^@]+)@/g, "://$1:<redacted>@");
}
