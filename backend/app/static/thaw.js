(function () {
  "use strict";
  // Set the real page paths from main.py
  var NAV = [
    { id: "practice", label: "Practice", href: "/practice-test", icon: "play" },
    { id: "review", label: "Image review", href: "/review", icon: "image" },
    { id: "editor", label: "Page editor", href: "/editor", icon: "edit" },
    { id: "admin", label: "Admin", href: "/admin-test", icon: "shield", admin: true }
  ];
  var ICONS = {
    play: '<circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4z"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M4 18l5-5 4 4 3-3 4 4"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>'
  };
  var LOGO = '<svg width="32" height="32" viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="tgx" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#3CC7E8"/><stop offset="1" stop-color="#0E7C9B"/></linearGradient></defs><rect width="48" height="48" rx="12" fill="url(#tgx)"/><path d="M24 9C24 9 14 21 14 28a10 10 0 0 0 20 0C34 21 24 9 24 9Z" fill="#fff"/><path d="M24 21v15M16.5 28.5h15" stroke="#0E7C9B" stroke-width="2.5" stroke-linecap="round"/></svg>';
  var installEvent = null;

  function icon(name) {
    return '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + "</svg>";
  }

  /* Theme */
  function initialTheme() {
    try { var s = localStorage.getItem("thaw-theme"); if (s === "dark" || s === "light") return s; } catch (e) {}
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("thaw-theme", t); } catch (e) {}
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.textContent = t === "dark" ? "\uD83C\uDF19" : "\u2600\uFE0F";
      b.setAttribute("aria-label", "Switch to " + (t === "dark" ? "light" : "dark") + " theme");
    });
  }

  /* Toasts and confirm dialog */
  function toast(msg, type, ms) {
    var host = document.getElementById("thawToasts");
    if (!host) { host = document.createElement("div"); host.id = "thawToasts"; host.className = "toasts"; host.setAttribute("aria-live", "polite"); document.body.appendChild(host); }
    var t = document.createElement("div");
    t.className = "toast" + (type ? " " + type : "");
    t.textContent = msg;
    host.appendChild(t);
    setTimeout(function () { t.style.transition = "opacity .25s"; t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 260); }, ms || 3500);
  }
  function confirmDialog(o) {
    o = o || {};
    return new Promise(function (resolve) {
      var back = document.createElement("div"); back.className = "modal-backdrop";
      var box = document.createElement("div"); box.className = "modal-content"; box.setAttribute("role", "alertdialog"); box.setAttribute("aria-modal", "true");
      var h = document.createElement("h3"); h.textContent = o.title || "Are you sure?";
      var p = document.createElement("p"); p.className = "hint"; p.textContent = o.body || "";
      var row = document.createElement("div"); row.className = "row"; row.style.justifyContent = "flex-end"; row.style.marginTop = "16px";
      var no = document.createElement("button"); no.type = "button"; no.className = "ghost"; no.textContent = o.cancelText || "Cancel";
      var yes = document.createElement("button"); yes.type = "button"; yes.className = o.danger ? "danger" : "primary"; yes.textContent = o.confirmText || "Confirm";
      function onKey(e) { if (e.key === "Escape") close(false); }
      function close(v) { document.removeEventListener("keydown", onKey); back.remove(); resolve(v); }
      no.onclick = function () { close(false); };
      yes.onclick = function () { close(true); };
      back.addEventListener("click", function (e) { if (e.target === back) close(false); });
      document.addEventListener("keydown", onKey);
      row.appendChild(no); row.appendChild(yes); box.appendChild(h); box.appendChild(p); box.appendChild(row); back.appendChild(box);
      document.body.appendChild(back); yes.focus();
    });
  }

  /* Busy state and run wrapper */
  function setBusy(btn, on, text) {
    if (!btn) return;
    if (on) {
      if (btn.dataset.label === undefined) btn.dataset.label = btn.innerHTML;
      btn.disabled = true; btn.classList.add("is-busy");
      btn.innerHTML = '<span class="spin"></span><span>' + (text || "Working") + "\u2026</span>";
    } else {
      if (btn.dataset.label !== undefined) { btn.innerHTML = btn.dataset.label; delete btn.dataset.label; }
      btn.disabled = false; btn.classList.remove("is-busy");
    }
  }
  // Thaw.run(button, asyncFunction, { busy: "Uploading", ok: "Uploaded" }) -> { ok: true, value } or { ok: false, error }
  function run(btn, fn, o) {
    o = o || {};
    setBusy(btn, true, o.busy);
    return Promise.resolve().then(fn).then(function (value) {
      setBusy(btn, false);
      if (o.ok) toast(o.ok, "ok");
      if (btn && o.flash !== false) { btn.classList.add("is-ok"); setTimeout(function () { btn.classList.remove("is-ok"); }, 900); }
      return { ok: true, value: value };
    }, function (error) {
      setBusy(btn, false);
      toast((error && error.message) || "Something went wrong", "bad", 5000);
      return { ok: false, error: error };
    });
  }

  /* Current user, cached for 5 minutes so every page shares one call */
  function me(force) {
    try { var c = JSON.parse(sessionStorage.getItem("thaw-me") || "null"); if (c && !force && Date.now() - c.t < 300000) return Promise.resolve(c.v); } catch (e) {}
    var tok = ""; try { tok = localStorage.getItem("token") || ""; } catch (e) {}
    if (!tok) return Promise.resolve(null);
    return fetch("/auth/me", { headers: { Authorization: "Bearer " + tok } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (v) { if (v) { try { sessionStorage.setItem("thaw-me", JSON.stringify({ t: Date.now(), v: v })); } catch (e) {} } return v; })
      .catch(function () { return null; });
  }

  /* Shared header and navigation: needs <header id="thawTop"></header> in the page */
  function mountShell(o) {
    o = o || {};
    var top = document.getElementById("thawTop");
    if (!top) return;
    var items = NAV.filter(function (n) { return !n.admin || o.isAdmin; });
    var links = items.map(function (n) { return '<a href="' + n.href + '"' + (n.id === o.active ? ' aria-current="page"' : "") + ">" + n.label + "</a>"; }).join("");
    var acts = (o.actions || []).map(function (a) { return '<a href="#" id="' + a.id + '"' + (a.danger ? ' class="danger-link"' : "") + ">" + a.label + "</a>"; }).join("");
    top.className = "topbar";
    top.innerHTML = '<a class="brand" href="' + (o.home || NAV[0].href) + '" aria-label="Thaw home">' + LOGO + "<span>Thaw</span></a>" +
      '<nav class="nav" aria-label="Main">' + links + "</nav>" +
      '<div class="top-actions"><button type="button" class="icon ghost" data-theme-toggle></button>' +
      '<div class="menu"><button type="button" class="icon tonal" id="menuBtn" aria-haspopup="true" aria-expanded="false" aria-label="Account menu">' + (o.initial || "U") + "</button>" +
      '<div class="menu-list hidden" id="menuList">' + acts + '<a href="#" id="installBtn" class="hidden">Install app</a></div></div></div>';
    var tabs = document.getElementById("thawTabs");
    if (!tabs) { tabs = document.createElement("nav"); tabs.id = "thawTabs"; document.body.appendChild(tabs); }
    tabs.className = "tabbar"; tabs.setAttribute("aria-label", "Main");
    tabs.innerHTML = items.map(function (n) { return '<a href="' + n.href + '"' + (n.id === o.active ? ' aria-current="page"' : "") + ">" + icon(n.icon) + "<span>" + n.label + "</span></a>"; }).join("");
    document.body.classList.add("has-nav");
    if (installEvent) document.getElementById("installBtn").classList.remove("hidden");
    applyTheme(document.documentElement.getAttribute("data-theme") || initialTheme());
  }

  /* One click handler for the shared widgets */
  function syncChips(group) {
    var target = document.getElementById(group.getAttribute("data-for"));
    group.querySelectorAll(".chip-btn").forEach(function (c) { c.setAttribute("aria-pressed", String(!!target && c.getAttribute("data-value") === String(target.value))); });
  }
  document.addEventListener("click", function (e) {
    var t = e.target; if (!t.closest) return;
    if (t.closest("[data-theme-toggle]")) { applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"); return; }
    var mb = t.closest("#menuBtn"), list = document.getElementById("menuList");
    if (mb && list) { var open = list.classList.toggle("hidden") === false; mb.setAttribute("aria-expanded", String(open)); return; }
    if (list && !list.classList.contains("hidden") && (!t.closest("#menuList") || t.closest("a"))) list.classList.add("hidden");
    if (t.closest("#installBtn") && installEvent) { e.preventDefault(); installEvent.prompt(); return; }
    var st = t.closest(".stepper button[data-step]");
    if (st) {
      var inp = st.parentElement.querySelector("input");
      if (inp) {
        var min = inp.min === "" ? -Infinity : Number(inp.min), max = inp.max === "" ? Infinity : Number(inp.max);
        inp.value = String(Math.min(max, Math.max(min, (Number(inp.value) || 0) + Number(st.getAttribute("data-step")))));
        inp.dispatchEvent(new Event("input", { bubbles: true }));
      }
      return;
    }
    var cb = t.closest(".chips[data-for] .chip-btn[data-value]");
    if (cb) {
      var grp = cb.parentElement, target = document.getElementById(grp.getAttribute("data-for"));
      if (target) { target.value = cb.getAttribute("data-value"); target.dispatchEvent(new Event("input", { bubbles: true })); syncChips(grp); }
      return;
    }
    var br = t.closest("[data-browse]");
    if (br) { var fi = document.getElementById(br.getAttribute("data-browse")); if (fi) fi.click(); return; }
    var im = t.closest("img[data-zoom]");
    if (im && im.src) {
      var lb = document.createElement("div"); lb.className = "lightbox"; lb.setAttribute("role", "dialog");
      var big = document.createElement("img"); big.src = im.src; big.alt = im.alt || "";
      lb.appendChild(big); lb.addEventListener("click", function () { lb.remove(); }); document.body.appendChild(lb);
      return;
    }
    if (t.classList.contains("modal-backdrop") && t.id && t.id !== "tutorial") t.classList.add("hidden");
  });
  document.addEventListener("input", function (e) {
    if (e.target.id) document.querySelectorAll('.chips[data-for="' + e.target.id + '"]').forEach(syncChips);
  });

  /* Press feedback: ripple and a short vibration on touch phones */
  document.addEventListener("pointerdown", function (e) {
    var b = e.target.closest && e.target.closest("button, .btn");
    if (!b || b.disabled) return;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      var r = b.getBoundingClientRect(), s = Math.max(r.width, r.height) * 1.6, d = document.createElement("span");
      d.className = "ripple"; d.style.width = d.style.height = s + "px";
      d.style.left = (e.clientX - r.left - s / 2) + "px"; d.style.top = (e.clientY - r.top - s / 2) + "px";
      b.appendChild(d); setTimeout(function () { d.remove(); }, 550);
    }
    if (navigator.vibrate && e.pointerType === "touch") { try { navigator.vibrate(8); } catch (x) {} }
  }, { passive: true });

  /* Drag and drop onto .drop[data-input="fileInputId"] */
  document.addEventListener("dragover", function (e) { var d = e.target.closest && e.target.closest(".drop"); e.preventDefault(); if (d) d.classList.add("over"); });
  document.addEventListener("dragleave", function (e) { var d = e.target.closest && e.target.closest(".drop"); if (d) d.classList.remove("over"); });
  document.addEventListener("drop", function (e) {
    var d = e.target.closest && e.target.closest(".drop"); e.preventDefault();
    if (!d) return;
    d.classList.remove("over");
    var inp = document.getElementById(d.getAttribute("data-input"));
    if (inp && e.dataTransfer && e.dataTransfer.files.length) { inp.files = e.dataTransfer.files; inp.dispatchEvent(new Event("change", { bubbles: true })); }
  });

  /* Escape closes lightboxes and modals that have an id (not the tutorial) */
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var lb = document.querySelector(".lightbox"); if (lb) { lb.remove(); return; }
    var m = document.querySelector(".modal-backdrop:not(.hidden)");
    if (m && m.id && m.id !== "tutorial") m.classList.add("hidden");
  });
  /* Lock page scroll while a modal is open */
  new MutationObserver(function () {
    document.body.style.overflow = document.querySelector(".modal-backdrop:not(.hidden)") ? "hidden" : "";
  }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ["class"] });

  window.addEventListener("offline", function () { toast("You are offline. Practice needs an internet connection.", "bad", 6000); });
  window.addEventListener("online", function () { toast("Back online", "ok"); });
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault(); installEvent = e;
    var b = document.getElementById("installBtn"); if (b) b.classList.remove("hidden");
  });

  function init() { applyTheme(initialTheme()); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();

  window.Thaw = { toast: toast, confirm: confirmDialog, busy: setBusy, run: run, me: me, mountShell: mountShell, setTheme: applyTheme, icon: icon };
})();	