// Builds one person's daily digest from their watchlist and the bills that changed.
// Plain JavaScript with no imports, so the server function and the tests share it.

const SITE = "https://capitolodds.com";
const OUT = {signed: "Signed", vetoed: "Vetoed", not_enacted: "Did not pass", pending: "Moving"};

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const spaced = id => String(id).replace(/^([A-Z]+)(\d+)$/, "$1 $2");
const pct = p => p == null ? "–" : Math.round(p * 100) + "%";

// Change in odds since introduction, in points; null when either side is unknown
export function move(now, before) {
  if (now == null || before == null) return null;
  return Math.round((now - before) * 100);
}

// watch: [{session, bill_id}], status: rows of bill_status, since: Date or null (first digest).
// Returns null when nothing on the watchlist changed, so no empty emails go out.
export function compose({name, watch, status, since, unsubscribeUrl}) {
  const byKey = new Map(status.map(s => [`${s.session}:${s.bill_id}`, s]));
  const changed = [], quiet = [];
  for (const w of watch) {
    const s = byKey.get(`${w.session}:${w.bill_id}`);
    if (!s) continue;
    const isNew = !since || new Date(s.changed_at) > since;
    (isNew ? changed : quiet).push({...s, delta: move(s.odds, s.odds_intro)});
  }
  if (!changed.length) return null;
  // Biggest news first: finished bills, then the largest moves in odds, then newest action
  changed.sort((a, b) => (b.outcome !== "pending") - (a.outcome !== "pending")
    || Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0)
    || String(b.last_action_date ?? "").localeCompare(String(a.last_action_date ?? "")));

  const n = changed.length;
  const subject = n === 1
    ? `${spaced(changed[0].bill_id)}: ${changed[0].last_action ? clip(changed[0].last_action, 60) : "new activity"}`
    : `${n} of your bills moved`;
  const link = s => `${SITE}/index.html?v=track&b=${encodeURIComponent(s.bill_id)}`;
  const line = s => {
    const d = s.delta == null || s.delta === 0 ? "" : ` (${s.delta > 0 ? "+" : ""}${s.delta} pts since introduction)`;
    return {s, odds: `${pct(s.odds)}${d}`};
  };

  const text = [
    `Good morning${name ? ", " + name : ""}. ${n === 1 ? "One bill" : n + " bills"} on your watchlist changed.`, "",
    ...changed.map(s => { const l = line(s);
      return `${spaced(s.bill_id)}  ${s.title ?? ""}\n  ${s.last_action ?? "Status updated"}${s.last_action_date ? " (" + s.last_action_date + ")" : ""}\n  ${OUT[s.outcome] ?? "Moving"} · odds ${l.odds}\n  ${link(s)}`; }),
    "", quiet.length ? `${quiet.length} other watched bill${quiet.length === 1 ? "" : "s"} had no news.` : "",
    "", `Your desk: ${SITE}/account.html`, `Stop these emails: ${unsubscribeUrl}`,
  ].join("\n");

  const html = `<div style="font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#18201C;max-width:620px">
<p>Good morning${name ? ", " + esc(name) : ""}. ${n === 1 ? "One bill" : n + " bills"} on your watchlist changed.</p>
<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%">${changed.map(s => { const l = line(s);
    return `<tr><td style="padding:12px 0;border-top:1px solid #E2E6E3">
<a href="${link(s)}" style="color:#24573F;font-weight:600;text-decoration:none">${esc(spaced(s.bill_id))}</a> <span style="color:#4A554F">${esc(s.title ?? "")}</span><br>
${esc(s.last_action ?? "Status updated")}${s.last_action_date ? ` <span style="color:#6B756F">(${esc(s.last_action_date)})</span>` : ""}<br>
<span style="color:#4A554F">${OUT[s.outcome] ?? "Moving"} · odds ${esc(l.odds)}</span></td></tr>`; }).join("")}</table>
${quiet.length ? `<p style="color:#6B756F">${quiet.length} other watched bill${quiet.length === 1 ? "" : "s"} had no news.</p>` : ""}
<p><a href="${SITE}/account.html" style="color:#24573F">Open your desk</a></p>
<p style="color:#6B756F;font-size:12px">You get this because you turned on the daily digest at Capitol Odds. <a href="${esc(unsubscribeUrl)}" style="color:#6B756F">Stop these emails</a>.</p></div>`;
  return {subject, text, html, count: n};
}

function clip(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; }
