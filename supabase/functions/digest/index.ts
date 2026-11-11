// Daily digest: one email each weekday morning listing what changed on a person's watchlist.
//
// POST (from the scheduler, with header x-digest-secret: DIGEST_CRON_SECRET)
//   Sends every due digest. Nobody gets an email on a day none of their bills moved.
// GET ?u=<user id>&t=<signature>
//   One-click unsubscribe from the link in each email (also used by List-Unsubscribe).
//
// Secrets: RESEND_API_KEY, DIGEST_CRON_SECRET, DIGEST_FROM (e.g. "Capitol Odds <digest@capitolodds.com>").
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided by Supabase.
// Deploy with --no-verify-jwt: the scheduler and the unsubscribe link carry their own checks.
import {compose} from "./compose.js";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const SERVICE = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const RESEND = Deno.env.get("RESEND_API_KEY") ?? "";
const SECRET = Deno.env.get("DIGEST_CRON_SECRET") ?? "";
const FROM = Deno.env.get("DIGEST_FROM") ?? "Capitol Odds <digest@capitolodds.com>";
const SELF = `${URL_}/functions/v1/digest`;

const H = {apikey: SERVICE, Authorization: `Bearer ${SERVICE}`, "Content-Type": "application/json"};
const rest = async (path: string, init: RequestInit = {}) => {
  const r = await fetch(`${URL_}/rest/v1/${path}`, {...init, headers: {...H, ...(init.headers ?? {})}});
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
};

async function sign(uid: string) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(SECRET), {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("unsub:" + uid)));
  return btoa(String.fromCharCode(...mac)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const same = (a: string, b: string) => a.length === b.length && [...a].reduce((x, c, i) => x | (c.charCodeAt(0) ^ b.charCodeAt(i)), 0) === 0;

async function emails(): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  for (let page = 1; ; page++) {
    const r = await fetch(`${URL_}/auth/v1/admin/users?page=${page}&per_page=1000`, {headers: H});
    if (!r.ok) throw new Error(`admin users: HTTP ${r.status}`);
    const {users} = await r.json();
    for (const u of users ?? []) if (u.email && u.email_confirmed_at) out.set(u.id, u.email);
    if (!users || users.length < 1000) return out;
  }
}

async function sendAll() {
  const profiles = await rest("profiles?digest_enabled=eq.true&select=id,display_name,last_digest_at");
  if (!profiles.length) return {sent: 0, skipped: 0};
  const mail = await emails();
  let sent = 0, skipped = 0;
  for (const p of profiles) {
    const to = mail.get(p.id);
    if (!to) { skipped++; continue; }
    const watch = await rest(`watchlist?user_id=eq.${p.id}&select=session,bill_id`);
    if (!watch.length) { skipped++; continue; }
    const ids = [...new Set(watch.map((w: {bill_id: string}) => w.bill_id))].join(",");
    const status = await rest(`bill_status?bill_id=in.(${ids})&select=*`);
    const u = `${SELF}?u=${p.id}&t=${await sign(p.id)}`;
    const d = compose({name: p.display_name, watch, status, since: p.last_digest_at ? new Date(p.last_digest_at) : null, unsubscribeUrl: u});
    if (!d) { skipped++; continue; }
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST", headers: {Authorization: `Bearer ${RESEND}`, "Content-Type": "application/json"},
      body: JSON.stringify({from: FROM, to, subject: d.subject, text: d.text, html: d.html,
        headers: {"List-Unsubscribe": `<${u}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}),
    });
    if (!r.ok) { console.error("send failed", p.id, r.status, await r.text()); continue; }
    await rest(`profiles?id=eq.${p.id}`, {method: "PATCH", body: JSON.stringify({last_digest_at: new Date().toISOString()}), headers: {Prefer: "return=minimal"}});
    sent++;
  }
  return {sent, skipped};
}

async function unsubscribe(u: string, t: string) {
  if (!/^[0-9a-f-]{36}$/.test(u) || !same(t, await sign(u))) return new Response("This link is not valid.", {status: 400});
  await rest(`profiles?id=eq.${u}`, {method: "PATCH", body: JSON.stringify({digest_enabled: false}), headers: {Prefer: "return=minimal"}});
  return new Response("<!doctype html><meta charset=utf-8><title>Unsubscribed</title><p style='font:16px system-ui;margin:3em auto;max-width:32em'>You won't get the Capitol Odds daily digest anymore. You can turn it back on from <a href='https://capitolodds.com/account.html'>your desk</a>.</p>",
    {headers: {"Content-Type": "text/html; charset=utf-8"}});
}

Deno.serve(async req => {
  const q = new URL(req.url).searchParams;
  if (q.has("u")) return unsubscribe(q.get("u") ?? "", q.get("t") ?? "");   // GET link or one-click POST
  if (req.method !== "POST" || !SECRET || !same(req.headers.get("x-digest-secret") ?? "", SECRET)) return new Response("Not found", {status: 404});
  try { return Response.json(await sendAll()); }
  catch (e) { console.error(e); return new Response("digest failed", {status: 500}); }
});
