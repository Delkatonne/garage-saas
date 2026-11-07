/* Garage SaaS - JS minimal (sans dépendance). Aucun script inline : compatible CSP "script-src 'self'". */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const cookie = (n) => (document.cookie.match(new RegExp("(?:^|; )" + n + "=([^;]*)")) || [])[1];

  // ---------- Appels API (cookies httpOnly + CSRF double-submit + refresh automatique) ----------
  async function raw(path, { method = "GET", body, isForm = false, headers: extraHeaders = {} } = {}) {
    const headers = { ...extraHeaders };
    if (body && !isForm) headers["Content-Type"] = "application/json";
    const csrf = cookie("csrf_access_token");
    if (csrf && method !== "GET") headers["X-CSRF-TOKEN"] = csrf;
    return fetch(path, { method, headers, credentials: "same-origin", body: isForm ? body : body ? JSON.stringify(body) : undefined });
  }
  // Le jeton d'accès dure 15 min : à son expiration, UN SEUL rafraîchissement est lancé même si plusieurs appels échouent
  // en même temps (le jeton de rafraîchissement est à usage unique). Valable aussi pour /api/auth/me.
  const NO_REFRESH = ["/api/auth/login", "/api/auth/register", "/api/auth/refresh", "/api/auth/logout", "/api/auth/forgot-password",
    "/api/auth/reset-password", "/api/auth/verify-email", "/api/auth/resend-verification", "/api/public/"];
  let refreshing = null;
  function refreshSession() {
    if (!refreshing) {
      refreshing = fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-TOKEN": cookie("csrf_refresh_token") || "" } })
        .then((r) => r.ok).catch(() => false).finally(() => { setTimeout(() => { refreshing = null; }, 0); });
    }
    return refreshing;
  }
  async function api(path, opts = {}) {
    let res = await raw(path, opts);
    if (res.status === 401 && !NO_REFRESH.some((p) => path.startsWith(p))) {
      if (await refreshSession()) res = await raw(path, opts);
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
    document.querySelectorAll("#search-form select, #search-form input[type=checkbox]").forEach((s) => s.addEventListener("change", reload));
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

  // ---------- Ordres de réparation : libellés et listes ----------
  const OR_STATUTS = { en_attente: ["En attente", "muted2"], diagnostic: ["Diagnostic", "info"], devis_envoye: ["Devis envoyé", "info"], devis_accepte: ["Devis accepté", "ok"],
    en_cours: ["Travaux en cours", "info"], attente_pieces: ["Attente de pièces", "muted2"], termine: ["Terminé", "ok"], facture: ["Facturé", "ok"], livre: ["Livré", "ok"], annule: ["Annulé", "bad"] };
  const OR_ACTIONS = { diagnostic: "Diagnostic en cours", devis_envoye: "Devis envoyé au client", devis_accepte: "Devis accepté", en_cours: "Travaux en cours",
    attente_pieces: "En attente de pièces", termine: "Travaux terminés", livre: "Véhicule livré", annule: "Annuler l'ordre" };
  const orLabel = (st) => (OR_STATUTS[st] || [st])[0];
  const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
  async function loadOrInto(params, list, empty) {
    try {
      const out = await api("/api/or?" + new URLSearchParams({ ...params, statut: "tous", par_page: 10 }));
      list.replaceChildren(...out.ordres.map((o) => itemLink("/or/" + o.id, `${o.numero} · ${o.vehicule ? o.vehicule.libelle : ""}`,
        [orLabel(o.statut), o.vehicule && o.vehicule.immatriculation, fmtDate(o.date_entree)].filter(Boolean).join(" · "))));
      empty.hidden = out.ordres.length > 0;
    } catch (e) { const section = list.closest("section"); if (section) section.hidden = true; }
  }

  const DEFAULT_CONDITIONS_FACTURE = "Paiement à réception de la facture. Toute somme non réglée à l'échéance peut donner lieu à des pénalités de retard.";
  const DEVIS_KIND = { api: "/api/devis", base: "/devis", key: "devis", notFound: "Devis introuvable.", editTitle: "Modifier le devis", defaultConditions: DEFAULT_CONDITIONS };
  const FACTURE_KIND = { api: "/api/factures", base: "/factures", key: "facture", notFound: "Facture introuvable.", editTitle: "Modifier la facture", defaultConditions: DEFAULT_CONDITIONS_FACTURE };
  // Éditeur de lignes (client, véhicule, travaux, remise, conditions) commun aux devis et aux factures
  function editorPage(kind) {
    return async function () {
        const me = await loadMe(); if (!me) return; navLoggedIn(me);
        const g = me.garage, dec = g.devise_decimales, f = $("#devis-form"), tbody = $("#lignes"), vsel = $("#vehicule-select"), chosen = $("#client-chosen");
        const parts = location.pathname.split("/").filter(Boolean);
        const editingId = parts[2] === "modifier" ? parts[1] : null;
        let orId = null;
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
          $("#editeur-titre").textContent = kind.editTitle;
          let d;
          try { d = (await api(kind.api + "/" + editingId))[kind.key]; } catch (e) { return alertBox(e.status === 404 ? kind.notFound : e.message); }
          if (d.statut !== "brouillon") { location.href = kind.base + "/" + editingId; return; }
          await chooseClient(d.client, d.vehicule);
          f.elements.remise_globale.value = d.remise_globale || "";
          f.elements.conditions.value = d.conditions || "";
          d.lignes.forEach((l) => addRow(l));
        } else {
          const params = new URLSearchParams(location.search), cid = params.get("client_id"), vid = params.get("vehicule_id");
          orId = params.get("or_id");
          f.elements.conditions.value = kind.defaultConditions;
          if (cid) {
            try { await chooseClient((await api("/api/clients/" + cid)).client, vid ? { id: vid } : null); } catch (e) { alertBox("Client introuvable."); }
          }
          addRow({ type: "main_oeuvre" });
        }

        f.addEventListener("submit", async (ev) => {
          ev.preventDefault(); clearErrors(f);
          const btn = f.querySelector("[type=submit]"); btn.disabled = true;
          const payload = {
            client_id: f.elements.client_id.value, vehicule_id: vsel.value || null, or_id: editingId ? undefined : orId,
            remise_globale: f.elements.remise_globale.value, conditions: f.elements.conditions.value,
            lignes: [...tbody.querySelectorAll("tr")].map((tr) => ({ type: field(tr, "type").value, designation: field(tr, "designation").value, quantite: field(tr, "quantite").value, prix_unitaire: field(tr, "prix_unitaire").value, remise_pct: field(tr, "remise_pct").value })),
          };
          try {
            const out = await api(editingId ? kind.api + "/" + editingId : kind.api, { method: editingId ? "PATCH" : "POST", body: payload });
            location.href = kind.base + "/" + out[kind.key].id;
          } catch (e) {
            showErrors(f, e.data && e.data.details);
            alertBox((e.data && e.data.details ? Object.values(e.data.details).join(" ") : "") || e.message || "Erreur réseau, réessayez.");
          } finally { btn.disabled = false; }
        });
    };
  }

  // ---------- Factures et paiements : libellés et outils ----------
  const FSTAT = { brouillon: ["Brouillon", "muted2"], impayee: ["Impayée", "bad"], partielle: ["Partielle", "info"], payee: ["Payée", "ok"], en_retard: ["En retard", "bad"], annulee: ["Annulée", "muted2"] };
  const fstat = (st) => (FSTAT[st] || [st, "muted2"]);
  async function loadFacturesInto(params, list, empty) {
    try {
      const out = await api("/api/factures?" + new URLSearchParams({ ...params, statut: "tous", par_page: 10 }));
      list.replaceChildren(...out.factures.map((f) => itemLink("/factures/" + f.id, f.numero || "Brouillon",
        [fstat(f.statut_paiement)[0], fmtMoney(f.total_ttc, f.devise_decimales, f.devise), fmtDate(f.emise_le || f.cree_le)].join(" · "))));
      empty.hidden = out.factures.length > 0;
    } catch (e) { const section = list.closest("section"); if (section) section.hidden = true; }
  }
  // Formulaire d'encaissement (facture ou acompte). La clé d'idempotence est conservée tant que le paiement n'a pas abouti :
  // si la réponse se perd (réseau instable) et qu'on réessaie, le serveur ne l'enregistre pas deux fois.
  function bindPaymentForm(form, target, done) {
    let key = null;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault(); clearErrors(form);
      const btn = form.querySelector("[type=submit]"); btn.disabled = true;
      key = key || (window.crypto && crypto.randomUUID ? crypto.randomUUID() : "k" + Date.now() + Math.random().toString(16).slice(2));
      const payload = { ...target(), montant: form.elements.montant.value, moyen: form.elements.moyen.value,
        reference_transaction: form.elements.reference_transaction.value, date_paiement: form.elements.date_paiement.value };
      try {
        const out = await api("/api/paiements", { method: "POST", body: payload, headers: { "Idempotency-Key": key } });
        key = null; form.reset(); form.hidden = true;
        alertBox((out.rejoue ? "Ce paiement était déjà enregistré. " : "Paiement enregistré. ") + (out.paiement.recu ? "Reçu " + out.paiement.recu.numero + "." : ""), "success");
        await done(out);
      } catch (e) {
        showErrors(form, e.data && e.data.details);
        alertBox((e.data && e.data.details ? Object.values(e.data.details).join(" ") : "") || e.message || "Erreur réseau, réessayez : le paiement ne sera pas enregistré deux fois.");
      } finally { btn.disabled = false; }
    });
  }

  // ---------- Pages ----------
  async function loadMe() {
    try { return await api("/api/auth/me"); } catch (e) {
      if (e.status === 401 || e.status === 403) { location.href = "/connexion"; return null; }  // vraiment déconnecté
      alertBox("Connexion impossible pour le moment. Vérifiez votre réseau, puis rechargez la page.");  // réseau instable : on reste connecté
      return null;
    }
  }
  const NAV_ITEMS = [["Tableau de bord", "/tableau-de-bord", null], ["Clients", "/clients", ["owner", "receptionniste", "comptable"]],
    ["Véhicules", "/vehicules", ["owner", "receptionniste", "mecanicien", "comptable"]], ["Réparations", "/or", ["owner", "receptionniste", "mecanicien", "comptable"]],
    ["Devis", "/devis", ["owner", "receptionniste", "comptable"]], ["Factures", "/factures", ["owner", "receptionniste", "comptable"]], ["Profil", "/profil", null]];
  const navItems = (me) => NAV_ITEMS.filter(([, , roles]) => !roles || roles.includes((me.utilisateur && me.utilisateur.role) || "owner"));
  const syncMenu = () => { const b = $("#menu-toggle"), n = $("#nav"); if (b && n) b.hidden = !n.children.length; };
  function initMenu() {
    const bar = $(".topbar"), btn = $("#menu-toggle"), nav = $("#nav"); if (!bar || !btn || !nav) return;
    const set = (open) => { bar.classList.toggle("open", open); btn.setAttribute("aria-expanded", String(open)); };
    btn.addEventListener("click", (e) => { e.stopPropagation(); set(!bar.classList.contains("open")); });
    nav.addEventListener("click", (e) => { if (e.target.closest("a")) set(false); });
    document.addEventListener("click", (e) => { if (!bar.contains(e.target)) set(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") set(false); });
  }
  function navLoggedIn(me) {
    const nav = $("#nav"); if (!nav) return;
    nav.innerHTML = "";
    navItems(me).forEach(([t, h]) => {
      const a = document.createElement("a"); a.href = h; a.textContent = t;
      if (location.pathname === h || (h !== "/tableau-de-bord" && location.pathname.startsWith(h + "/"))) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
    const b = document.createElement("a"); b.href = "#"; b.textContent = "Déconnexion";
    b.addEventListener("click", async (e) => { e.preventDefault(); await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); location.href = "/connexion"; });
    nav.appendChild(b);
    syncMenu();
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
        $("#btn-or").href = "/or/nouveau?client_id=" + id;
        loadDevisInto({ client_id: id }, $("#devis-liste"), $("#devis-vide"));
        loadOrInto({ client_id: id }, $("#or-liste"), $("#or-vide"));
        loadFacturesInto({ client_id: id }, $("#factures-liste"), $("#factures-vide"));
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
        $("#btn-or").href = "/or/nouveau?vehicule_id=" + id;
        loadDevisInto({ vehicule_id: id }, $("#devis-liste"), $("#devis-vide"));
        loadOrInto({ vehicule_id: id }, $("#or-liste"), $("#or-vide"));
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
    "devis-editeur": editorPage(DEVIS_KIND),
    "facture-editeur": editorPage(FACTURE_KIND),
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
        $("#devis-or").replaceChildren(d.ordre ? el("a", { href: "/or/" + d.ordre.id, text: d.ordre.numero }) : "—");
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
        if (st === "accepte" && ["owner", "receptionniste", "comptable"].includes(me.utilisateur.role)) {
          act.append(btn("Créer la facture", async () => {
            try { location.href = "/factures/" + (await api("/api/factures", { method: "POST", body: { devis_id: id } })).facture.id; }
            catch (e) { if (e.data && e.data.details && e.data.details.facture_id) location.href = "/factures/" + e.data.details.facture_id; else throw e; }
          }, "btn"));
        }
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
    async or() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      if (!["owner", "receptionniste"].includes(me.utilisateur.role)) $("#btn-nouveau").hidden = true;
      pagedList({
        url: "/api/or", itemKey: "ordres",
        extra: () => { const p = { q: $("#q").value.trim(), statut: $("#statut").value }; if ($("#mes").checked) p.mecanicien_id = "moi"; return p; },
        render: (o) => itemLink("/or/" + o.id, `${o.numero} · ${o.vehicule ? o.vehicule.libelle : ""}`,
          [orLabel(o.statut), o.vehicule && o.vehicule.immatriculation, o.client && o.client.nom_affiche, o.urgent && "URGENT"].filter(Boolean).join(" · ")),
      });
    },
    async "or-nouveau"() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const f = $("#or-form"), chosen = $("#vehicule-chosen"), submit = $("#or-submit"), msel = f.elements.mecanicien_id;
      try { (await api("/api/or/mecaniciens")).mecaniciens.forEach((m) => msel.append(el("option", { value: m.id, text: m.nom }))); } catch (_) { /* liste indisponible */ }
      const label = (v) => `${v.marque} ${v.modele}${v.immatriculation ? " · " + v.immatriculation : ""}`;
      function chooseVehicule(v) {
        f.elements.vehicule_id.value = v.id;
        chosen.textContent = `${label(v)} — ` + (v.proprietaire ? "propriétaire : " + v.proprietaire.nom_affiche : "aucun propriétaire. Rattachez d'abord ce véhicule à un client (fiche du véhicule).");
        submit.disabled = !v.proprietaire;
        if (v.kilometrage_actuel !== null && v.kilometrage_actuel !== undefined && !f.elements.kilometrage_entree.value) f.elements.kilometrage_entree.value = v.kilometrage_actuel;
      }
      const params = new URLSearchParams(location.search), cid = params.get("client_id"), vid = params.get("vehicule_id");
      if (cid) {
        try {
          const out = await api("/api/vehicules?" + new URLSearchParams({ client_id: cid, par_page: 100 }));
          const sel = $("#client-vehicules"); $("#client-vehicules-label").hidden = false;
          out.vehicules.forEach((v) => sel.append(el("option", { value: v.id, text: label(v) })));
          sel.addEventListener("change", () => { const v = out.vehicules.find((x) => x.id === sel.value); if (v) chooseVehicule(v); });
        } catch (_) { /* on peut toujours chercher un véhicule */ }
      }
      if (vid) { try { chooseVehicule((await api("/api/vehicules/" + vid)).vehicule); } catch (_) { alertBox("Véhicule introuvable."); } }
      const q = $("#picker-q"), res = $("#picker-results");
      let timer;
      q.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          const term = q.value.trim();
          if (term.length < 2) { res.replaceChildren(); return; }
          try {
            const out = await api("/api/vehicules?" + new URLSearchParams({ q: term, par_page: 6 }));
            res.replaceChildren(...out.vehicules.map((v) => {
              const b = el("button", { type: "button", class: "linklike", text: label(v) + (v.proprietaire ? " · " + v.proprietaire.nom_affiche : "") });
              b.addEventListener("click", () => { chooseVehicule(v); res.replaceChildren(); q.value = ""; });
              return el("li", {}, b);
            }));
          } catch (e) { alertBox(e.message); }
        }, 300);
      });
      f.addEventListener("submit", async (ev) => {
        ev.preventDefault(); clearErrors(f); submit.disabled = true;
        const payload = { vehicule_id: f.elements.vehicule_id.value, motif: f.elements.motif.value, symptomes: f.elements.symptomes.value,
          kilometrage_entree: f.elements.kilometrage_entree.value, niveau_carburant: f.elements.niveau_carburant.value, etat_arrivee: f.elements.etat_arrivee.value,
          date_sortie_prevue: f.elements.date_sortie_prevue.value, mecanicien_id: msel.value || null, urgent: f.elements.urgent.checked };
        try {
          const out = await api("/api/or", { method: "POST", body: payload });
          const warn = (out.avertissements || []).join(" ");
          if (warn) alertBox(warn, "success");
          setTimeout(() => (location.href = "/or/" + out.ordre.id), warn ? 2500 : 0);
        } catch (e) {
          submit.disabled = false;
          showErrors(f, e.data && e.data.details);
          alertBox((e.data && e.data.details ? Object.values(e.data.details).join(" ") : "") || e.message || "Erreur réseau, réessayez.");
        }
      });
    },
    async "or-fiche"() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const id = idFromUrl(), f = $("#or-form"), role = me.utilisateur.role;
      const canEdit = ["owner", "receptionniste"].includes(role), notesOnly = new Set(["diagnostic", "travaux_effectues"]);
      try { (await api("/api/or/mecaniciens")).mecaniciens.forEach((m) => f.elements.mecanicien_id.append(el("option", { value: m.id, text: m.nom }))); } catch (_) { /* liste indisponible */ }
      const btn = (text, fn, cls = "btn btn-ghost") => {
        const b = el("button", { type: "button", class: cls, text });
        b.addEventListener("click", async () => { b.disabled = true; try { await fn(); } catch (e) { alertBox(e.message); } finally { b.disabled = false; } });
        return b;
      };
      const post = (path, body) => api(`/api/or/${id}/${path}`, { method: "POST", body });
      const canPay = ["owner", "receptionniste", "comptable"].includes(role);
      async function loadFinance(o) {
        try {
          const fac = await api("/api/factures?" + new URLSearchParams({ or_id: id, statut: "tous", par_page: 20 }));
          $("#factures-liste").replaceChildren(...fac.factures.map((f) => itemLink("/factures/" + f.id, f.numero || "Brouillon",
            [fstat(f.statut_paiement)[0], fmtMoney(f.total_ttc, f.devise_decimales, f.devise)].join(" · "))));
          $("#factures-vide").hidden = fac.factures.length > 0;
          $("#btn-facturer").hidden = o.statut === "annule" || fac.factures.some((f) => f.statut !== "annulee");
          const pay = await api("/api/paiements?" + new URLSearchParams({ or_id: id, par_page: 50 }));
          const open = pay.paiements.filter((p) => !p.facture_id);
          $("#acomptes-liste").replaceChildren(...open.map((p) => el("li", {}, el("span", { text: `${fmtDate(p.date_paiement)} · ${p.moyen_label} · ${fmtMoney(p.montant, fac.factures[0] ? fac.factures[0].devise_decimales : 0, p.devise)} ` }),
            el("a", { href: `/api/paiements/${p.id}/recu`, target: "_blank", rel: "noopener noreferrer", text: p.recu ? "Reçu " + p.recu.numero : "Reçu" }))));
          $("#acomptes-vide").hidden = open.length > 0;
        } catch (e) { $("#finance-card").hidden = true; }
      }
      if (canPay) {
        $("#btn-acompte").addEventListener("click", () => { const form = $("#acompte-form"); form.hidden = !form.hidden; });
        bindPaymentForm($("#acompte-form"), () => ({ or_id: id }), () => load());
        $("#btn-facturer").addEventListener("click", async () => {
          try { location.href = "/factures/" + (await api("/api/factures", { method: "POST", body: { or_id: id } })).facture.id; }
          catch (e) { if (e.data && e.data.details && e.data.details.facture_id) location.href = "/factures/" + e.data.details.facture_id; else alertBox((e.data && e.data.details ? Object.values(e.data.details).join(" ") : "") || e.message); }
        });
      }
      async function load() {
        let out;
        try { out = await api("/api/or/" + id); } catch (e) { return alertBox(e.status === 404 ? "Ordre de réparation introuvable." : e.message); }
        const o = out.ordre, closed = o.statut === "livre" || o.statut === "annule";
        $("#or-titre").textContent = o.numero;
        const badgeNode = $("#or-badge"), [t, c] = OR_STATUTS[o.statut] || [o.statut, "muted2"]; badgeNode.textContent = t; badgeNode.className = "badge " + c;
        $("#or-urgent").hidden = !o.urgent;
        $("#or-resume").textContent = [o.date_entree && "Entré le " + fmtDate(o.date_entree), o.date_sortie_prevue && "sortie prévue le " + fmtDate(o.date_sortie_prevue), o.date_livraison && "livré le " + fmtDate(o.date_livraison)].filter(Boolean).join(" · ");
        $("#or-vehicule").replaceChildren(o.vehicule ? el("a", { href: "/vehicules/" + o.vehicule.id, text: o.vehicule.libelle + (o.vehicule.immatriculation ? " · " + o.vehicule.immatriculation : "") }) : "—");
        $("#or-client").replaceChildren(o.client ? (["owner", "receptionniste", "comptable"].includes(role) ? el("a", { href: "/clients/" + o.client.id, text: o.client.nom_affiche }) : o.client.nom_affiche) : "—");
        $("#or-mecano").textContent = o.mecanicien ? o.mecanicien.nom : "Non affecté";
        $("#or-motif").textContent = o.motif;
        $("#or-autorisation").textContent = o.autorisation ? `Travaux autorisés par ${o.autorisation.nom} le ${fmtDate(o.autorisation.date)}.` : "Aucune autorisation de travaux enregistrée.";

        const act = $("#actions"), other = $("#actions-autres"); act.replaceChildren(); other.replaceChildren();
        out.transitions_possibles.filter((st) => st !== "annule").forEach((st, i) => act.append(btn(OR_ACTIONS[st] || st, async () => {
          const res = await post("status", { statut: st });
          if ((res.avertissements || []).length) alertBox(res.avertissements.join(" "), "success");
          await load();
        }, i === 0 ? "btn" : "btn btn-ghost")));
        if (!out.transitions_possibles.length) act.append(el("span", { class: "muted", text: "Cet ordre est clos." }));
        if (canEdit && !closed && !o.autorisation) other.append(btn("Enregistrer l'autorisation de travaux", async () => {
          const nom = prompt("Nom de la personne qui autorise les travaux :", o.client ? o.client.nom_affiche : ""); if (!nom) return;
          await post("authorize", { nom }); await load();
        }));
        if (out.transitions_possibles.includes("annule")) other.append(btn("Annuler l'ordre", async () => {
          const note = prompt("Motif de l'annulation :"); if (!note) return;
          await post("status", { statut: "annule", note }); await load();
        }));
        other.append(el("a", { class: "btn btn-ghost", href: `/api/or/${id}/pdf`, target: "_blank", rel: "noopener noreferrer", text: "Imprimer l'ordre (PDF)" }));

        $("#devis-card").hidden = role === "mecanicien";
        $("#btn-devis").hidden = !canEdit || closed;
        $("#btn-devis").href = "/devis/nouveau?" + new URLSearchParams({ client_id: o.client_id, vehicule_id: o.vehicule_id, or_id: id });
        $("#devis-liste").replaceChildren(...out.devis.map((d) => itemLink("/devis/" + d.id, d.numero || "Brouillon",
          [(STATUTS[d.statut_effectif] || [d.statut_effectif])[0], fmtMoney(d.total_ttc, d.devise_decimales, d.devise)].join(" · "))));
        $("#devis-vide").hidden = out.devis.length > 0;
        $("#finance-card").hidden = !canPay;
        if (canPay) await loadFinance(o);
        $("#historique").replaceChildren(...out.historique.map((h) => el("li", {}, el("span", { class: "muted", text:
          `${fmtDateTime(h.date)} — ` + (h.ancien_statut === h.nouveau_statut ? (h.commentaire || "") : `${h.ancien_statut ? orLabel(h.ancien_statut) + " → " : ""}${orLabel(h.nouveau_statut)}${h.commentaire ? " : " + h.commentaire : ""}`) + (h.par ? ` (${h.par})` : "") }))));

        const values = { motif: o.motif, symptomes: o.symptomes, diagnostic: o.diagnostic, travaux_effectues: o.travaux_effectues, etat_arrivee: o.etat_arrivee,
          kilometrage_entree: o.kilometrage_entree, niveau_carburant: o.niveau_carburant, date_sortie_prevue: o.date_sortie_prevue ? o.date_sortie_prevue.slice(0, 10) : "", mecanicien_id: o.mecanicien_id };
        [...f.elements].forEach((e) => {
          if (!e.name) return;
          if (e.name === "urgent") e.checked = o.urgent; else if (e.name in values) e.value = values[e.name] === null || values[e.name] === undefined ? "" : String(values[e.name]);
          e.disabled = closed || (!canEdit && !notesOnly.has(e.name));
        });
        $("#or-save").hidden = closed;
      }
      f.addEventListener("submit", async (ev) => {
        ev.preventDefault(); clearErrors(f);
        const payload = {};
        [...f.elements].forEach((e) => { if (e.name && !e.disabled) payload[e.name] = e.type === "checkbox" ? e.checked : e.value; });
        try { await api("/api/or/" + id, { method: "PATCH", body: payload }); alertBox("Modifications enregistrées.", "success"); await load(); }
        catch (e) { showErrors(f, e.data && e.data.details); alertBox((e.data && e.data.details ? Object.values(e.data.details).join(" ") : "") || e.message || "Erreur réseau, réessayez."); }
      });
      await load();
    },
    async factures() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      try {
        const c = await api("/api/paiements/caisse");
        const parts = Object.entries(c.par_moyen).map(([m, t]) => `${({ especes: "Espèces", momo_mtn: "MTN MoMo", momo_moov: "Moov Money", momo_celtiis: "Celtiis Cash", virement: "Virement", carte: "Carte", cheque: "Chèque", autre: "Autre" })[m] || m} ${fmtMoney(t, c.devise_decimales, c.devise)}`);
        $("#caisse").textContent = `Encaissé aujourd'hui : ${fmtMoney(c.total, c.devise_decimales, c.devise)} (${c.nombre} paiement${c.nombre > 1 ? "s" : ""})` + (parts.length ? " — " + parts.join(", ") : "");
      } catch (_) { $("#caisse").hidden = true; }
      pagedList({
        url: "/api/factures", itemKey: "factures",
        extra: () => ({ q: $("#q").value.trim(), statut: $("#statut").value }),
        render: (f) => itemLink("/factures/" + f.id, `${f.numero || "Brouillon"} · ${f.client ? f.client.nom_affiche : ""}`,
          [fstat(f.statut_paiement)[0], fmtMoney(f.total_ttc, f.devise_decimales, f.devise), f.statut === "emise" && f.reste_a_payer > 0 ? "reste " + fmtMoney(f.reste_a_payer, f.devise_decimales, f.devise) : "", fmtDate(f.emise_le || f.cree_le)].filter(Boolean).join(" · ")),
      });
    },
    async "facture-fiche"() {
      const me = await loadMe(); if (!me) return; navLoggedIn(me);
      const id = idFromUrl(), role = me.utilisateur.role, form = $("#paiement-form");
      const canPay = ["owner", "receptionniste", "comptable"].includes(role), canCancel = ["owner", "comptable"].includes(role);
      let reste = 0;
      bindPaymentForm(form, () => ({ facture_id: id }), () => load());
      const btn = (text, fn, cls = "btn btn-ghost") => {
        const b = el("button", { type: "button", class: cls, text });
        b.addEventListener("click", async () => { b.disabled = true; try { await fn(); } catch (e) { alertBox(e.message); } finally { b.disabled = false; } });
        return b;
      };
      async function load() {
        let out;
        try { out = await api("/api/factures/" + id); } catch (e) { return alertBox(e.status === 404 ? "Facture introuvable." : e.message); }
        const f = out.facture, dec = f.devise_decimales, money = (n) => fmtMoney(n, dec, f.devise);
        $("#fac-titre").textContent = f.numero || "Brouillon";
        const [t, c] = fstat(f.statut_paiement); $("#fac-badge").textContent = t; $("#fac-badge").className = "badge " + c;
        $("#fac-resume").textContent = [f.emise_le && "Émise le " + fmtDate(f.emise_le), f.echeance && f.statut === "emise" && "échéance le " + fmtDate(f.echeance), f.empreinte && "empreinte " + f.empreinte].filter(Boolean).join(" · ");
        $("#fac-client").replaceChildren(f.client ? el("a", { href: "/clients/" + f.client.id, text: f.client.nom_affiche }) : "—");
        $("#fac-vehicule").replaceChildren(f.vehicule ? el("a", { href: "/vehicules/" + f.vehicule.id, text: f.vehicule.libelle + (f.vehicule.immatriculation ? " · " + f.vehicule.immatriculation : "") }) : "—");
        $("#fac-or").replaceChildren(f.ordre ? el("a", { href: "/or/" + f.ordre.id, text: f.ordre.numero }) : "—");
        $("#fac-devis").replaceChildren(f.devis ? el("a", { href: "/devis/" + f.devis.id, text: f.devis.numero || "Devis" }) : "—");
        const av = $("#fac-avoir"); av.hidden = !out.avoir;
        if (out.avoir) av.textContent = `Facture annulée par l'avoir ${out.avoir.numero} du ${fmtDate(out.avoir.date)} (${out.avoir.motif}).`;
        linesTable($("#lignes-table"), f); totalsBlock($("#totaux"), f);
        $("#fac-conditions").textContent = f.conditions || "—";
        reste = f.reste_a_payer || 0;
        $("#paiements-card").hidden = f.statut === "brouillon";
        $("#fac-solde").textContent = f.statut === "emise" ? `Payé ${money(f.total_paye)} · reste ${money(reste)}` : "";
        $("#paiements-liste").replaceChildren(...out.paiements.map((p) => el("li", {},
          el("span", { class: p.statut === "annule" ? "muted strike" : "", text: `${fmtDate(p.date_paiement)} · ${p.moyen_label} · ${money(p.montant)}${p.reference ? " · réf. " + p.reference : ""}${p.statut === "annule" ? " · ANNULÉ" : ""} ` }),
          el("a", { href: `/api/paiements/${p.id}/recu`, target: "_blank", rel: "noopener noreferrer", text: p.recu ? "Reçu " + p.recu.numero : "Reçu" }),
          canCancel && p.statut === "valide" ? el("span", {}, " · ", btn("Annuler ce paiement", async () => {
            const motif = prompt("Motif de l'annulation du paiement :"); if (!motif) return;
            await api(`/api/paiements/${p.id}/cancel`, { method: "POST", body: { motif } }); await load();
          }, "linklike")) : "")));
        $("#paiements-vide").hidden = out.paiements.length > 0;

        const act = $("#actions"); act.replaceChildren();
        const post = (path, body) => api(`/api/factures/${id}/${path}`, { method: "POST", body });
        if (f.statut === "brouillon") {
          act.append(
            el("a", { class: "btn", href: `/factures/${id}/modifier`, text: "Modifier" }),
            btn("Émettre la facture", async () => {
              const j = prompt("Délai de paiement, en jours (0 = à réception) ?", "30"); if (j === null) return;
              await post("emit", { echeance_jours: Number(j) >= 0 && j !== "" ? Number(j) : undefined });
              alertBox("Facture émise : elle a maintenant son numéro légal et ne peut plus être modifiée.", "success"); await load();
            }, "btn"),
            btn("Supprimer le brouillon", async () => { if (!confirm("Supprimer ce brouillon ?")) return; await api("/api/factures/" + id, { method: "DELETE" }); location.href = "/factures"; }));
        }
        if (f.statut === "emise") {
          if (canPay && reste > 0) act.append(btn("Enregistrer un paiement", async () => { form.hidden = !form.hidden; if (!form.hidden) form.elements.montant.value = reste; }, "btn"));
          if (canCancel && f.total_paye === 0) act.append(btn("Annuler la facture (avoir)", async () => {
            const motif = prompt("Motif de l'annulation (un avoir sera émis) :"); if (!motif) return;
            await post("cancel", { motif }); await load();
          }));
          act.append(btn("Vérifier l'intégrité", async () => { const r = await api(`/api/factures/${id}/verify`); alertBox(r.integre ? "Facture intacte : l'empreinte correspond à celle de l'émission." : "ATTENTION : la facture ne correspond plus à son empreinte.", r.integre ? "success" : undefined); }));
        }
        if (f.statut === "annulee") act.append(el("a", { class: "btn btn-ghost", href: `/api/factures/${id}/avoir/pdf`, target: "_blank", rel: "noopener noreferrer", text: "Avoir (PDF)" }));
        act.append(el("a", { class: "btn btn-ghost", href: `/api/factures/${id}/pdf`, target: "_blank", rel: "noopener noreferrer", text: "Télécharger le PDF" }));
      }
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
    initMenu();
    document.querySelectorAll("form[data-api]").forEach(bindForm);
    const fn = pages[document.body.dataset.page]; if (fn) fn();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
})();
