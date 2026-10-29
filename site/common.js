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
    const label = el.textContent;
    el.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(location.href); el.textContent = "Link copied"; }
      catch (e) { prompt("Copy this link", location.href); }
      setTimeout(() => { el.textContent = label; }, 1800);
    });
  }

  // Top bar on every page. current: a file name, or "track" / "draft" for the two home views.
  const PAGES = [["track", "index.html", "Track"], ["draft", "index.html?v=draft", "Draft"], ["scorecard.html", "scorecard.html", "Scorecard"],
                 ["legislator.html", "legislator.html", "Legislators"], ["trends.html", "trends.html", "Trends"],
                 ["committees.html", "committees.html", "Committees"], ["findings.html", "findings.html", "Findings"]];
  const MARK = '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect x="1" y="1" width="24" height="24" rx="6" fill="#172A47"></rect><path d="M6 18.5l4.5-5 3.5 3 6-8" fill="none" stroke="#F2C14E" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
  function nav(current) {
    if (current === "index.html") current = "track";
    const old = document.querySelector("header nav");
    if (old) old.remove();
    let bar = document.querySelector(".topbar");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "topbar";
      document.body.prepend(bar);
    }
    bar.innerHTML = `<div class="topbar-in"><a class="brand" href="index.html">${MARK}<span>CAPITOL ODDS</span></a>` +
      `<nav class="topnav" aria-label="Main">${PAGES.map(([k, h, l]) => `<a href="${h}" data-k="${k}"${k === current ? ' aria-current="page"' : ""}>${l}</a>`).join("")}</nav></div>`;
  }
  function navCurrent(k) {
    document.querySelectorAll(".topnav a").forEach(a => a.toggleAttribute("aria-current", a.dataset.k === k));
    document.querySelectorAll(".topnav a[aria-current]").forEach(a => a.setAttribute("aria-current", "page"));
  }

  const pct = (a, b, d = 0) => b ? (100 * a / b).toFixed(d) + "%" : "–";
  const leginfo = (session, billId) =>
    `https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id=${session}${+session + 1}0${billId}`;
  return {esc, label, readState, writeState, csv, load, shareButton, nav, navCurrent, pct, leginfo};
})();
