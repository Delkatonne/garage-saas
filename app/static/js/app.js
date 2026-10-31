/* Garage SaaS - JS minimal (sans dépendance). Aucun script inline : compatible CSP "script-src 'self'". */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const cookie = (n) => (document.cookie.match(new RegExp("(?:^|; )" + n + "=([^;]*)")) || [])[1];

  // ---------- Appels API (cookies httpOnly + CSRF double-submit + refresh automatique) ----------
  async function raw(path, { method = "GET", body, isForm = false } = {}) {
    const headers = {};
    if (body && !isForm) headers["Content-Type"] = "application/json";
    const csrf = cookie("csrf_access_token");
    if (csrf && method !== "GET") headers["X-CSRF-TOKEN"] = csrf;
    return fetch(path, { method, headers, credentials: "same-origin", body: isForm ? body : body ? JSON.stringify(body) : undefined });
  }
  async function api(path, opts = {}) {
    let res = await raw(path, opts);
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      const r = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-TOKEN": cookie("csrf_refresh_token") || "" } });
      if (r.ok) res = await raw(path, opts);
    }
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw Object.assign(new Error(data.erreur || "Erreur"), { status: res.status, data });
    return data;
  }

  // ---------- Affichage ----------
  function alertBox(msg, type = "error") {
    const box = $("#alert"); if (!box) return;
    box.textContent = msg; box.className = "alert " + type; box.hidden = false;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  const clearErrors = (f) => { $("#alert") && ($("#alert").hidden = true); f.querySelectorAll("[data-error-for]").forEach((e) => (e.textContent = "")); };
  function showErrors(f, details) {
    Object.entries(details || {}).forEach(([k, m]) => { const e = f.querySelector(`[data-error-for="${k}"]`); if (e) e.textContent = m; });
  }
  function renderLogo(el, garage) {
    if (!el) return; el.textContent = "";
    if (garage.logo_url) { const i = document.createElement("img"); i.src = garage.logo_url; i.alt = "Logo " + garage.nom_garage; el.appendChild(i); }
    else el.textContent = garage.initiales;
  }

  // ---------- Brouillons locaux (connexions instables) : jamais les mots de passe ----------
  function draftKey(f) { return f.dataset.draft ? "draft:" + f.dataset.draft : null; }
  function restoreDraft(f) {
    const k = draftKey(f); if (!k) return;
    try {
      const d = JSON.parse(localStorage.getItem(k) || "{}");
      Object.entries(d).forEach(([n, v]) => { const el = f.elements[n]; if (el && el.type !== "password" && el.type !== "file") el.value = v; });
    } catch (_) {}
    f.addEventListener("input", () => {
      const d = {}; [...f.elements].forEach((el) => { if (el.name && el.type !== "password" && el.type !== "file") d[el.name] = el.value; });
      try { localStorage.setItem(k, JSON.stringify(d)); } catch (_) {}
    });
  }

  // ---------- Formulaires pilotés par data-* ----------
  function formPayload(f) {
    const fd = new FormData(f);
    if (f.dataset.withToken !== undefined) fd.set("token", new URLSearchParams(location.search).get("token") || "");
    const hasFile = [...f.elements].some((e) => e.type === "file" && e.files.length);
    const hasFileInput = [...f.elements].some((e) => e.type === "file");
    if (hasFileInput) { if (!hasFile) fd.delete("logo"); return { body: fd, isForm: true }; }
    const obj = {}; fd.forEach((v, k) => (obj[k] = v));
    if (f.dataset.json !== undefined) {
      f.querySelectorAll("input[type=checkbox]").forEach((c) => (obj[c.name] = c.checked));
      f.querySelectorAll("input[type=number]").forEach((n) => { if (n.value !== "") obj[n.name] = Number(n.value); });
      delete obj.email;
    }
    return { body: obj, isForm: false };
  }
  function bindForm(f) {
    restoreDraft(f);
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault(); clearErrors(f);
      const btn = f.querySelector("[type=submit]"); btn.disabled = true;
      try {
        const { body, isForm } = formPayload(f);
        const out = await api(f.dataset.api, { method: f.dataset.method || "POST", body, isForm });
        const k = draftKey(f); if (k) localStorage.removeItem(k);
        if (f.dataset.success === "reload") return location.reload();
        if (out.message) alertBox(out.message, "success");
        if (f.dataset.success === "message") f.reset();
        if (f.dataset.redirect) setTimeout(() => (location.href = f.dataset.redirect), Number(f.dataset.redirectDelay || 0));
        if (out.garage && $("#logo")) renderLogo($("#logo"), out.garage);
      } catch (e) {
        showErrors(f, e.data && e.data.details);
        alertBox(e.status === 429 ? "Trop de tentatives, patientez un instant." : e.message || "Erreur réseau, réessayez.");
      } finally { btn.disabled = false; }
    });
  }

  // ---------- Pages ----------
  async function loadMe() {
    try { return await api("/api/auth/me"); } catch (e) { location.href = "/connexion"; return null; }
  }
  function navLoggedIn(me) {
    const nav = $("#nav"); if (!nav) return;
    nav.innerHTML = "";
    [["Tableau de bord", "/tableau-de-bord"], ["Profil", "/profil"]].forEach(([t, h]) => { const a = document.createElement("a"); a.href = h; a.textContent = t; nav.appendChild(a); });
    const b = document.createElement("a"); b.href = "#"; b.textContent = "Déconnexion";
    b.addEventListener("click", async (e) => { e.preventDefault(); await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); location.href = "/connexion"; });
    nav.appendChild(b);
  }
  const pages = {
    async "tableau-de-bord"() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      $("#garage-nom").textContent = me.garage.nom_garage;
      $("#user-info").textContent = `${me.utilisateur.nom_complet} · ${me.utilisateur.role === "owner" ? "Propriétaire" : me.utilisateur.role}`;
      renderLogo($("#logo"), me.garage);
      if (me.garage.statut_abonnement === "essai" && me.garage.essai_fin)
        $("#essai-info").textContent = "Période d'essai jusqu'au " + new Date(me.garage.essai_fin).toLocaleDateString("fr-FR");
    },
    async profil() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const g = me.garage, f = $("#profile-form");
      renderLogo($("#logo"), g);
      ["nom_garage", "nom_chef_garage", "email", "telephone", "adresse", "ville", "ifu", "rccm", "devise", "devise_decimales", "tva_taux"].forEach((n) => { if (f.elements[n]) f.elements[n].value = g[n] ?? ""; });
      f.elements.tva_active.checked = g.tva_active;
      $("#logo-delete").addEventListener("click", async () => {
        try { renderLogo($("#logo"), (await api("/api/garage/logo", { method: "DELETE" })).garage); alertBox("Logo supprimé.", "success"); }
        catch (e) { alertBox(e.message); }
      });
    },
    async "verifier-email"() {
      const token = new URLSearchParams(location.search).get("token"), s = $("#verify-status");
      try { const out = await api("/api/auth/verify-email", { method: "POST", body: { token } }); s.textContent = out.message; }
      catch (e) { s.textContent = e.message; }
      $("#verify-actions").hidden = false;
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-api]").forEach(bindForm);
    const fn = pages[document.body.dataset.page]; if (fn) fn();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
})();
