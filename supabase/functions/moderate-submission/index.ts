// Edge Function: moderate-submission
//
// The endpoint the Approve/Reject buttons in the notification email point at.
// Security: every link carries an HMAC token over `${id}:${action}` signed with
// MODERATION_HMAC_KEY, so a leaked submission UUID alone can't moderate
// anything. JWT verification is OFF for this function (it's opened from an email
// in a browser with no Supabase auth) — the HMAC token IS the auth.
//
// Anti-prefetch: a GET only renders a confirmation page (no mutation). The actual
// approve/reject happens on POST (the form button on that page). This stops email
// link scanners / Gmail prefetch from silently approving content on a bare GET.
//
// On POST it calls the service-role RPCs approve_user_submission /
// reject_user_submission (single source of truth, shared with the CLI), then
// refresh_searchable_images() so an approved review appears in search immediately.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SIGNING_SECRET = Deno.env.get("MODERATION_HMAC_KEY")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

async function hmacHex(data: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(SIGNING_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Constant-time-ish comparison to avoid leaking the token via timing.
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

function htmlPage(title: string, body: string, status = 200): Response {
  const html = `<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>
  body{font-family:system-ui,Arial,sans-serif;max-width:540px;margin:48px auto;padding:0 20px;color:#111}
  .card{border:1px solid #e4e4e4;border-radius:12px;padding:24px}
  h2{margin:0 0 12px}
  .meta{font-size:14px;color:#555;margin:0 0 18px;line-height:1.5}
  button{font-size:15px;font-weight:600;padding:11px 18px;border-radius:8px;border:none;cursor:pointer}
  .approve{background:#1e8e3e;color:#fff}
  .reject{background:#c0392b;color:#fff}
  .muted{color:#888;font-size:13px;margin-top:14px}
</style></head><body><div class="card">${`<h2>${title}</h2>`}${body}</div></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8" } });
}

Deno.serve(async (req) => {
  let id = "", action = "", token = "";
  if (req.method === "POST") {
    const form = await req.formData();
    id = String(form.get("id") ?? "");
    action = String(form.get("action") ?? "");
    token = String(form.get("token") ?? "");
  } else {
    const u = new URL(req.url);
    id = u.searchParams.get("id") ?? "";
    action = u.searchParams.get("action") ?? "";
    token = u.searchParams.get("token") ?? "";
  }

  if (!id || (action !== "approve" && action !== "reject") || !token) {
    return htmlPage("Invalid link", "<p class='meta'>This link is missing required parameters.</p>", 400);
  }

  const expected = await hmacHex(`${id}:${action}`);
  if (!safeEqual(token, expected)) {
    return htmlPage("Link could not be verified", "<p class='meta'>This moderation link is invalid or has been tampered with.</p>", 403);
  }

  const sb = createClient(SUPABASE_URL, SERVICE_ROLE);

  // GET → confirmation page only (no mutation). POST → perform the action.
  if (req.method !== "POST") {
    const { data: sub } = await sb
      .from("user_review_submissions")
      .select("status, brand, size_purchased, image_paths")
      .eq("id", id)
      .maybeSingle();

    if (!sub) return htmlPage("Not found", "<p class='meta'>That submission no longer exists.</p>", 404);
    if (sub.status !== "pending") {
      return htmlPage("Already handled", `<p class='meta'>This submission was already <b>${sub.status}</b>. No further action is needed.</p>`);
    }

    const nPhotos = Array.isArray(sub.image_paths) ? sub.image_paths.length : 0;
    const verb = action === "approve" ? "Approve" : "Reject";
    const cls = action === "approve" ? "approve" : "reject";
    return htmlPage(
      `${verb} this review?`,
      `<p class="meta">Brand: <b>${sub.brand ?? "—"}</b> · Size: <b>${sub.size_purchased ?? "—"}</b> · ${nPhotos} photo(s)</p>
       <form method="POST" action="${req.url.replace(/&/g, "&amp;")}">
         <input type="hidden" name="id" value="${id}">
         <input type="hidden" name="action" value="${action}">
         <input type="hidden" name="token" value="${token}">
         <button type="submit" class="${cls}">${verb}</button>
       </form>
       <p class="muted">${action === "approve" ? "Approving publishes the review and its photos to the site." : "Rejecting keeps it off the site permanently."}</p>`,
    );
  }

  // POST → execute
  try {
    if (action === "approve") {
      const { data, error } = await sb.rpc("approve_user_submission", {
        p_submission_id: id,
        p_storage_base_url: SUPABASE_URL,
      });
      if (error) throw error;
      await sb.rpc("refresh_searchable_images");
      const n = (data as { image_count?: number })?.image_count ?? 0;
      return htmlPage("Approved ✅", `<p class="meta">This review is now live. ${n} photo(s) published to the site.</p>`);
    } else {
      const { error } = await sb.rpc("reject_user_submission", {
        p_submission_id: id,
        p_reason: "Rejected via email link",
      });
      if (error) throw error;
      return htmlPage("Rejected", "<p class='meta'>This submission was rejected and will not appear on the site.</p>");
    }
  } catch (e) {
    const msg = String((e as { message?: string })?.message ?? e);
    if (/not pending|already exists/i.test(msg)) {
      return htmlPage("Already handled", `<p class='meta'>This submission was already moderated.</p>`);
    }
    return htmlPage("Something went wrong", `<p class='meta'>${msg}</p>`, 500);
  }
});
