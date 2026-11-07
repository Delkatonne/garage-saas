"""Phase 2, étape 4 : factures, paiements, reçus, avoirs (numérotation, inviolabilité, acomptes, idempotence, rôles, isolation)."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.errors import ApiError
from app.extensions import db
from app.models import Avoir, Facture, FactureLigne, Paiement, Recu, utcnow
from app.services.factures_core import compute_hash, payment_status
from conftest import PASSWORD, make_staff

YEAR = datetime.now(timezone.utc).year
LIGNES = [{"type": "main_oeuvre", "designation": "Remplacement plaquettes", "quantite": 2, "prix_unitaire": 20000},
          {"type": "piece", "designation": "Plaquettes avant", "quantite": 1, "prix_unitaire": 60000}]  # total 100 000


# ------------------------------------------------------------------ outils
def mk_client(api, nom="Houngbo", telephone="+229 97 00 00 01"):
    r = api.post("/api/clients", json={"type": "particulier", "nom": nom, "prenom": "Marc", "telephone": telephone})
    assert r.status_code == 201, r.json
    return r.json["client"]["id"]


def mk_vehicule(api, client_id, immat=None):
    r = api.post("/api/vehicules", json={"type": "voiture", "marque": "Toyota", "modele": "Corolla", "client_id": client_id,
                                         "immatriculation": immat or "T" + uuid.uuid4().hex[:6].upper()})
    assert r.status_code == 201, r.json
    return r.json["vehicule"]["id"]


def mk_or(api, client_id=None):
    cid = client_id or mk_client(api)
    r = api.post("/api/or", json={"vehicule_id": mk_vehicule(api, cid), "motif": "Freins"})
    assert r.status_code == 201, r.json
    return r.json["ordre"]["id"]


def mk_facture(api, **kw):
    payload = {"client_id": kw.pop("client_id", None) or mk_client(api), "lignes": LIGNES, **kw}
    r = api.post("/api/factures", json=payload)
    assert r.status_code == 201, r.json
    return r.json["facture"]["id"]


def emit(api, fid, **body):
    r = api.post(f"/api/factures/{fid}/emit", json=body or None)
    assert r.status_code == 200, r.json
    return r.json["facture"]


def issued(api, **kw):
    fid = mk_facture(api, **kw)
    emit(api, fid)
    return fid


def pay(api, fid, montant, moyen="especes", **kw):
    return api.post("/api/paiements", json={"facture_id": fid, "montant": montant, "moyen": moyen, **kw})


def get(api, fid):
    return api.get(f"/api/factures/{fid}").json


def accepted_devis(api, client_id=None, or_id=None):
    cid = client_id or mk_client(api)
    r = api.post("/api/devis", json={"client_id": cid, "or_id": or_id, "lignes": LIGNES, "remise_globale": 10000})
    assert r.status_code == 201, r.json
    did = r.json["devis"]["id"]
    assert api.post(f"/api/devis/{did}/send").status_code == 200
    assert api.post(f"/api/devis/{did}/accept", json={"nom": "Marc"}).status_code == 200
    return did


@pytest.fixture()
def garage(make_garage):
    return make_garage("Garage Alpha", "alpha@example.com")


@pytest.fixture()
def two(make_garage):
    return make_garage("Garage A", "a@example.com"), make_garage("Garage B", "b@example.com")


def login_staff(app, new_api, role, email):
    make_staff(app, "alpha@example.com", email, role)
    api = new_api()
    assert api.post("/api/auth/login", json={"email": email, "mot_de_passe": PASSWORD}).status_code == 200
    return api


# ------------------------------------------------------------------ brouillons
def test_draft_invoice_computes_totals_and_has_no_number(garage):
    garage.patch("/api/garage/profile", json={"tva_active": True, "tva_taux": 18})
    r = garage.post("/api/factures", json={"client_id": mk_client(garage), "lignes": LIGNES, "remise_globale": 10000, "total_ttc": 1})
    f = r.json["facture"]
    assert r.status_code == 201 and f["statut"] == "brouillon" and f["numero"] is None
    assert (f["sous_total_ht"], f["total_ht"], f["total_tva"], f["total_ttc"]) == (100000, 90000, 16200, 106200)
    assert f["statut_paiement"] == "brouillon" and f["conditions"]


def test_draft_can_be_edited_and_deleted_without_a_gap_in_numbers(garage):
    fid = mk_facture(garage)
    r = garage.patch(f"/api/factures/{fid}", json={"lignes": [{"designation": "Pneu", "quantite": 4, "prix_unitaire": 30000}], "remise_globale": ""})
    assert r.status_code == 200 and r.json["facture"]["total_ttc"] == 120000
    other = mk_facture(garage)
    assert garage.delete(f"/api/factures/{other}").status_code == 200
    assert garage.get(f"/api/factures/{other}").status_code == 404
    assert emit(garage, fid)["numero"] == f"FAC-{YEAR}-0001"
    assert emit(garage, mk_facture(garage))["numero"] == f"FAC-{YEAR}-0002"


def test_create_validation(garage):
    cid = mk_client(garage)
    assert garage.post("/api/factures", json={"lignes": LIGNES}).status_code == 422
    assert garage.post("/api/factures", json={"client_id": cid, "lignes": [{"designation": "", "quantite": 1, "prix_unitaire": 5}]}).status_code == 422
    assert garage.post("/api/factures", json={"client_id": cid, "devis_id": str(uuid.uuid4())}).status_code == 422
    assert garage.post("/api/factures", json={"client_id": cid, "or_id": "nope"}).status_code == 422
    assert garage.post("/api/factures", json={"client_id": cid, "remise_globale": 999999999, "lignes": LIGNES}).status_code == 422


def test_create_from_an_accepted_quote_copies_it(garage):
    did = accepted_devis(garage)
    r = garage.post("/api/factures", json={"devis_id": did})
    f = r.json["facture"]
    assert r.status_code == 201 and f["devis"]["id"] == did and len(f["lignes"]) == 2
    assert (f["sous_total_ht"], f["remise_globale"], f["total_ttc"]) == (100000, 10000, 90000)
    twin = garage.post("/api/factures", json={"devis_id": did})
    assert twin.status_code == 409 and twin.json["code"] == "facture_existe" and twin.json["details"]["facture_id"] == f["id"]


def test_only_an_accepted_quote_can_be_invoiced(garage):
    cid = mk_client(garage)
    did = garage.post("/api/devis", json={"client_id": cid, "lignes": LIGNES}).json["devis"]["id"]
    r = garage.post("/api/factures", json={"devis_id": did})
    assert r.status_code == 422 and "devis_id" in r.json["details"]


def test_create_from_an_order_uses_its_accepted_quote_and_one_invoice_per_order(garage):
    oid = mk_or(garage)
    client_id = garage.get(f"/api/or/{oid}").json["ordre"]["client_id"]
    did = accepted_devis(garage, client_id, oid)
    r = garage.post("/api/factures", json={"or_id": oid})
    f = r.json["facture"]
    assert r.status_code == 201 and f["or_id"] == oid and f["devis_id"] == did and f["total_ttc"] == 90000 and f["vehicule"]
    assert garage.post("/api/factures", json={"or_id": oid}).status_code == 409
    garage.delete(f"/api/factures/{f['id']}")
    assert garage.post("/api/factures", json={"or_id": oid}).status_code == 201  # le brouillon supprimé libère l'ordre


def test_order_without_quote_gives_an_empty_draft(garage):
    f = garage.post("/api/factures", json={"or_id": mk_or(garage)}).json["facture"]
    assert f["lignes"] == [] and f["total_ttc"] == 0


# ------------------------------------------------------------------ émission et inviolabilité
def test_emit_assigns_number_freezes_data_and_hash(garage):
    fid = mk_facture(garage)
    f = emit(garage, fid, echeance_jours=15)
    assert f["statut"] == "emise" and f["numero"].startswith(f"FAC-{YEAR}-") and f["empreinte"]
    assert (datetime.fromisoformat(f["echeance"]) - datetime.fromisoformat(f["emise_le"])).days == 15
    assert garage.get(f"/api/factures/{fid}/verify").json["integre"] is True
    stored = db.session.get(Facture, uuid.UUID(fid))
    assert stored.snapshot["client"]["nom_affiche"].startswith("Marc") and stored.snapshot["garage"]["nom_garage"] == "Garage Alpha"


def test_issued_invoice_cannot_be_changed_or_deleted_through_the_api(garage):
    fid = issued(garage)
    assert garage.patch(f"/api/factures/{fid}", json={"conditions": "autre"}).status_code == 409
    assert garage.patch(f"/api/factures/{fid}", json={"lignes": []}).json["code"] == "document_verrouille"
    assert garage.delete(f"/api/factures/{fid}").status_code == 409
    assert garage.post(f"/api/factures/{fid}/emit").status_code == 409


def test_issued_invoice_is_protected_even_by_direct_database_changes(garage):
    fid = issued(garage)
    uid = uuid.UUID(fid)
    f = db.session.get(Facture, uid)
    f.total_ttc = D("1")
    with pytest.raises(ApiError) as exc:
        db.session.commit()
    assert exc.value.code == "document_verrouille"
    db.session.rollback()
    ligne = db.session.get(Facture, uid).lignes[0]
    ligne.prix_unitaire = D("1")
    with pytest.raises(ApiError):
        db.session.commit()
    db.session.rollback()
    db.session.delete(db.session.get(Facture, uid))
    with pytest.raises(ApiError):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(Facture, uid).total_ttc == D("100000")
    assert garage.get(f"/api/factures/{fid}/verify").json["integre"] is True


def test_hash_changes_when_content_changes(garage):
    fid = issued(garage)
    f = db.session.get(Facture, uuid.UUID(fid))
    original = f.hash_integrite
    assert compute_hash(f) == original
    f.lignes[0].designation = "Autre chose"  # modification en mémoire seulement (jamais enregistrée)
    assert compute_hash(f) != original
    db.session.rollback()


def test_emit_validation(garage):
    cid = mk_client(garage)
    empty = garage.post("/api/factures", json={"client_id": cid}).json["facture"]["id"]
    r = garage.post(f"/api/factures/{empty}/emit")
    assert r.status_code == 422 and "lignes" in r.json["details"]
    free = mk_facture(garage, client_id=cid, lignes=[{"designation": "Offert", "quantite": 1, "prix_unitaire": 0}])
    assert garage.post(f"/api/factures/{free}/emit").status_code == 422
    assert garage.post(f"/api/factures/{empty}/emit", json={"echeance_jours": 9999}).status_code == 422
    fid = mk_facture(garage, client_id=cid)
    garage.post(f"/api/clients/{cid}/archive")
    assert garage.post(f"/api/factures/{fid}/emit").status_code == 422


def test_emitting_moves_a_finished_order_to_facture_but_not_a_running_one(garage):
    done, running = mk_or(garage), mk_or(garage)
    for oid, path in ((done, ("diagnostic", "termine")), (running, ("en_cours",))):
        for st in path:
            assert garage.post(f"/api/or/{oid}/status", json={"statut": st}).status_code == 200
    emit(garage, mk_facture(garage, client_id=garage.get(f"/api/or/{done}").json["ordre"]["client_id"], or_id=done))
    emit(garage, mk_facture(garage, client_id=garage.get(f"/api/or/{running}").json["ordre"]["client_id"], or_id=running))
    assert garage.get(f"/api/or/{done}").json["ordre"]["statut"] == "facture"
    assert garage.get(f"/api/or/{running}").json["ordre"]["statut"] == "en_cours"
    assert garage.post(f"/api/or/{done}/status", json={"statut": "livre"}).status_code == 200  # facturé -> livré


# ------------------------------------------------------------------ paiements et reçus
def test_partial_then_full_payment_with_receipts(garage):
    fid = issued(garage)
    r = pay(garage, fid, 30000)
    assert r.status_code == 201
    out = r.json
    assert out["paiement"]["recu"]["numero"] == f"REC-{YEAR}-0001" and out["paiement"]["recu"]["solde_restant"] == 70000
    assert out["facture"]["reste_a_payer"] == 70000
    assert get(garage, fid)["facture"]["statut_paiement"] == "partielle"
    assert pay(garage, fid, 80000).status_code == 422  # dépasse le reste
    r = pay(garage, fid, 70000, "momo_mtn", reference_transaction="TX-555")
    assert r.status_code == 201 and r.json["paiement"]["recu"]["numero"].endswith("0002") and r.json["paiement"]["recu"]["solde_restant"] == 0
    detail = get(garage, fid)
    assert detail["facture"]["statut_paiement"] == "payee" and detail["facture"]["reste_a_payer"] == 0 and len(detail["paiements"]) == 2
    assert pay(garage, fid, 1).status_code == 409 and pay(garage, fid, 1).json["code"] == "facture_soldee"


def test_payment_validation(garage):
    fid = issued(garage)
    assert pay(garage, fid, 0).status_code == 422
    assert pay(garage, fid, -5).status_code == 422
    assert pay(garage, fid, 1000.5).status_code == 422  # FCFA : pas de décimales
    assert pay(garage, fid, "abc").status_code == 422
    assert pay(garage, fid, 1000, "troc").status_code == 422
    assert pay(garage, fid, 1000, date_paiement="demain").status_code == 422
    assert pay(garage, fid, 1000, date_paiement=(datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()).status_code == 422
    assert garage.post("/api/paiements", json={"montant": 1000, "moyen": "especes"}).status_code == 422  # ni facture ni ordre
    assert garage.post("/api/paiements", json={"facture_id": fid, "or_id": mk_or(garage), "montant": 1000, "moyen": "especes"}).status_code == 422
    assert pay(garage, str(uuid.uuid4()), 1000).status_code == 422
    draft = mk_facture(garage)
    r = pay(garage, draft, 1000)
    assert r.status_code == 409 and r.json["code"] == "facture_non_emise"


def test_payment_is_idempotent_when_the_request_is_replayed(garage):
    fid = issued(garage)
    headers = {"Idempotency-Key": "pay-abcdef-0001"}
    first = garage.post("/api/paiements", json={"facture_id": fid, "montant": 20000, "moyen": "especes"}, headers=headers)
    again = garage.post("/api/paiements", json={"facture_id": fid, "montant": 20000, "moyen": "especes"}, headers=headers)
    assert first.status_code == 201 and again.status_code == 200 and again.json["rejoue"] is True
    assert again.json["paiement"]["id"] == first.json["paiement"]["id"]
    assert Paiement.query.count() == 1 and Recu.query.count() == 1
    assert get(garage, fid)["facture"]["total_paye"] == 20000
    second = garage.post("/api/paiements", json={"facture_id": fid, "montant": 5000, "moyen": "especes"}, headers={"Idempotency-Key": "pay-abcdef-0002"})
    assert second.status_code == 201 and Paiement.query.count() == 2
    assert garage.post("/api/paiements", json={"facture_id": fid, "montant": 1, "moyen": "especes"}, headers={"Idempotency-Key": "x"}).status_code == 422


def test_cancelling_a_payment_restores_the_balance_and_keeps_the_receipt(garage):
    fid = issued(garage)
    pid = pay(garage, fid, 40000).json["paiement"]["id"]
    assert garage.post(f"/api/paiements/{pid}/cancel", json={}).status_code == 422  # motif obligatoire
    r = garage.post(f"/api/paiements/{pid}/cancel", json={"motif": "Erreur de saisie"})
    assert r.status_code == 200 and r.json["paiement"]["statut"] == "annule"
    detail = get(garage, fid)
    assert detail["facture"]["total_paye"] == 0 and detail["facture"]["statut_paiement"] in ("impayee", "en_retard")
    assert detail["paiements"][0]["statut"] == "annule" and detail["paiements"][0]["recu"]["numero"]
    assert garage.post(f"/api/paiements/{pid}/cancel", json={"motif": "x"}).status_code == 409
    assert garage.get(f"/api/paiements/{pid}/recu").status_code == 200  # le reçu reste imprimable (marqué « annulé »)
    assert pay(garage, fid, 100000).status_code == 201  # le solde est de nouveau dû en entier


def test_deposit_on_an_order_is_attached_to_the_invoice_at_emission(garage):
    oid = mk_or(garage)
    client_id = garage.get(f"/api/or/{oid}").json["ordre"]["client_id"]
    r = garage.post("/api/paiements", json={"or_id": oid, "montant": 30000, "moyen": "momo_moov"})
    assert r.status_code == 201 and r.json["paiement"]["recu"]["solde_restant"] is None and r.json["facture"] is None
    assert garage.get("/api/paiements", query_string={"or_id": oid}).json["total"] == 1
    fid = mk_facture(garage, client_id=client_id, or_id=oid)
    f = emit(garage, fid)
    assert f["total_paye"] == 30000 and f["reste_a_payer"] == 70000
    assert len(get(garage, fid)["paiements"]) == 1
    late = garage.post("/api/paiements", json={"or_id": oid, "montant": 1000, "moyen": "especes"})
    assert late.status_code == 409 and late.json["code"] == "facture_existe"


def test_deposits_larger_than_the_invoice_block_emission(garage):
    oid = mk_or(garage)
    client_id = garage.get(f"/api/or/{oid}").json["ordre"]["client_id"]
    garage.post("/api/paiements", json={"or_id": oid, "montant": 150000, "moyen": "especes"})
    fid = mk_facture(garage, client_id=client_id, or_id=oid)
    r = garage.post(f"/api/factures/{fid}/emit")
    assert r.status_code == 409 and r.json["code"] == "acomptes_excessifs"


def test_cash_register_totals_by_method(garage):
    f1, f2 = issued(garage), issued(garage)
    pay(garage, f1, 10000)
    pay(garage, f1, 5000, "momo_mtn")
    pid = pay(garage, f2, 7000).json["paiement"]["id"]
    garage.post(f"/api/paiements/{pid}/cancel", json={"motif": "Erreur"})
    pay(garage, f2, 2000, date_paiement=(datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat())
    today = garage.get("/api/paiements/caisse").json
    assert today["total"] == 15000 and today["nombre"] == 2 and today["par_moyen"] == {"especes": 10000, "momo_mtn": 5000} and today["annules"] == 1
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    assert garage.get("/api/paiements/caisse", query_string={"date": yesterday}).json["total"] == 2000
    assert garage.get("/api/paiements/caisse", query_string={"date": "hier"}).status_code == 422


# ------------------------------------------------------------------ annulation par avoir
def test_cancel_an_invoice_with_a_credit_note(garage):
    fid = issued(garage)
    assert garage.post(f"/api/factures/{fid}/cancel", json={}).status_code == 422  # motif obligatoire
    r = garage.post(f"/api/factures/{fid}/cancel", json={"motif": "Erreur de facturation"})
    f = r.json["facture"]
    assert r.status_code == 200 and f["statut"] == "annulee" and f["statut_paiement"] == "annulee"
    detail = get(garage, fid)
    assert detail["avoir"]["numero"] == f"AV-{YEAR}-0001" and Avoir.query.count() == 1
    assert garage.get(f"/api/factures/{fid}/avoir/pdf").status_code == 200
    assert garage.post(f"/api/factures/{fid}/cancel", json={"motif": "x"}).status_code == 409
    assert pay(garage, fid, 1000).json["code"] == "facture_annulee"
    assert garage.patch(f"/api/factures/{fid}", json={"conditions": "x"}).status_code == 409
    assert garage.get(f"/api/factures/{fid}/verify").json["integre"] is True  # l'annulation ne touche pas au contenu émis


def test_invoice_with_payments_cannot_be_cancelled_until_they_are_cancelled(garage):
    fid = issued(garage)
    pid = pay(garage, fid, 10000).json["paiement"]["id"]
    r = garage.post(f"/api/factures/{fid}/cancel", json={"motif": "x"})
    assert r.status_code == 409 and r.json["code"] == "paiements_existants"
    garage.post(f"/api/paiements/{pid}/cancel", json={"motif": "Remboursé"})
    assert garage.post(f"/api/factures/{fid}/cancel", json={"motif": "Erreur"}).status_code == 200


def test_a_cancelled_invoice_frees_the_order_for_a_new_one(garage):
    oid = mk_or(garage)
    client_id = garage.get(f"/api/or/{oid}").json["ordre"]["client_id"]
    fid = mk_facture(garage, client_id=client_id, or_id=oid)
    emit(garage, fid)
    assert garage.post("/api/factures", json={"or_id": oid, "lignes": LIGNES}).status_code == 409
    garage.post(f"/api/factures/{fid}/cancel", json={"motif": "Erreur"})
    new = garage.post("/api/factures", json={"or_id": oid, "lignes": LIGNES})
    assert new.status_code == 201
    assert emit(garage, new.json["facture"]["id"])["numero"].endswith("0002")


# ------------------------------------------------------------------ statuts de paiement, liste, calcul
def test_payment_status_helper():
    f = Facture(statut="emise", total_ttc=D("1000"), echeance=utcnow() + timedelta(days=5))
    assert payment_status(f, 0) == "impayee" and payment_status(f, 400) == "partielle" and payment_status(f, 1000) == "payee"
    f.echeance = utcnow() - timedelta(days=1)
    assert payment_status(f, 0) == "en_retard" and payment_status(f, 1000) == "payee"
    assert payment_status(Facture(statut="brouillon", total_ttc=D("1")), 0) == "brouillon"
    assert payment_status(Facture(statut="annulee", total_ttc=D("1")), 0) == "annulee"


def test_list_filters_by_payment_status(garage):
    cid = mk_client(garage)
    draft = mk_facture(garage, client_id=cid)
    unpaid, partial, paid, cancelled = (issued(garage, client_id=cid) for _ in range(4))
    late = mk_facture(garage, client_id=cid)
    emit(garage, late, echeance_jours=0)  # échéance = émission : dépassée dès la requête suivante
    pay(garage, partial, 10000)
    pay(garage, paid, 100000)
    garage.post(f"/api/factures/{cancelled}/cancel", json={"motif": "x"})
    counts = {s: garage.get("/api/factures", query_string={"statut": s}).json["total"]
              for s in ("tous", "brouillon", "emise", "impayees", "partielles", "payees", "en_retard", "annulee")}
    assert counts == {"tous": 6, "brouillon": 1, "emise": 4, "impayees": 2, "partielles": 1, "payees": 1, "en_retard": 1, "annulee": 1}
    assert garage.get(f"/api/factures/{late}").json["facture"]["statut_paiement"] == "en_retard"
    assert garage.get("/api/factures", query_string={"q": "houngbo"}).json["total"] == 6
    assert garage.get("/api/factures", query_string={"q": "0001"}).json["total"] == 1
    assert garage.get("/api/factures", query_string={"q": "%"}).json["total"] == 0
    assert garage.get("/api/factures", query_string={"client_id": cid}).json["total"] == 6
    assert garage.get("/api/factures", query_string={"client_id": "nope"}).status_code == 422
    assert draft and unpaid


# ------------------------------------------------------------------ PDF
def test_pdfs(garage):
    draft = mk_facture(garage)
    assert garage.get(f"/api/factures/{draft}/pdf").data.startswith(b"%PDF")
    fid = issued(garage)
    pid = pay(garage, fid, 25000).json["paiement"]["id"]
    for url in (f"/api/factures/{fid}/pdf", f"/api/paiements/{pid}/recu"):
        r = garage.get(url)
        assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF"), url
    assert garage.get(f"/api/factures/{fid}/avoir/pdf").status_code == 404
    acompte = garage.post("/api/paiements", json={"or_id": mk_or(garage), "montant": 5000, "moyen": "especes"}).json["paiement"]["id"]
    assert garage.get(f"/api/paiements/{acompte}/recu").status_code == 200


# ------------------------------------------------------------------ rôles
def test_roles(garage, app, new_api):
    fid = issued(garage)
    pid = pay(garage, fid, 10000).json["paiement"]["id"]
    meca = login_staff(app, new_api, "mecanicien", "meca@example.com")
    for url in ("/api/factures", f"/api/factures/{fid}", "/api/paiements", "/api/paiements/caisse", f"/api/paiements/{pid}/recu"):
        assert meca.get(url).status_code == 403, url
    recep = login_staff(app, new_api, "receptionniste", "recep@example.com")
    mine = mk_facture(recep, client_id=mk_client(recep, "Autre", "+229 91 00 00 03"))
    assert recep.post(f"/api/factures/{mine}/emit").status_code == 200
    assert pay(recep, mine, 5000).status_code == 201
    assert recep.post(f"/api/factures/{mine}/cancel", json={"motif": "x"}).status_code == 403
    assert recep.delete(f"/api/factures/{mk_facture(recep)}").status_code == 403
    assert recep.post(f"/api/paiements/{pid}/cancel", json={"motif": "x"}).status_code == 403
    compta = login_staff(app, new_api, "comptable", "compta@example.com")
    assert compta.get(f"/api/factures/{fid}").status_code == 200
    assert compta.post(f"/api/paiements/{pid}/cancel", json={"motif": "Remboursé"}).status_code == 200
    assert compta.post(f"/api/factures/{fid}/cancel", json={"motif": "Erreur"}).status_code == 200
    assert new_api().get("/api/factures").status_code == 401 and new_api().post("/api/paiements", json={}).status_code == 401


# ------------------------------------------------------------------ isolation entre garages
def test_garage_b_cannot_reach_garage_a_billing(two):
    a, b = two
    fid = issued(a)
    pid = pay(a, fid, 10000).json["paiement"]["id"]
    assert b.get("/api/factures").json["total"] == 0 and b.get("/api/paiements").json["total"] == 0
    assert b.get("/api/factures", query_string={"q": "houngbo"}).json["total"] == 0
    assert b.get("/api/paiements/caisse").json["total"] == 0
    for method, url, body in (("get", f"/api/factures/{fid}", None), ("patch", f"/api/factures/{fid}", {"conditions": "x"}),
                              ("delete", f"/api/factures/{fid}", None), ("post", f"/api/factures/{fid}/emit", None),
                              ("post", f"/api/factures/{fid}/cancel", {"motif": "x"}), ("get", f"/api/factures/{fid}/pdf", None),
                              ("get", f"/api/factures/{fid}/verify", None), ("get", f"/api/factures/{fid}/avoir/pdf", None),
                              ("post", f"/api/paiements/{pid}/cancel", {"motif": "x"}), ("get", f"/api/paiements/{pid}/recu", None)):
        assert getattr(b, method)(url, **({"json": body} if body is not None else {})).status_code == 404, url
    r = pay(b, fid, 1000)
    assert r.status_code == 422 and "facture_id" in r.json["details"]
    assert get(a, fid)["facture"]["total_paye"] == 10000


def test_garage_b_cannot_invoice_garage_a_documents(two):
    a, b = two
    client_a = mk_client(a)
    oid_a = mk_or(a, client_a)
    did_a = accepted_devis(a, client_a)
    own = mk_client(b)
    for payload in ({"client_id": client_a, "lignes": LIGNES}, {"client_id": own, "or_id": oid_a}, {"client_id": own, "devis_id": did_a}, {"or_id": oid_a}, {"devis_id": did_a}):
        assert b.post("/api/factures", json=payload).status_code == 422, payload
    assert b.post("/api/paiements", json={"or_id": oid_a, "montant": 1000, "moyen": "especes"}).status_code == 422
    assert a.get("/api/factures").json["total"] == 0


def test_numbers_are_independent_per_garage(two):
    a, b = two
    assert emit(a, mk_facture(a))["numero"] == f"FAC-{YEAR}-0001"
    assert emit(b, mk_facture(b))["numero"] == f"FAC-{YEAR}-0001"
    fid_b = issued(b)
    assert pay(b, fid_b, 1000).json["paiement"]["recu"]["numero"] == f"REC-{YEAR}-0001"
    assert pay(a, issued(a), 1000).json["paiement"]["recu"]["numero"] == f"REC-{YEAR}-0001"


# ------------------------------------------------------------------ pages
def test_pages_render(new_api):
    anon = new_api()
    for url in ("/factures", "/factures/nouveau", f"/factures/{uuid.uuid4()}", f"/factures/{uuid.uuid4()}/modifier"):
        assert anon.get(url).status_code == 200, url
    assert anon.get("/factures/pas-un-uuid").status_code == 404
