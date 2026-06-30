// Edge Function: notify-submission
//
// Fired by a database webhook on INSERT into public.user_review_submissions
// (see dev_35 migration). Emails the operator (NOTIFY_EMAIL) a summary of the
// new submission plus signed one-tap Approve / Reject buttons that point at the
// moderate-submission function.
//
// Trust model: the webhook only sends the row id. We RE-FETCH the submission with
// the service role and build the email from the DB, never from the request body —
// so even if someone calls this function directly (the webhook uses the public
// anon key), they can't inject arbitrary email content; at worst they re-trigger a
// notification for a real pending row. The Approve/Reject tokens are HMAC-signed
// with MODERATION_HMAC_KEY, which the caller doesn't have, so forged links
// fail verification downstream.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SIGNING_SECRET = Deno.env.get("MODERATION_HMAC_KEY")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const RESEND_API_KEY = Deno.env.get("RESEND_KEY")!;
const NOTIFY_EMAIL = Deno.env.get("NOTIFY_EMAIL") || "bsinger3@gmail.com";
// Resend's shared sender works with no domain setup when emailing your own
// account address. Swap for a verified-domain sender when porting to prod.
const FROM = Deno.env.get("NOTIFY_FROM") || "FWM Reviews <onboarding@resend.dev>";

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

function esc(v: unknown): string {
  return String(v ?? "—").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}

function row(label: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  return `<tr><td style="padding:2px 12px 2px 0;color:#888">${label}</td><td style="padding:2px 0"><b>${esc(value)}</b></td></tr>`;
}

Deno.serve(async (req) => {
  let body: { type?: string; record?: { id?: string } };
  try {
    body = await req.json();
  } catch {
    return new Response("bad request", { status: 400 });
  }
  const id = body?.record?.id;
  if (!id) return new Response("ignored (no id)", { status: 200 });

  const sb = createClient(SUPABASE_URL, SERVICE_ROLE);
  const { data: s } = await sb.from("user_review_submissions").select("*").eq("id", id).maybeSingle();
  // Only notify for rows that are actually pending (ignore re-fires / already moderated).
  if (!s || s.status !== "pending") return new Response("ignored (not pending)", { status: 200 });

  const approveToken = await hmacHex(`${id}:approve`);
  const rejectToken = await hmacHex(`${id}:reject`);
  const base = `${SUPABASE_URL}/functions/v1/moderate-submission`;
  const approveUrl = `${base}?id=${id}&action=approve&token=${approveToken}`;
  const rejectUrl = `${base}?id=${id}&action=reject&token=${rejectToken}`;

  const paths: string[] = Array.isArray(s.image_paths) ? s.image_paths : [];
  const photosHtml = paths
    .map((p) => `${SUPABASE_URL}/storage/v1/object/public/review-uploads/${p}`)
    .map((u) => `<a href="${u}"><img src="${u}" alt="photo" width="90" style="border-radius:6px;margin:0 6px 6px 0;object-fit:cover"></a>`)
    .join("");

  const heightStr = s.height_in_total ? `${Math.floor(s.height_in_total / 12)}'${Math.round(s.height_in_total % 12)}"` : null;

  const html = `<div style="font-family:system-ui,Arial,sans-serif;max-width:560px;color:#111">
  <h2 style="margin:0 0 4px">New review submission</h2>
  <p style="color:#666;margin:0 0 16px">Review it, then tap a button below.</p>
  <div>${photosHtml || "<i style='color:#999'>No photos</i>"}</div>
  <table style="border-collapse:collapse;font-size:14px;margin:14px 0">
    ${row("Brand", s.brand)}
    ${row("Product URL", s.product_page_url)}
    ${row("Retailer", s.source_site)}
    ${row("Size", s.size_purchased)}
    ${row("Color", s.color)}
    ${row("Category", s.mother_category_id)}
    ${row("Height", heightStr)}
    ${row("Weight (lb)", s.weight_lbs)}
    ${row("Bra band", s.bra_band_in)}
    ${row("Cup", s.cup_size)}
    ${row("Full bust", s.bust_full_in)}
    ${row("Waist", s.waist_in)}
    ${row("Hips", s.hips_in)}
    ${row("Inseam", s.inseam_in)}
    ${row("Age", s.age_years)}
    ${row("Weeks pregnant", s.weeks_pregnant)}
    ${row("Comment", s.user_comment)}
    ${row("Reviewer", s.reviewer_name)}
    ${row("Email", s.reviewer_email)}
  </table>
  <p style="margin:18px 0">
    <a href="${approveUrl}" style="display:inline-block;background:#1e8e3e;color:#fff;text-decoration:none;font-weight:600;padding:11px 22px;border-radius:8px;margin-right:10px">Approve</a>
    <a href="${rejectUrl}" style="display:inline-block;background:#c0392b;color:#fff;text-decoration:none;font-weight:600;padding:11px 22px;border-radius:8px">Reject</a>
  </p>
  <p style="color:#999;font-size:12px">You'll get a confirmation screen before anything is published.</p>
</div>`;

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({
      from: FROM,
      to: [NOTIFY_EMAIL],
      subject: `New review: ${s.brand || "unknown brand"} — size ${s.size_purchased || "?"}`,
      html,
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    console.error("resend send failed", res.status, detail);
    return new Response(`email send failed: ${res.status}`, { status: 500 });
  }
  return new Response("notified", { status: 200 });
});
