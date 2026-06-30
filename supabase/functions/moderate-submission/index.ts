// Edge Function: moderate-submission
//
// The endpoint the Approve/Reject buttons in the notification email point at.
// Security: every link carries an HMAC token over `${id}:${action}` signed with
// MODERATION_HMAC_KEY, so a leaked submission UUID alone can't moderate anything.
// JWT verification is OFF (opened from an email in a browser, no Supabase auth) —
// the HMAC token IS the auth.
//
// Note on the design: Supabase's edge runtime forces `content-type: text/plain`
// on function responses (a security measure — functions can't serve rendered HTML
// on the supabase.co domain), so an HTML confirmation page with a button can't
// render. We therefore perform the action directly on GET and return a plain-text
// result. This is genuine one-tap. (Gmail loads tracking pixels but does not GET
// action links, so emailed links aren't auto-triggered; if stricter anti-prefetch
// is ever needed, host a confirm page on the static site that POSTs here.)
//
// On a valid Approve it calls approve_user_submission + refresh_searchable_images;
// on Reject it calls reject_user_submission. Both RPCs are idempotent (they refuse
// anything not still 'pending'), so a double-tap is harmless.

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

function reply(message: string, status = 200): Response {
  return new Response(message + "\n", {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

Deno.serve(async (req) => {
  const u = new URL(req.url);
  const id = u.searchParams.get("id") ?? "";
  const action = u.searchParams.get("action") ?? "";
  const token = u.searchParams.get("token") ?? "";

  if (!id || (action !== "approve" && action !== "reject") || !token) {
    return reply("Invalid link — missing parameters.", 400);
  }

  const expected = await hmacHex(`${id}:${action}`);
  if (!safeEqual(token, expected)) {
    return reply("This moderation link is invalid or has been tampered with.", 403);
  }

  const sb = createClient(SUPABASE_URL, SERVICE_ROLE);
  try {
    if (action === "approve") {
      const { data, error } = await sb.rpc("approve_user_submission", {
        p_submission_id: id,
        p_storage_base_url: SUPABASE_URL,
      });
      if (error) throw error;
      await sb.rpc("refresh_searchable_images");
      const n = (data as { image_count?: number })?.image_count ?? 0;
      return reply(`Approved. This review is now live (${n} photo(s) published). You can close this tab.`);
    } else {
      const { error } = await sb.rpc("reject_user_submission", {
        p_submission_id: id,
        p_reason: "Rejected via email link",
      });
      if (error) throw error;
      return reply("Rejected. This submission will not appear on the site. You can close this tab.");
    }
  } catch (e) {
    const msg = String((e as { message?: string })?.message ?? e);
    if (/not pending|already exists/i.test(msg)) {
      return reply("This submission was already handled — no action taken.");
    }
    return reply(`Something went wrong: ${msg}`, 500);
  }
});
