import { loadDotEnv } from "./local-env.mjs";

export const PRODUCTION_SUPABASE_REF = "kmomndloorvrjzmiexxl";
export const PRODUCTION_SUPABASE_URL = `https://${PRODUCTION_SUPABASE_REF}.supabase.co`;
export const DEV_SUPABASE_REF = "gosqgqpftqlawvnyelkt";
export const DEV_SUPABASE_URL = `https://${DEV_SUPABASE_REF}.supabase.co`;

const APPROVED_DEV_PROJECTS = new Map([[DEV_SUPABASE_URL, DEV_SUPABASE_REF]]);

function normalizeSupabaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

export function supabaseRefFromUrl(supabaseUrl) {
  const normalized = normalizeSupabaseUrl(supabaseUrl);
  const host = new URL(normalized).hostname;
  return host.endsWith(".supabase.co") ? host.slice(0, -".supabase.co".length) : null;
}

export async function assertApprovedDevSupabase({
  cwd = process.cwd(),
  requireServiceRoleKey = false,
  loadEnv = true,
} = {}) {
  if (loadEnv) await loadDotEnv({ cwd });

  const supabaseUrl = normalizeSupabaseUrl(process.env.SUPABASE_URL);
  if (!supabaseUrl) {
    throw new Error("SUPABASE_URL is unset. Refusing to continue.");
  }
  if (supabaseUrl === PRODUCTION_SUPABASE_URL) {
    throw new Error(
      `SUPABASE_URL resolves to production (${PRODUCTION_SUPABASE_REF}). Refusing to continue.`,
    );
  }
  if (!APPROVED_DEV_PROJECTS.has(supabaseUrl)) {
    throw new Error(
      `SUPABASE_URL is not the approved dev Supabase URL. Got ${supabaseUrl}; expected ${DEV_SUPABASE_URL}.`,
    );
  }
  const resolvedRef = supabaseRefFromUrl(supabaseUrl);
  if (resolvedRef !== APPROVED_DEV_PROJECTS.get(supabaseUrl)) {
    throw new Error(
      `SUPABASE_URL ref mismatch. Got ${resolvedRef || "unknown"}; expected ${DEV_SUPABASE_REF}.`,
    );
  }
  if (requireServiceRoleKey && !process.env.SUPABASE_SERVICE_ROLE_KEY) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY is unset. Refusing to continue.");
  }

  return {
    ok: true,
    supabaseUrl,
    projectRef: resolvedRef,
    environment: "dev",
    productionUrl: PRODUCTION_SUPABASE_URL,
    approvedDevUrl: DEV_SUPABASE_URL,
  };
}

export function printGuardSummary(guard, { prefix = "Supabase guard" } = {}) {
  console.log(`${prefix}: ${guard.environment}`);
  console.log(`Resolved SUPABASE_URL: ${guard.supabaseUrl}`);
  console.log(`Resolved project ref: ${guard.projectRef}`);
}

export function requireExplicitWriteFlag({
  flagName = "FWM_DEV_DB_WRITE_OK",
  expectedValue = "yes-i-understand-this-is-dev",
} = {}) {
  if (process.env[flagName] !== expectedValue) {
    throw new Error(
      `Write mode requires ${flagName}=${expectedValue}. Dry-run first, then rerun only after reviewing the write summary.`,
    );
  }
}

export function assertApprovedDevDatabaseUrl(databaseUrl, { name = "DEV_DATABASE_URL" } = {}) {
  const value = String(databaseUrl || "");
  if (!value) {
    throw new Error(`${name} is unset. Refusing database write mode.`);
  }
  if (value.includes(PRODUCTION_SUPABASE_REF)) {
    throw new Error(`${name} appears to reference production (${PRODUCTION_SUPABASE_REF}). Refusing to continue.`);
  }
  if (!value.includes(DEV_SUPABASE_REF)) {
    throw new Error(`${name} does not contain the approved dev project ref (${DEV_SUPABASE_REF}). Refusing to continue.`);
  }
  return true;
}

export function assertProductionDatabaseUrl(databaseUrl, { name = "PROD_DATABASE_URL" } = {}) {
  const value = String(databaseUrl || "");
  if (!value) {
    throw new Error(`${name} is unset. Refusing production read workflow.`);
  }
  if (value.includes(DEV_SUPABASE_REF)) {
    throw new Error(`${name} appears to reference dev (${DEV_SUPABASE_REF}). Refusing production export.`);
  }
  if (!value.includes(PRODUCTION_SUPABASE_REF)) {
    throw new Error(`${name} does not contain the expected production project ref (${PRODUCTION_SUPABASE_REF}).`);
  }
  return true;
}

export async function callSupabaseRest({
  supabaseUrl,
  serviceRoleKey,
  path,
  method = "GET",
  searchParams = null,
  body = null,
  prefer = null,
}) {
  const url = new URL(path.replace(/^\/+/, ""), `${supabaseUrl}/rest/v1/`);
  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, value);
    }
  }
  const headers = {
    apikey: serviceRoleKey,
    Authorization: `Bearer ${serviceRoleKey}`,
  };
  if (body !== null) headers["Content-Type"] = "application/json";
  if (prefer) headers.Prefer = prefer;

  const response = await fetch(url, {
    method,
    headers,
    body: body === null ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) {
    throw new Error(`Supabase REST ${method} ${url.pathname} failed (${response.status}): ${text}`);
  }
  return { response, data };
}
