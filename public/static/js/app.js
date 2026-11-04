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

  // ---------- Devis : formats et blocs réutilisables ----------
  const STATUTS = { brouillon: ["Brouillon", "muted2"], envoye: ["Envoyé", "info"], accepte: ["Accepté", "ok"], refuse: ["Refusé", "bad"], expire: ["Expiré", "bad"], remplace: ["Remplacé", "muted2"] };
  const LIGNE_LABELS = { main_oeuvre: "Main-d'œuvre", piece: "Pièce", forfait: "Forfait", consommable: "Consommable", autre: "Autre" };
  const CUR = { XOF: "FCFA", XAF: "FCFA" };
  const DEFAULT_CONDITIONS = "Devis valable pendant la durée indiquée. Les prix pourront être révisés si des travaux supplémentaires s'avèrent nécessaires après démontage.";
  const fmtMoney = (n, dec, devise) => Number(n || 0).toLocaleString("fr-FR", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + " " + (CUR[devise] || devise);
  function setBadge(node, statut) { const [t, c] = STATUTS[statut] || [statut, "muted2"]; node.textContent = t; node.className = "badge " + c; }
  function linesTable(table, d) {
    const dec = d.devise_decimales;
    const head = el("thead", {}, el("tr", {}, el("th", { text: "Désignation" }), el("th", { class: "num", text: "Qté" }), el("th", { class: "num", text: "Prix unitaire" }), el("th", { class: "num", text: "Remise" }), el("th", { class: "num", text: "Total" })));
    const body = el("tbody", {}, d.lignes.map((l) => el("tr", {},
      el("td", {}, el("strong", { text: l.designation }), el("br"), el("span", { class: "muted", text: LIGNE_LABELS[l.type] || "" })),
      el("td", { class: "num", text: String(l.quantite).replace(".", ",") + (l.unite ? " " + l.unite : "") }),
      el("td", { class: "num", text: fmtMoney(l.prix_unitaire, dec, d.devise) }),
      el("td", { class: "num", text: l.remise_pct ? l.remise_pct + " %" : "" }),
      el("td", { class: "num", text: fmtMoney(l.total_ht, dec, d.devise) }))));
    table.replaceChildren(head, body);
  }
  function totalsBlock(box, d) {
    const m = (n) => fmtMoney(n, d.devise_decimales, d.devise);
    const row = (label, value, cls) => el("div", cls ? { class: cls } : {}, el("span", { text: label }), el("span", { text: value }));
    const rows = [];
    if (d.tva_active || d.remise_globale > 0) rows.push(row("Sous-total" + (d.tva_active ? " HT" : ""), m(d.sous_total_ht)));
    if (d.remise_globale > 0) rows.push(row("Remise", "- " + m(d.remise_globale)));
    if (d.tva_active) { rows.push(row("Total HT", m(d.total_ht))); rows.push(row(`TVA (${d.tva_taux} %)`, m(d.total_tva))); }
    rows.push(row(d.tva_active ? "Total TTC" : "Total", m(d.total_ttc), "grand"));
    box.replaceChildren(...rows);
  }
  async function loadDevisInto(params, list, empty) {
    try {
      const out = await api("/api/devis?" + new URLSearchParams({ ...params, par_page: 10 }));
      list.replaceChildren(...out.devis.map((d) => itemLink("/devis/" + d.id, d.numero || "Brouillon",
        [(STATUTS[d.statut_effectif] || [d.statut_effectif])[0], fmtMoney(d.total_ttc, d.devise_decimales, d.devise), fmtDate(d.date_emission || d.cree_le)].join(" · "))));
      empty.hidden = out.devis.length > 0;
    } catch (e) { const section = list.closest("section"); if (section) section.hidden = true; }  // pas le droit de voir les devis
  }

  // ---------- Pages ----------
  async function loadMe() {
    try { return await api("/api/auth/me"); } catch (e) { location.href = "/connexion"; return null; }
  }
  function navLoggedIn(me) {
    const nav = $("#nav"); if (!nav) return;
    nav.innerHTML = "";
    [["Tableau de bord", "/tableau-de-bord"], ["Clients", "/clients"], ["Véhicules", "/vehicules"], ["Devis", "/devis"], ["Profil", "/profil"]].forEach(([t, h]) => { const a = document.createElement("a"); a.href = h; a.textContent = t; nav.appendChild(a); });
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
        $("#btn-devis").href = "/devis/nouveau?client_id=" + id;
        loadDevisInto({ client_id: id }, $("#devis-liste"), $("#devis-vide"));
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
        $("#btn-devis").href = "/devis/nouveau?" + new URLSearchParams(out.proprietaire ? { client_id: out.proprietaire.id, vehicule_id: id } : { vehicule_id: id });
        loadDevisInto({ vehicule_id: id }, $("#devis-liste"), $("#devis-vide"));
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
    async devis() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      pagedList({
        url: "/api/devis", itemKey: "devis",
        extra: () => ({ q: $("#q").value.trim(), statut: $("#statut").value }),
        render: (d) => itemLink("/devis/" + d.id, `${d.numero || "Brouillon"} · ${d.client ? d.client.nom_affiche : ""}`,
          [(STATUTS[d.statut_effectif] || [d.statut_effectif])[0], fmtMoney(d.total_ttc, d.devise_decimales, d.devise), fmtDate(d.date_emission || d.cree_le)].join(" · ")),
      });
    },
    async "devis-editeur"() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const g = me.garage, dec = g.devise_decimales, f = $("#devis-form"), tbody = $("#lignes"), vsel = $("#vehicule-select"), chosen = $("#client-chosen");
      const parts = location.pathname.split("/").filter(Boolean);
      const editingId = parts[2] === "modifier" ? parts[1] : null;
      const rnd = (x) => { const k = 10 ** dec; return Math.round((x + Number.EPSILON) * k) / k; };
      const num = (v) => { const n = parseFloat(String(v).replace(",", ".")); return Number.isFinite(n) ? n : 0; };
      const field = (tr, name) => tr.querySelector(`[name=${name}]`);

      function recalc() {
        let sub = 0;
        tbody.querySelectorAll("tr").forEach((tr) => {
          const t = rnd(num(field(tr, "quantite").value) * num(field(tr, "prix_unitaire").value) * (100 - num(field(tr, "remise_pct").value)) / 100);
          tr.querySelector(".ligne-total").textContent = fmtMoney(t, dec, g.devise); sub += t;
        });
        const remise = Math.min(num(f.elements.remise_globale.value), sub), ht = rnd(sub - remise), tva = g.tva_active ? rnd(ht * g.tva_taux / 100) : 0;
        totalsBlock($("#totaux"), { devise: g.devise, devise_decimales: dec, tva_active: g.tva_active, tva_taux: g.tva_taux, sous_total_ht: sub, remise_globale: remise, total_ht: ht, total_tva: tva, total_ttc: rnd(ht + tva) });
      }
      function addRow(data = {}) {
        const typeSel = el("select", { name: "type" }, Object.entries(LIGNE_LABELS).map(([v, t]) => el("option", { value: v, text: t })));
        typeSel.value = data.type || "main_oeuvre";
        const inp = (name, attrs) => el("input", { name, ...attrs });
        const des = inp("designation", { maxlength: "200", placeholder: "Ex. Vidange moteur" }); des.value = data.designation || "";
        const qte = inp("quantite", { type: "number", min: "0.01", step: "any", inputmode: "decimal" }); qte.value = data.quantite ?? 1;
        const pu = inp("prix_unitaire", { type: "number", min: "0", step: "any", inputmode: "decimal" }); pu.value = data.prix_unitaire ?? "";
        const rem = inp("remise_pct", { type: "number", min: "0", max: "100", step: "any", inputmode: "decimal" }); rem.value = data.remise_pct || "";
        const del = el("button", { type: "button", class: "linklike", "aria-label": "Supprimer la ligne", text: "✕" });
        const tr = el("tr", {}, el("td", {}, typeSel), el("td", { class: "col-des" }, des), el("td", {}, qte), el("td", {}, pu), el("td", {}, rem), el("td", { class: "num ligne-total" }), el("td", {}, del));
        del.addEventListener("click", () => { tr.remove(); recalc(); });
        tr.addEventListener("input", recalc);
        tbody.appendChild(tr); recalc();
        return tr;
      }
      async function loadVehicules(clientId, selected) {
        vsel.replaceChildren(el("option", { value: "", text: "— Aucun —" }));
        try {
          const out = await api("/api/vehicules?" + new URLSearchParams({ client_id: clientId, par_page: 100 }));
          out.vehicules.forEach((v) => vsel.append(el("option", { value: v.id, text: `${v.marque} ${v.modele}${v.immatriculation ? " · " + v.immatriculation : ""}` })));
        } catch (_) { /* liste de véhicules indisponible : le devis reste possible sans véhicule */ }
        if (selected && ![...vsel.options].some((o) => o.value === selected.id))
          vsel.append(el("option", { value: selected.id, text: selected.libelle ? selected.libelle + (selected.immatriculation ? " · " + selected.immatriculation : "") : "Véhicule sélectionné" }));
        vsel.value = selected ? selected.id : "";
      }
      function chooseClient(c, selectedVehicule) {
        f.elements.client_id.value = c.id;
        chosen.textContent = "Client : " + c.nom_affiche + (c.telephone ? " · " + c.telephone : "");
        return loadVehicules(c.id, selectedVehicule);
      }
      document.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => addRow({ type: b.dataset.add }).querySelector("[name=designation]").focus()));
      f.elements.remise_globale.addEventListener("input", recalc);

      const q = $("#picker-q"), res = $("#picker-results");
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
              b.addEventListener("click", () => { chooseClient(c, null); res.replaceChildren(); q.value = ""; });
              return el("li", {}, b);
            }));
          } catch (e) { alertBox(e.message); }
        }, 300);
      });

      if (editingId) {
        $("#editeur-titre").textContent = "Modifier le devis";
        let d;
        try { d = (await api("/api/devis/" + editingId)).devis; } catch (e) { return alertBox(e.status === 404 ? "Devis introuvable." : e.message); }
        if (d.statut !== "brouillon") { location.href = "/devis/" + editingId; return; }
        await chooseClient(d.client, d.vehicule);
        f.elements.remise_globale.value = d.remise_globale || "";
        f.elements.conditions.value = d.conditions || "";
        d.lignes.forEach((l) => addRow(l));
      } else {
        const params = new URLSearchParams(location.search), cid = params.get("client_id"), vid = params.get("vehicule_id");
        f.elements.conditions.value = DEFAULT_CONDITIONS;
        if (cid) {
          try { await chooseClient((await api("/api/clients/" + cid)).client, vid ? { id: vid } : null); } catch (e) { alertBox("Client introuvable."); }
        }
        addRow({ type: "main_oeuvre" });
      }

      f.addEventListener("submit", async (ev) => {
        ev.preventDefault(); clearErrors(f);
        const btn = f.querySelector("[type=submit]"); btn.disabled = true;
        const payload = {
          client_id: f.elements.client_id.value, vehicule_id: vsel.value || null,
          remise_globale: f.elements.remise_globale.value, conditions: f.elements.conditions.value,
          lignes: [...tbody.querySelectorAll("tr")].map((tr) => ({ type: field(tr, "type").value, designation: field(tr, "designation").value, quantite: field(tr, "quantite").value, prix_unitaire: field(tr, "prix_unitaire").value, remise_pct: field(tr, "remise_pct").value })),
        };
        try {
          const out = await api(editingId ? "/api/devis/" + editingId : "/api/devis", { method: editingId ? "PATCH" : "POST", body: payload });
          location.href = "/devis/" + out.devis.id;
        } catch (e) {
          showErrors(f, e.data && e.data.details);
          alertBox((e.data && e.data.details ? Object.values(e.data.details).join(" ") : "") || e.message || "Erreur réseau, réessayez.");
        } finally { btn.disabled = false; }
      });
    },
    async "devis-fiche"() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const id = idFromUrl();
      let linkUrl = "";
      $("#lien-copier").addEventListener("click", () => { navigator.clipboard.writeText(linkUrl).then(() => alertBox("Lien copié.", "success"), () => alertBox("Copie impossible : sélectionnez le lien et copiez-le à la main.")); });
      function showLink(url, d) {
        linkUrl = url;
        $("#lien-box").hidden = false; $("#lien-url").textContent = url;
        const phone = waNumber((d.client && (d.client.whatsapp || d.client.telephone)) || "", me.garage.pays);
        const text = `Bonjour, voici votre devis ${d.numero} du garage ${me.garage.nom_garage} : ${url}`;
        $("#lien-whatsapp").href = `https://wa.me/${phone}?text=${encodeURIComponent(text)}`;
      }
      async function load() {
        let d;
        try { d = (await api("/api/devis/" + id)).devis; } catch (e) { return alertBox(e.status === 404 ? "Devis introuvable." : e.message); }
        const st = d.statut_effectif;
        $("#devis-titre").textContent = d.numero || "Brouillon";
        setBadge($("#devis-badge"), st);
        $("#devis-resume").textContent = [d.date_emission && "Émis le " + fmtDate(d.date_emission), d.date_validite && "valable jusqu'au " + fmtDate(d.date_validite), d.version > 1 && "version " + d.version].filter(Boolean).join(" · ");
        $("#devis-client").replaceChildren(d.client ? el("a", { href: "/clients/" + d.client.id, text: d.client.nom_affiche }) : "—");
        $("#devis-vehicule").replaceChildren(d.vehicule ? el("a", { href: "/vehicules/" + d.vehicule.id, text: d.vehicule.libelle + (d.vehicule.immatriculation ? " · " + d.vehicule.immatriculation : "") }) : "—");
        const acc = $("#devis-acceptation");
        acc.hidden = !(d.accepte_le || d.refuse_le);
        if (d.accepte_le) acc.textContent = `Accepté par ${d.acceptation_nom} le ${fmtDate(d.accepte_le)} (${d.acceptation_mode === "lien" ? "via le lien client" : "enregistré par le garage"}).`;
        if (d.refuse_le) acc.textContent = `Refusé le ${fmtDate(d.refuse_le)}${d.refus_motif ? " : " + d.refus_motif : ""}.`;
        linesTable($("#lignes-table"), d); totalsBlock($("#totaux"), d);
        $("#devis-conditions").textContent = d.conditions || "—";

        const act = $("#actions"); act.replaceChildren();
        const btn = (text, fn, cls = "btn btn-ghost") => {
          const b = el("button", { type: "button", class: cls, text });
          b.addEventListener("click", async () => { b.disabled = true; try { await fn(); } catch (e) { alertBox(e.message); } finally { b.disabled = false; } });
          return b;
        };
        const post = (path, body) => api(`/api/devis/${id}/${path}`, { method: "POST", body });
        const newVersion = btn("Nouvelle version", async () => { const out = await post("new-version"); location.href = `/devis/${out.devis.id}/modifier`; });
        if (d.statut === "brouillon") {
          act.append(
            el("a", { class: "btn", href: `/devis/${id}/modifier`, text: "Modifier" }),
            btn("Envoyer le devis", async () => {
              const j = prompt("Validité du devis, en jours ?", "30"); if (j === null) return;
              await post("send", { validite_jours: Number(j) || undefined });
              alertBox("Devis envoyé : il a maintenant son numéro et ne peut plus être modifié.", "success"); await load();
            }, "btn"),
            btn("Supprimer le brouillon", async () => { if (!confirm("Supprimer ce brouillon ?")) return; await api("/api/devis/" + id, { method: "DELETE" }); location.href = "/devis"; }));
        }
        if (st === "envoye") {
          act.append(
            btn("Lien pour le client", async () => { showLink((await post("public-link")).url, d); }, "btn"),
            btn("Accepté", async () => { const nom = prompt("Nom de la personne qui accepte ce devis :", d.client ? d.client.nom_affiche : ""); if (!nom) return; await post("accept", { nom }); await load(); }),
            btn("Refusé", async () => { const motif = prompt("Motif du refus (facultatif) :", ""); if (motif === null) return; await post("refuse", { motif }); await load(); }),
            newVersion);
        }
        if (st === "refuse" || st === "expire") act.append(newVersion);
        act.append(el("a", { class: "btn btn-ghost", href: `/api/devis/${id}/pdf`, target: "_blank", rel: "noopener noreferrer", text: "Télécharger le PDF" }));
      }
      await load();
    },
    async "devis-public"() {
      const token = idFromUrl();
      let data;
      try { data = await api("/api/public/devis/" + token); } catch (e) {
        $("#garage-nom").textContent = "Lien invalide";
        return alertBox(e.status === 404 ? "Ce lien est invalide ou n'est plus valable. Contactez votre garage." : (e.message || "Erreur réseau, réessayez."));
      }
      const g = data.garage, d = data.devis;
      renderLogo($("#logo"), g);
      $("#garage-nom").textContent = g.nom_garage;
      $("#garage-contact").textContent = [g.telephone, [g.adresse, g.ville].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
      $("#devis-card").hidden = false;
      $("#devis-titre").textContent = "Devis " + d.numero;
      setBadge($("#devis-badge"), d.statut);
      $("#devis-resume").textContent = [d.date_emission && "Émis le " + fmtDate(d.date_emission), d.date_validite && "valable jusqu'au " + fmtDate(d.date_validite)].filter(Boolean).join(" · ");
      $("#devis-pour").textContent = [data.client && "Pour : " + data.client, data.vehicule && "Véhicule : " + data.vehicule].filter(Boolean).join(" — ");
      linesTable($("#lignes-table"), d); totalsBlock($("#totaux"), d);
      $("#devis-conditions").textContent = d.conditions || "—";
      $("#pdf-link").href = `/api/public/devis/${token}/pdf`;
      const card = $("#reponse-card");
      if (d.statut === "envoye") card.hidden = false;
      else if (d.statut === "accepte") alertBox(`Devis accepté par ${d.acceptation_nom} le ${fmtDate(d.accepte_le)}. Merci !`, "success");
      else if (d.statut === "expire") alertBox("Ce devis a expiré. Contactez le garage pour en obtenir une nouvelle version.");
      else if (d.statut === "remplace") alertBox("Ce devis a été remplacé par une nouvelle version. Contactez le garage.");
      else if (d.statut === "refuse") alertBox("Ce devis a été refusé.");
      const answer = async (action, body, badgeStatus) => {
        try {
          const out = await api(`/api/public/devis/${token}/${action}`, { method: "POST", body });
          card.hidden = true; setBadge($("#devis-badge"), badgeStatus); alertBox(out.message, "success");
        } catch (e) { alertBox(e.message || "Erreur réseau, réessayez."); }
      };
      $("#btn-accepter").addEventListener("click", () => {
        const nom = $("#reponse-nom").value.trim();
        $("#reponse-erreur").textContent = nom ? "" : "Indiquez votre nom pour accepter le devis.";
        if (nom) answer("accept", { nom }, "accepte");
      });
      $("#btn-refuser").addEventListener("click", () => {
        const motif = prompt("Motif du refus (facultatif) :", ""); if (motif === null) return;
        answer("refuse", { motif }, "refuse");
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
