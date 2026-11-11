// Accounts: sign in with a one-time email code, then keep saved bills, notes and recently
// viewed bills on the server so they follow the person to any browser.
//
// No library: Supabase Auth and the database are plain HTTPS calls. The public browser key
// (ai-config.js) only reaches rows that row level security gives the signed-in person.
// Signed out, everything still works from this browser's storage, as before.
const CO_ACCOUNT = (() => {
  const cfg = window.CO_AI || {};
  const BASE = (cfg.endpoint || "").replace(/\/functions\/v1\/.*$/, "");
  const KEY = cfg.anonKey || "";
  const SKEY = "capitolodds.auth";
  const enabled = !!(BASE && KEY);
  let session = null;
  const listeners = new Set();

  const store = {
    get() { try { return JSON.parse(localStorage.getItem(SKEY) || "null"); } catch (e) { return null; } },
    set(v) { try { v ? localStorage.setItem(SKEY, JSON.stringify(v)) : localStorage.removeItem(SKEY); } catch (e) { /* storage blocked */ } },
  };
  // Keep only what's needed; expires_at in seconds since the epoch
  function keep(s) {
    if (!s || !s.access_token) return null;
    return {access_token: s.access_token, refresh_token: s.refresh_token,
      expires_at: s.expires_at || Math.floor(Date.now() / 1000) + (s.expires_in || 3600),
      user: s.user ? {id: s.user.id, email: s.user.email} : null};
  }
  function setSession(s) {
    session = keep(s); store.set(session);
    listeners.forEach(f => { try { f(session && session.user); } catch (e) { console.error(e); } });
  }

  async function auth(path, body) {
    const r = await fetch(`${BASE}/auth/v1/${path}`, {method: "POST", headers: {apikey: KEY, "Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.msg || j.error_description || j.message || `Sign-in failed (${r.status})`);
    return j;
  }

  // A code, not a link: work email systems often open links to scan them, which would use
  // up a one-time sign-in link before the person ever clicks it.
  const sendCode = email => auth("otp", {email: String(email).trim().toLowerCase(), create_user: true});
  async function verifyCode(email, code) {
    const j = await auth("verify", {type: "email", email: String(email).trim().toLowerCase(), token: String(code).replace(/\D/g, "")});
    setSession(j); return session.user;
  }
  let refreshing = null;
  async function fresh() {
    if (!session) return null;
    if (session.expires_at - 60 > Date.now() / 1000) return session;
    refreshing = refreshing || auth("token?grant_type=refresh_token", {refresh_token: session.refresh_token})
      .then(j => (setSession(j), session)).catch(() => (setSession(null), null)).finally(() => { refreshing = null; });
    return refreshing;
  }
  async function signOut() {
    const s = session; setSession(null);
    if (s) fetch(`${BASE}/auth/v1/logout`, {method: "POST", headers: {apikey: KEY, Authorization: `Bearer ${s.access_token}`}}).catch(() => {});
  }

  // Database calls as the signed-in person
  async function api(path, {method = "GET", body, prefer} = {}) {
    const s = await fresh();
    if (!s) throw new Error("Sign in first");
    const h = {apikey: KEY, Authorization: `Bearer ${s.access_token}`, "Content-Type": "application/json"};
    if (prefer) h.Prefer = prefer;
    const r = await fetch(`${BASE}/rest/v1/${path}`, {method, headers: h, body: body === undefined ? undefined : JSON.stringify(body)});
    if (r.status === 401) { setSession(null); throw new Error("Signed out. Sign in again."); }
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.message || `Request failed (${r.status})`); }
    return r.status === 204 || r.headers.get("content-length") === "0" ? null : r.json().catch(() => null);
  }
  const enc = encodeURIComponent;

  const watchlist = {
    list: session_ => api(`watchlist?select=session,bill_id,added_at${session_ ? `&session=eq.${+session_}` : ""}&order=added_at.desc`),
    add: (s, bill) => api("watchlist?on_conflict=user_id,session,bill_id", {method: "POST", body: {session: +s, bill_id: bill}, prefer: "resolution=ignore-duplicates,return=minimal"}),
    addMany: (s, bills) => bills.length ? api("watchlist?on_conflict=user_id,session,bill_id", {method: "POST", body: bills.map(b => ({session: +s, bill_id: b})), prefer: "resolution=ignore-duplicates,return=minimal"}) : null,
    remove: (s, bill) => api(`watchlist?session=eq.${+s}&bill_id=eq.${enc(bill)}`, {method: "DELETE"}),
  };
  const notes = {
    list: (s, bill) => api(`notes?select=id,session,bill_id,body,created_at,updated_at${s ? `&session=eq.${+s}` : ""}${bill ? `&bill_id=eq.${enc(bill)}` : ""}&order=created_at.desc`),
    add: (s, bill, body) => api("notes", {method: "POST", body: {session: +s, bill_id: bill, body}, prefer: "return=representation"}).then(r => r && r[0]),
    update: (id, body) => api(`notes?id=eq.${+id}`, {method: "PATCH", body: {body}, prefer: "return=minimal"}),
    remove: id => api(`notes?id=eq.${+id}`, {method: "DELETE"}),
  };
  const history = {
    record: (s, bill) => api("rpc/record_view", {method: "POST", body: {p_session: +s, p_bill: bill}}).catch(() => null),
    recent: (n = 25) => api(`history?select=session,bill_id,viewed_at,views&order=viewed_at.desc&limit=${+n}`),
    clear: () => api("history?bill_id=neq.__", {method: "DELETE"}),
  };
  const profile = {
    get: () => api("profiles?select=display_name,role,organization,digest_enabled,last_digest_at").then(r => r && r[0]),
    update: patch => api(`profiles?id=eq.${session.user.id}`, {method: "PATCH", body: patch, prefer: "return=minimal"}),
  };
  const deleteAccount = () => api("rpc/delete_my_account", {method: "POST", body: {}}).then(() => setSession(null));
  // Bill status is public: no sign-in needed
  async function billStatus(s, bills) {
    if (!enabled || !bills.length) return [];
    const r = await fetch(`${BASE}/rest/v1/bill_status?select=*&session=eq.${+s}&bill_id=in.(${bills.map(enc).join(",")})`, {headers: {apikey: KEY}});
    return r.ok ? r.json() : [];
  }

  // Nav link: "Sign in" or "My desk"
  function paintNav() {
    const a = document.querySelector('.topnav a[data-k="account"]');
    if (a) a.textContent = session ? "My desk" : "Sign in";
  }
  listeners.add(paintNav);

  session = enabled ? store.get() : null;
  const ready = enabled ? fresh() : Promise.resolve(null);
  ready.then(paintNav);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paintNav); else paintNav();
  // Another tab signed in or out
  addEventListener("storage", e => { if (e.key === SKEY) { session = store.get(); listeners.forEach(f => f(session && session.user)); } });

  return {
    enabled, ready, sendCode, verifyCode, signOut, api, watchlist, notes, history, profile, deleteAccount, billStatus,
    user: () => session && session.user,
    onChange: f => { listeners.add(f); return () => listeners.delete(f); },
  };
})();
