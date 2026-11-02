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
      Object.entries(d).forEach(([n, v]) => { const el = f.elements[n]; if (el && el.type !== "password" && el.type !== "file" && el.type !== "hidden") el.value = v; });
    } catch (_) {}
    f.addEventListener("input", () => {
      const d = {}; [...f.elements].forEach((el) => { if (el.name && el.type !== "password" && el.type !== "file" && el.type !== "hidden") d[el.name] = el.value; });
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
    }
    (f.dataset.omit || "").split(",").forEach((k) => { if (k) delete obj[k]; });
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
        if (f.dataset.success === "goto-client" || f.dataset.success === "goto-vehicule") {
          const target = f.dataset.success === "goto-client" ? "/clients/" + out.client.id : "/vehicules/" + out.vehicule.id;
          const warn = (out.avertissements || []).join(" ");
          if (warn) alertBox(warn, "success");
          setTimeout(() => (location.href = target), warn ? 2500 : 0);
          return;
        }
        if (f.dataset.success === "saved") { alertBox("Modifications enregistrées.", "success"); f.dispatchEvent(new CustomEvent("saved", { detail: out })); }
        if (out.message) alertBox(out.message, "success");
        if (f.dataset.success === "message") f.reset();
        if (out.redirect) setTimeout(() => (location.href = out.redirect), 1500);
        if (f.dataset.redirect) setTimeout(() => (location.href = f.dataset.redirect), Number(f.dataset.redirectDelay || 0));
        if (out.garage && $("#logo")) renderLogo($("#logo"), out.garage);
      } catch (e) {
        showErrors(f, e.data && e.data.details);
        alertBox(e.status === 429 ? "Trop de tentatives, patientez un instant." : e.message || "Erreur réseau, réessayez.");
      } finally { btn.disabled = false; }
    });
  }

  // ---------- Outils d'affichage sûrs : textContent uniquement, aucune donnée n'est injectée en HTML ----------
  function el(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => { if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v); });
    kids.flat().forEach((k) => { if (k !== null && k !== undefined && k !== false) e.append(k); });
    return e;
  }
  const idFromUrl = () => location.pathname.split("/").filter(Boolean).pop();
  const LABELS = { particulier: "Particulier", entreprise: "Entreprise", flotte: "Flotte", voiture: "Voiture", moto: "Moto", scooter: "Scooter", quad: "Quad" };
  const PHONE_CODES = { BJ: "229", TG: "228", CI: "225", SN: "221", NE: "227", BF: "226", ML: "223", CM: "237", GN: "224" };
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "");
  const fmtKm = (n) => (n === null || n === undefined ? "" : Number(n).toLocaleString("fr-FR") + " km");
  function fill(f, obj) { [...f.elements].forEach((e) => { if (e.name && e.name in obj && e.type !== "file") e.value = obj[e.name] ?? ""; }); }
  // Numéro WhatsApp international (chiffres seulement) : ajoute l'indicatif du pays du garage si absent.
  function waNumber(raw, pays) {
    let d = String(raw || "").replace(/[^\d+]/g, "");
    if (!d) return "";
    if (d.startsWith("+")) return d.slice(1);
    if (d.startsWith("00")) return d.slice(2);
    const cc = PHONE_CODES[pays] || "";
    return cc && !d.startsWith(cc) ? cc + d : d;
  }
  function bindClientType(f) {
    const sel = f.elements.type, soc = f.querySelector("[data-only=societe]"), nom = f.querySelector("[data-label=nom]");
    const sync = () => { const company = sel.value !== "particulier"; soc.hidden = !company; nom.textContent = company ? "Nom du contact" : "Nom"; };
    sel.addEventListener("change", sync); sync(); return sync;
  }
  // Liste paginée avec recherche (clients, véhicules)
  function pagedList({ url, itemKey, extra, render }) {
    const list = $("#list"), empty = $("#empty"), prev = $("#prev"), next = $("#next"), info = $("#page-info");
    let page = 1, timer;
    async function load() {
      try {
        const out = await api(url + "?" + new URLSearchParams({ page, par_page: 20, ...extra() }));
        list.replaceChildren(...out[itemKey].map(render));
        empty.hidden = out[itemKey].length > 0;
        const pages = Math.max(1, Math.ceil(out.total / out.par_page));
        info.textContent = `Page ${out.page} / ${pages} · ${out.total} résultat${out.total > 1 ? "s" : ""}`;
        prev.disabled = out.page <= 1; next.disabled = out.page >= pages;
      } catch (e) { alertBox(e.message || "Erreur réseau, réessayez."); }
    }
    const reload = () => { page = 1; load(); };
    $("#search-form").addEventListener("submit", (ev) => { ev.preventDefault(); reload(); });
    $("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(reload, 300); });
    document.querySelectorAll("#search-form select").forEach((s) => s.addEventListener("change", reload));
    prev.addEventListener("click", () => { page -= 1; load(); });
    next.addEventListener("click", () => { page += 1; load(); });
    load();
  }
  const itemLink = (href, title, sub) => el("li", {}, el("a", { href }, el("strong", { text: title }), el("span", { class: "muted", text: sub })));

  // ---------- Pages ----------
  async function loadMe() {
    try { return await api("/api/auth/me"); } catch (e) { location.href = "/connexion"; return null; }
  }
  function navLoggedIn(me) {
    const nav = $("#nav"); if (!nav) return;
    nav.innerHTML = "";
    [["Tableau de bord", "/tableau-de-bord"], ["Clients", "/clients"], ["Véhicules", "/vehicules"], ["Profil", "/profil"]].forEach(([t, h]) => { const a = document.createElement("a"); a.href = h; a.textContent = t; nav.appendChild(a); });
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
    async clients() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const card = $("#new-card");
      bindClientType(card.querySelector("form"));
      $("#toggle-new").addEventListener("click", () => { card.hidden = !card.hidden; if (!card.hidden) card.scrollIntoView({ behavior: "smooth" }); });
      pagedList({
        url: "/api/clients", itemKey: "clients",
        extra: () => ({ q: $("#q").value.trim(), statut: $("#statut").value }),
        render: (c) => itemLink("/clients/" + c.id, c.nom_affiche, [LABELS[c.type], c.telephone, c.actif ? "" : "archivé"].filter(Boolean).join(" · ")),
      });
    },
    async client() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const id = idFromUrl(), f = $("#client-form"), vf = $("#vehicule-form");
      f.dataset.api = "/api/clients/" + id;
      vf.elements.client_id.value = id;
      const sync = bindClientType(f);
      async function load() {
        let out;
        try { out = await api("/api/clients/" + id); } catch (e) { return alertBox(e.status === 404 ? "Client introuvable." : e.message); }
        const c = out.client;
        $("#client-nom").textContent = c.nom_affiche;
        $("#client-resume").textContent = [LABELS[c.type], c.telephone, c.email, c.adresse].filter(Boolean).join(" · ");
        const badge = $("#client-badge"); badge.hidden = c.actif; badge.textContent = "Archivé";
        fill(f, c); sync();
        const wa = waNumber(c.whatsapp || c.telephone, me.garage.pays);
        $("#btn-whatsapp").hidden = !wa; if (wa) $("#btn-whatsapp").href = "https://wa.me/" + wa;
        const tel = String(c.telephone || "").replace(/[^\d+]/g, "");
        $("#btn-appeler").hidden = !tel; if (tel) $("#btn-appeler").href = "tel:" + tel;
        $("#btn-archive").hidden = !c.actif; $("#btn-restore").hidden = c.actif;
        $("#vehicules").replaceChildren(...out.vehicules.map((v) => itemLink("/vehicules/" + v.id, `${v.marque} ${v.modele}`, [LABELS[v.type], v.immatriculation, fmtKm(v.kilometrage_actuel), v.actif ? "" : "archivé"].filter(Boolean).join(" · "))));
        $("#vehicules-empty").hidden = out.vehicules.length > 0;
      }
      f.addEventListener("saved", load);
      $("#toggle-vehicule").addEventListener("click", () => { const c = $("#vehicule-card"); c.hidden = !c.hidden; if (!c.hidden) c.scrollIntoView({ behavior: "smooth" }); });
      const setActive = (action, question) => async () => {
        if (question && !confirm(question)) return;
        try { await api(`/api/clients/${id}/${action}`, { method: "POST" }); alertBox(action === "archive" ? "Client archivé." : "Client restauré.", "success"); load(); }
        catch (e) { alertBox(e.message); }
      };
      $("#btn-archive").addEventListener("click", setActive("archive", "Archiver ce client ? Il n'apparaîtra plus dans la liste, mais son historique est conservé."));
      $("#btn-restore").addEventListener("click", setActive("restore"));
      await load();
    },
    async vehicules() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      pagedList({
        url: "/api/vehicules", itemKey: "vehicules",
        extra: () => ({ q: $("#q").value.trim(), statut: $("#statut").value, type: $("#type").value }),
        render: (v) => itemLink("/vehicules/" + v.id, `${v.marque} ${v.modele}`,
          [LABELS[v.type], v.immatriculation, v.proprietaire && v.proprietaire.nom_affiche, v.actif ? "" : "archivé"].filter(Boolean).join(" · ")),
      });
    },
    async vehicule() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const id = idFromUrl(), f = $("#vehicule-form"), tf = $("#transfer-form");
      f.dataset.api = "/api/vehicules/" + id;
      tf.dataset.api = `/api/vehicules/${id}/transfer`;
      async function load() {
        let out;
        try { out = await api("/api/vehicules/" + id); } catch (e) { return alertBox(e.status === 404 ? "Véhicule introuvable." : e.message); }
        const v = out.vehicule;
        $("#vehicule-titre").textContent = `${v.marque} ${v.modele}`;
        $("#vehicule-resume").textContent = [LABELS[v.type], v.immatriculation, v.vin && "VIN " + v.vin, v.annee, fmtKm(v.kilometrage_actuel)].filter(Boolean).join(" · ");
        const badge = $("#vehicule-badge"); badge.hidden = v.actif; badge.textContent = "Archivé";
        const owner = $("#proprietaire"); owner.replaceChildren();
        if (out.proprietaire) owner.append(el("a", { href: "/clients/" + out.proprietaire.id, text: out.proprietaire.nom_affiche })); else owner.textContent = "Aucun";
        $("#historique").replaceChildren(...out.historique_proprietaires.map((h) =>
          el("li", {}, el("a", { href: "/clients/" + h.client_id, text: h.nom_affiche }),
            el("span", { class: "muted", text: ` — du ${fmtDate(h.date_debut)}${h.date_fin ? " au " + fmtDate(h.date_fin) : " (actuel)"}` }))));
        fill(f, v); f.elements.corriger_kilometrage.checked = false;
        $("#btn-archive").hidden = !v.actif; $("#btn-restore").hidden = v.actif;
      }
      f.addEventListener("saved", load);
      const setActive = (action, question) => async () => {
        if (question && !confirm(question)) return;
        try { await api(`/api/vehicules/${id}/${action}`, { method: "POST" }); alertBox(action === "archive" ? "Véhicule archivé." : "Véhicule restauré.", "success"); load(); }
        catch (e) { alertBox(e.message); }
      };
      $("#btn-archive").addEventListener("click", setActive("archive", "Archiver ce véhicule ? Son historique est conservé."));
      $("#btn-restore").addEventListener("click", setActive("restore"));
      // Recherche du nouveau propriétaire
      const q = $("#picker-q"), res = $("#picker-results"), chosen = $("#picker-chosen"), btn = $("#transfer-btn");
      let timer;
      q.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          const term = q.value.trim();
          if (term.length < 2) { res.replaceChildren(); return; }
          try {
            const out = await api("/api/clients?" + new URLSearchParams({ q: term, par_page: 6 }));
            res.replaceChildren(...out.clients.map((c) => {
              const b = el("button", { type: "button", class: "linklike", text: c.nom_affiche + (c.telephone ? " · " + c.telephone : "") });
              b.addEventListener("click", () => {
                tf.elements.client_id.value = c.id; chosen.textContent = "Nouveau propriétaire : " + c.nom_affiche;
                chosen.hidden = false; btn.disabled = false; res.replaceChildren();
              });
              return el("li", {}, b);
            }));
          } catch (e) { alertBox(e.message); }
        }, 300);
      });
      await load();
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
