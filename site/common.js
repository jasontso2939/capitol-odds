// Shared helpers for every page: escaping, session labels, page state in the URL,
// CSV downloads, lazy loading of data files, and the site navigation.
const CL = (() => {
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const label = y => `${y}-${String(+y + 1).slice(2)}`;

  // Page state lives in the query string, so any view can be shared or bookmarked.
  // defaults: {key: default value}; values equal to the default are left out of the URL.
  function readState(defaults) {
    const p = new URLSearchParams(location.search), o = {...defaults};
    for (const k of Object.keys(defaults)) if (p.has(k)) {
      const v = p.get(k);
      o[k] = typeof defaults[k] === "number" ? (Number.isFinite(+v) ? +v : defaults[k]) : typeof defaults[k] === "boolean" ? v === "1" : v;
    }
    return o;
  }
  function writeState(st, defaults) {
    const p = new URLSearchParams();
    for (const k of Object.keys(defaults)) {
      const v = st[k];
      if (v == null || v === "" || String(v) === String(defaults[k])) continue;
      p.set(k, typeof v === "boolean" ? (v ? "1" : "0") : v);
    }
    const q = p.toString();
    history.replaceState(null, "", (q ? "?" + q : location.pathname.split("/").pop() || "./") + location.hash);
  }

  // CSV download. rows: array of arrays (with header) or array of objects (header from keys).
  function csv(filename, rows, header) {
    if (rows.length && !Array.isArray(rows[0])) {
      header = header || Object.keys(rows[0]);
      rows = rows.map(r => header.map(h => r[h]));
    }
    const cell = v => v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
    const text = [header, ...rows].filter(Boolean).map(r => r.map(cell).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + text], {type: "text/csv;charset=utf-8"}));
    a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // Load a data script once; resolves when it has run.
  const loaded = {};
  function load(src) {
    return loaded[src] || (loaded[src] = new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = () => { delete loaded[src]; fail(new Error("Could not load " + src)); };
      document.head.appendChild(s);
    }));
  }

  // "Copy link" button: copies the current URL, which carries the page state.
  function shareButton(el) {
    el.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(location.href); el.textContent = "Link copied"; }
      catch (e) { prompt("Copy this link", location.href); }
      setTimeout(() => { el.textContent = "Copy link"; }, 1800);
    });
  }

  const PAGES = [["index.html", "Bill odds"], ["scorecard.html", "Scorecard"], ["legislator.html", "Legislators"],
                 ["trends.html", "Trends"], ["committees.html", "Committees"], ["findings.html", "Findings"]];
  function nav(current) {
    const n = document.querySelector("header nav");
    if (n) n.innerHTML = '<a class="brand" href="index.html" style="font-weight:700;letter-spacing:.02em;border-color:#f2a900;color:#f2a900">Capitol Odds</a>' + PAGES.map(([h, l]) => `<a href="${h}"${h === current ? ' aria-current="page"' : ""}>${l}</a>`).join("");
  }

  const pct = (a, b, d = 0) => b ? (100 * a / b).toFixed(d) + "%" : "–";
  const leginfo = (session, billId) =>
    `https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id=${session}${+session + 1}0${billId}`;
  return {esc, label, readState, writeState, csv, load, shareButton, nav, pct, leginfo};
})();
