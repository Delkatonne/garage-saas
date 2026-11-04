"""Phase 2, étape 2 : devis (montants, numérotation, cycle de vie, versions, lien client, PDF, isolation)."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.extensions import db
from app.models import AuditLog, Devis, utcnow
from app.services import devis_calc as calc
from conftest import PASSWORD, make_staff

YEAR = datetime.now(timezone.utc).year


# ------------------------------------------------------------------ outils
def mk_client(api, nom="Houngbo", telephone="+229 97 00 00 01"):
    r = api.post("/api/clients", json={"type": "particulier", "nom": nom, "prenom": "Marc", "telephone": telephone})
    assert r.status_code == 201, r.json
    return r.json["client"]["id"]


def mk_vehicule(api, client_id=None, immat="AB 1234 RB"):
    r = api.post("/api/vehicules", json={"type": "voiture", "marque": "Toyota", "modele": "Corolla",
                                         "immatriculation": immat, "client_id": client_id})
    assert r.status_code == 201, r.json
    return r.json["vehicule"]["id"]


def lignes(*items):
    return list(items) if items else [
        {"type": "main_oeuvre", "designation": "Vidange moteur", "quantite": 2.5, "prix_unitaire": 15000, "remise_pct": 10},
        {"type": "piece", "designation": "Filtre à huile", "quantite": 1, "prix_unitaire": 45500},
    ]


def mk_devis(api, client_id=None, **kw):
    payload = {"client_id": client_id or mk_client(api), "lignes": lignes()}
    payload.update(kw)
    r = api.post("/api/devis", json=payload)
    assert r.status_code == 201, r.json
    return r.json["devis"]["id"]


def send(api, devis_id, **body):
    r = api.post(f"/api/devis/{devis_id}/send", json=body or None)
    assert r.status_code == 200, r.json
    return r.json["devis"]


def token_of(api, devis_id):
    r = api.post(f"/api/devis/{devis_id}/public-link")
    assert r.status_code == 200, r.json
    return r.json["url"].rsplit("/", 1)[1]


@pytest.fixture()
def garage(make_garage):
    return make_garage("Garage Alpha", "alpha@example.com")


@pytest.fixture()
def two(make_garage):
    return make_garage("Garage A", "a@example.com"), make_garage("Garage B", "b@example.com")


# ------------------------------------------------------------------ calcul des montants
def test_calc_rounding_and_totals():
    l1 = calc.line_total(D("2.5"), D("15000"), D("10"), 0)
    assert l1 == D("33750")
    assert calc.line_total(D("1"), D("0.125"), D("0"), 2) == D("0.13")  # arrondi commercial (0,5 vers le haut)
    sous, remise, ht, tva, ttc = calc.totals([l1, D("45500")], D("5000"), True, D("18"), 0)
    assert (sous, remise, ht, tva, ttc) == (D("79250"), D("5000"), D("74250"), D("13365"), D("87615"))
    assert calc.totals([D("100")], D(0), False, D("18"), 0)[3:] == (D(0), D("100"))  # sans TVA
    with pytest.raises(ValueError):
        calc.totals([D("100")], D("200"), False, 0, 0)


def test_create_draft_computes_totals_on_the_server(garage):
    garage.patch("/api/garage/profile", json={"tva_active": True, "tva_taux": 18})
    r = garage.post("/api/devis", json={"client_id": mk_client(garage), "remise_globale": 5000, "lignes": lignes(),
                                        "total_ttc": 1, "numero": "DEV-HACK"})  # champs calculés/protégés ignorés
    assert r.status_code == 201
    d = r.json["devis"]
    assert d["statut"] == "brouillon" and d["numero"] is None and d["version"] == 1
    assert (d["sous_total_ht"], d["total_ht"], d["total_tva"], d["total_ttc"]) == (79250, 74250, 13365, 87615)
    assert [l["total_ht"] for l in d["lignes"]] == [33750, 45500]
    assert d["tva_active"] is True and d["devise"] == "XOF"


def test_no_vat_garage_has_total_equal_to_ht(garage):
    garage.patch("/api/garage/profile", json={"tva_active": False})
    d = garage.get(f"/api/devis/{mk_devis(garage)}").json["devis"]
    assert d["total_tva"] == 0 and d["total_ttc"] == d["total_ht"] == 79250


def test_line_and_quote_validation(garage):
    cid = mk_client(garage)

    def post(**kw):
        return garage.post("/api/devis", json={"client_id": cid, "lignes": lignes(), **kw})

    r = post(lignes=[{"type": "piece", "quantite": 1, "prix_unitaire": 10}])
    assert r.status_code == 422 and "Ligne 1" in r.json["details"]["lignes"]
    assert post(lignes=[{"designation": "X", "quantite": 0, "prix_unitaire": 10}]).status_code == 422
    assert post(lignes=[{"designation": "X", "quantite": 1, "prix_unitaire": -5}]).status_code == 422
    assert post(lignes=[{"designation": "X", "quantite": 1, "prix_unitaire": 10.5}]).status_code == 422  # FCFA : 0 décimale
    assert post(lignes=[{"designation": "X", "quantite": 1, "prix_unitaire": 10, "remise_pct": 150}]).status_code == 422
    assert post(lignes=[{"designation": "X", "quantite": "abc", "prix_unitaire": 10}]).status_code == 422
    assert post(lignes=[{"designation": "X", "type": "inconnu", "quantite": 1, "prix_unitaire": 10}]).status_code == 422
    assert post(lignes="pas une liste").status_code == 422
    assert post(remise_globale=999999999).status_code == 422  # remise > total des lignes
    assert garage.post("/api/devis", json={"client_id": "nope", "lignes": lignes()}).status_code == 422
    assert garage.post("/api/devis", json={"lignes": lignes()}).status_code == 422


def test_html_in_designation_is_stored_as_text(garage):
    d = garage.get(f"/api/devis/{mk_devis(garage, lignes=lignes({'designation': '<b>x</b> & y', 'quantite': 1, 'prix_unitaire': 100}))}").json["devis"]
    assert d["lignes"][0]["designation"] == "<b>x</b> & y"


def test_update_replaces_lines_and_recomputes(garage):
    did = mk_devis(garage)
    r = garage.patch(f"/api/devis/{did}", json={"lignes": lignes({"designation": "Pneu", "quantite": 4, "prix_unitaire": 30000}),
                                                "remise_globale": ""})
    assert r.status_code == 200 and r.json["devis"]["total_ttc"] == 120000 and len(r.json["devis"]["lignes"]) == 1
    # modifier le client/véhicule seulement ne touche pas aux lignes
    cid2 = mk_client(garage, "Zinsou", "+229 90 00 00 02")
    r = garage.patch(f"/api/devis/{did}", json={"client_id": cid2, "vehicule_id": mk_vehicule(garage, cid2)})
    assert r.status_code == 200 and r.json["devis"]["client"]["id"] == cid2 and r.json["devis"]["total_ttc"] == 120000
    assert garage.patch(f"/api/devis/{did}", json={"vehicule_id": None}).json["devis"]["vehicule"] is None


# ------------------------------------------------------------------ numérotation et envoi
def test_numbers_are_sequential_per_garage_and_year(two):
    a, b = two
    d1, d2 = mk_devis(a), mk_devis(a)
    assert send(a, d1)["numero"] == f"DEV-{YEAR}-0001"
    assert send(a, d2)["numero"] == f"DEV-{YEAR}-0002"
    assert send(b, mk_devis(b))["numero"] == f"DEV-{YEAR}-0001"  # chaque garage a sa propre séquence


def test_drafts_have_no_number_so_deleting_one_leaves_no_gap(garage):
    first, middle, last = mk_devis(garage), mk_devis(garage), mk_devis(garage)
    assert garage.get(f"/api/devis/{middle}").json["devis"]["numero"] is None
    assert garage.delete(f"/api/devis/{middle}").status_code == 200
    assert garage.get(f"/api/devis/{middle}").status_code == 404
    assert send(garage, first)["numero"].endswith("0001")
    assert send(garage, last)["numero"].endswith("0002")


def test_send_freezes_the_quote(garage):
    did = mk_devis(garage)
    sent = send(garage, did, validite_jours=15)
    assert sent["statut"] == "envoye" and sent["date_emission"] and sent["date_validite"]
    emitted = datetime.fromisoformat(sent["date_emission"])
    assert (datetime.fromisoformat(sent["date_validite"]) - emitted).days == 15
    assert garage.patch(f"/api/devis/{did}", json={"conditions": "autre"}).status_code == 409
    assert garage.delete(f"/api/devis/{did}").status_code == 409
    assert garage.post(f"/api/devis/{did}/send").status_code == 409
    # changer la TVA du garage après l'envoi ne modifie pas le devis émis
    garage.patch("/api/garage/profile", json={"tva_active": True, "tva_taux": 18})
    assert garage.get(f"/api/devis/{did}").json["devis"]["total_ttc"] == sent["total_ttc"]


def test_send_requires_lines_and_a_positive_total(garage):
    cid = mk_client(garage)
    empty = garage.post("/api/devis", json={"client_id": cid}).json["devis"]["id"]
    r = garage.post(f"/api/devis/{empty}/send")
    assert r.status_code == 422 and "lignes" in r.json["details"]
    free = mk_devis(garage, cid, lignes=lignes({"designation": "Offert", "quantite": 1, "prix_unitaire": 0}))
    assert garage.post(f"/api/devis/{free}/send").status_code == 422
    assert garage.post(f"/api/devis/{empty}/send", json={"validite_jours": 9999}).status_code == 422


def test_cannot_send_for_an_archived_client(garage):
    cid = mk_client(garage)
    did = mk_devis(garage, cid)
    garage.post(f"/api/clients/{cid}/archive")
    assert garage.post(f"/api/devis/{did}/send").status_code == 422


# ------------------------------------------------------------------ acceptation, refus, expiration
def test_accept_by_the_garage(garage):
    did = mk_devis(garage)
    assert garage.post(f"/api/devis/{did}/accept", json={"nom": "Marc"}).status_code == 409  # pas encore envoyé
    send(garage, did)
    assert garage.post(f"/api/devis/{did}/accept", json={}).status_code == 422
    r = garage.post(f"/api/devis/{did}/accept", json={"nom": "Marc Houngbo"})
    d = r.json["devis"]
    assert r.status_code == 200 and d["statut"] == "accepte" and d["acceptation_nom"] == "Marc Houngbo" and d["acceptation_mode"] == "atelier"
    assert garage.post(f"/api/devis/{did}/accept", json={"nom": "X"}).status_code == 409
    assert garage.post(f"/api/devis/{did}/refuse", json={}).status_code == 409


def test_refuse_then_new_version(garage):
    did = mk_devis(garage)
    send(garage, did)
    r = garage.post(f"/api/devis/{did}/refuse", json={"motif": "Trop cher"})
    assert r.json["devis"]["statut"] == "refuse" and r.json["devis"]["refus_motif"] == "Trop cher"
    assert garage.post(f"/api/devis/{did}/new-version").status_code == 201


def set_validity(devis_id, days):
    d = db.session.get(Devis, uuid.UUID(devis_id))
    d.date_validite = utcnow() + timedelta(days=days)
    db.session.commit()


def test_expired_quote_cannot_be_accepted_but_can_be_versioned(garage):
    did = mk_devis(garage)
    send(garage, did)
    set_validity(did, -1)
    assert garage.get(f"/api/devis/{did}").json["devis"]["statut_effectif"] == "expire"
    assert garage.get("/api/devis", query_string={"statut": "expire"}).json["total"] == 1
    assert garage.get("/api/devis", query_string={"statut": "envoye"}).json["total"] == 0
    r = garage.post(f"/api/devis/{did}/accept", json={"nom": "X"})
    assert r.status_code == 409 and r.json["code"] == "devis_expire"
    assert garage.post(f"/api/devis/{did}/new-version").status_code == 201


def test_new_version_keeps_the_number_and_replaces_the_old_one(garage):
    did = mk_devis(garage)
    v1 = send(garage, did)
    r = garage.post(f"/api/devis/{did}/new-version")
    assert r.status_code == 201
    v2 = r.json["devis"]
    assert v2["version"] == 2 and v2["statut"] == "brouillon" and v2["numero"] is None and v2["devis_parent_id"] == did
    assert len(v2["lignes"]) == 2 and v2["total_ttc"] == v1["total_ttc"]
    again = garage.post(f"/api/devis/{did}/new-version")  # déjà une version en préparation : on la retrouve
    assert again.status_code == 200 and again.json["devis"]["id"] == v2["id"]
    garage.patch(f"/api/devis/{v2['id']}", json={"lignes": lignes({"designation": "Pneu", "quantite": 4, "prix_unitaire": 30000})})
    sent2 = send(garage, v2["id"])
    assert sent2["numero"] == v1["numero"] + "-V2"
    assert garage.get(f"/api/devis/{did}").json["devis"]["statut"] == "remplace"
    assert garage.post(f"/api/devis/{did}/new-version").status_code == 409  # un devis remplacé n'a plus de version
    # la version 3 garde le même numéro de base
    v3 = garage.post(f"/api/devis/{v2['id']}/new-version").json["devis"]
    assert send(garage, v3["id"])["numero"] == v1["numero"] + "-V3"


def test_draft_cannot_get_a_new_version_or_a_public_link(garage):
    did = mk_devis(garage)
    assert garage.post(f"/api/devis/{did}/new-version").status_code == 409
    assert garage.post(f"/api/devis/{did}/public-link").status_code == 409


# ------------------------------------------------------------------ lien public du client
def test_client_can_view_and_accept_through_the_public_link(garage, new_api):
    did = mk_devis(garage, vehicule_id=mk_vehicule(garage))
    sent = send(garage, did)
    token = token_of(garage, did)
    anon = new_api()
    r = anon.get(f"/api/public/devis/{token}")
    assert r.status_code == 200
    body = r.json
    assert body["garage"]["nom_garage"] == "Garage Alpha" and body["devis"]["numero"] == sent["numero"]
    assert body["devis"]["statut"] == "envoye" and body["client"].startswith("Marc") and "Toyota" in body["vehicule"]
    text = r.get_data(as_text=True)
    assert did not in text and "client_id" not in text and "garage_id" not in text  # aucun identifiant interne
    assert anon.post(f"/api/public/devis/{token}/accept", json={}).status_code == 422
    r = anon.post(f"/api/public/devis/{token}/accept", json={"nom": "Marc H."})
    assert r.status_code == 200
    d = garage.get(f"/api/devis/{did}").json["devis"]
    assert d["statut"] == "accepte" and d["acceptation_mode"] == "lien" and d["acceptation_nom"] == "Marc H."
    assert anon.post(f"/api/public/devis/{token}/accept", json={"nom": "Autre"}).status_code == 409
    assert anon.get(f"/api/public/devis/{token}").json["devis"]["statut"] == "accepte"  # lecture toujours possible
    assert AuditLog.query.filter_by(action="devis.accepte_par_client").count() == 1


def test_client_can_refuse_through_the_link(garage, new_api):
    did = mk_devis(garage)
    send(garage, did)
    token = token_of(garage, did)
    r = new_api().post(f"/api/public/devis/{token}/refuse", json={"motif": "Déjà réparé ailleurs"})
    assert r.status_code == 200
    d = garage.get(f"/api/devis/{did}").json["devis"]
    assert d["statut"] == "refuse" and d["refus_motif"] == "Déjà réparé ailleurs"


def test_new_link_invalidates_the_old_one_and_bad_tokens_are_404(garage, new_api):
    did = mk_devis(garage)
    send(garage, did)
    old, new = token_of(garage, did), token_of(garage, did)
    anon = new_api()
    assert old != new
    assert anon.get(f"/api/public/devis/{old}").status_code == 404
    assert anon.get(f"/api/public/devis/{new}").status_code == 200
    assert anon.get("/api/public/devis/court").status_code == 404
    assert anon.get("/api/public/devis/" + "x" * 43).status_code == 404
    assert anon.post("/api/public/devis/" + "x" * 43 + "/accept", json={"nom": "Pirate"}).status_code == 404


def test_public_link_cannot_accept_expired_or_replaced_quotes(garage, new_api):
    did = mk_devis(garage)
    send(garage, did)
    token = token_of(garage, did)
    anon = new_api()
    set_validity(did, -1)
    r = anon.post(f"/api/public/devis/{token}/accept", json={"nom": "X"})
    assert r.status_code == 409 and r.json["code"] == "devis_expire"
    assert anon.get(f"/api/public/devis/{token}").json["devis"]["statut"] == "expire"
    set_validity(did, 5)
    new = garage.post(f"/api/devis/{did}/new-version").json["devis"]["id"]
    send(garage, new)  # l'ancien devient "remplace"
    r = anon.post(f"/api/public/devis/{token}/accept", json={"nom": "X"})
    assert r.status_code == 409 and r.json["code"] == "devis_remplace"


# ------------------------------------------------------------------ PDF
def test_pdf_for_staff_and_for_the_client(garage, new_api):
    did = mk_devis(garage)
    r = garage.get(f"/api/devis/{did}/pdf")  # un brouillon a aussi son PDF (filigrane)
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    send(garage, did)
    r = garage.get(f"/api/devis/{did}/pdf")
    assert r.status_code == 200 and "Devis-DEV-" in r.headers["Content-Disposition"]
    token = token_of(garage, did)
    r = new_api().get(f"/api/public/devis/{token}/pdf")
    assert r.status_code == 200 and r.data.startswith(b"%PDF")


# ------------------------------------------------------------------ isolation entre garages
def test_garage_b_cannot_reach_garage_a_quotes(two, new_api):
    a, b = two
    did = mk_devis(a)
    send(a, did)
    assert b.get("/api/devis").json["total"] == 0
    assert b.get("/api/devis", query_string={"q": "Houngbo"}).json["total"] == 0
    assert b.get("/api/devis", query_string={"q": "DEV"}).json["total"] == 0
    for method, url, body in (("get", f"/api/devis/{did}", None), ("patch", f"/api/devis/{did}", {"conditions": "x"}),
                              ("delete", f"/api/devis/{did}", None), ("post", f"/api/devis/{did}/send", None),
                              ("post", f"/api/devis/{did}/accept", {"nom": "x"}), ("post", f"/api/devis/{did}/refuse", {}),
                              ("post", f"/api/devis/{did}/new-version", None), ("post", f"/api/devis/{did}/public-link", None),
                              ("get", f"/api/devis/{did}/pdf", None)):
        assert getattr(b, method)(url, **({"json": body} if body is not None else {})).status_code == 404, url
    assert a.get(f"/api/devis/{did}").json["devis"]["statut"] == "envoye"


def test_garage_b_cannot_quote_for_a_client_or_vehicle_of_garage_a(two):
    a, b = two
    client_a = mk_client(a)
    vehicule_a = mk_vehicule(a, client_a)
    r = b.post("/api/devis", json={"client_id": client_a, "lignes": lignes()})
    assert r.status_code == 422 and "client_id" in r.json["details"]
    own = mk_client(b, "Autre", "+229 91 00 00 03")
    r = b.post("/api/devis", json={"client_id": own, "vehicule_id": vehicule_a, "lignes": lignes()})
    assert r.status_code == 422 and "vehicule_id" in r.json["details"]
    mine = mk_devis(b, own)
    assert b.patch(f"/api/devis/{mine}", json={"client_id": client_a}).status_code == 422
    assert b.patch(f"/api/devis/{mine}", json={"vehicule_id": vehicule_a}).status_code == 422
    assert a.get("/api/devis").json["total"] == 0


def test_each_garage_numbers_independently_and_listing_is_scoped(two):
    a, b = two
    send(a, mk_devis(a))
    send(a, mk_devis(a))
    send(b, mk_devis(b))
    assert a.get("/api/devis").json["total"] == 2 and b.get("/api/devis").json["total"] == 1
    assert {d["numero"] for d in b.get("/api/devis").json["devis"]} == {f"DEV-{YEAR}-0001"}


# ------------------------------------------------------------------ liste et recherche
def test_list_filters_and_search(garage):
    c1, c2 = mk_client(garage), mk_client(garage, "Zinsou", "+229 90 00 00 02")
    draft, sent_id, accepted = mk_devis(garage, c1), mk_devis(garage, c1), mk_devis(garage, c2)
    send(garage, sent_id)
    send(garage, accepted)
    garage.post(f"/api/devis/{accepted}/accept", json={"nom": "Zinsou"})
    assert garage.get("/api/devis").json["total"] == 3
    for statut, expected in (("brouillon", 1), ("envoye", 1), ("accepte", 1), ("refuse", 0)):
        assert garage.get("/api/devis", query_string={"statut": statut}).json["total"] == expected, statut
    assert garage.get("/api/devis", query_string={"q": "zinsou"}).json["total"] == 1
    assert garage.get("/api/devis", query_string={"client_id": c1}).json["total"] == 2
    assert garage.get("/api/devis", query_string={"q": "0001"}).json["total"] == 1
    assert garage.get("/api/devis", query_string={"q": "%"}).json["total"] == 0
    assert garage.get("/api/devis", query_string={"client_id": "nope"}).status_code == 422
    first = garage.get("/api/devis").json["devis"][0]
    assert first["client"]["nom_affiche"] and "lignes" not in first


# ------------------------------------------------------------------ permissions et pages
def login_staff(app, new_api, role, email):
    make_staff(app, "alpha@example.com", email, role)
    api = new_api()
    assert api.post("/api/auth/login", json={"email": email, "mot_de_passe": PASSWORD}).status_code == 200
    return api


def test_roles(garage, app, new_api):
    did = mk_devis(garage)
    meca = login_staff(app, new_api, "mecanicien", "meca@example.com")
    assert meca.get("/api/devis").status_code == 403 and meca.get(f"/api/devis/{did}/pdf").status_code == 403
    compta = login_staff(app, new_api, "comptable", "compta@example.com")
    assert compta.get("/api/devis").status_code == 200 and compta.get(f"/api/devis/{did}/pdf").status_code == 200
    assert compta.post(f"/api/devis/{did}/send").status_code == 403
    assert compta.post("/api/devis", json={"client_id": mk_client(garage, "N", "+229 92 00 00 04"), "lignes": lignes()}).status_code == 403
    recep = login_staff(app, new_api, "receptionniste", "recep@example.com")
    assert recep.post(f"/api/devis/{did}/send").status_code == 200
    assert new_api().get("/api/devis").status_code == 401


def test_pages_render(new_api):
    anon = new_api()
    for url in ("/devis", "/devis/nouveau", f"/devis/{uuid.uuid4()}", f"/devis/{uuid.uuid4()}/modifier", "/d/abcdefghijklmnopqrstuvwxyz"):
        assert anon.get(url).status_code == 200, url
    assert anon.get("/devis/pas-un-uuid").status_code == 404
