"""Phase 2, étape 3 : ordres de réparation (accueil, statuts, historique, autorisation, devis liés, rôles, isolation)."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models import OR_STATUTS, OR_TRANSITIONS, User
from conftest import PASSWORD, make_staff

YEAR = datetime.now(timezone.utc).year


# ------------------------------------------------------------------ outils
def mk_client(api, nom="Houngbo", telephone="+229 97 00 00 01"):
    r = api.post("/api/clients", json={"type": "particulier", "nom": nom, "prenom": "Marc", "telephone": telephone})
    assert r.status_code == 201, r.json
    return r.json["client"]["id"]


def mk_vehicule(api, client_id=None, immat="AB 1234 RB", **kw):
    r = api.post("/api/vehicules", json={"type": "voiture", "marque": "Toyota", "modele": "Corolla",
                                         "immatriculation": immat, "client_id": client_id, **kw})
    assert r.status_code == 201, r.json
    return r.json["vehicule"]["id"]


def mk_or(api, vehicule_id=None, **kw):
    if vehicule_id is None:  # chaque appel crée un véhicule avec une plaque différente
        vehicule_id = mk_vehicule(api, mk_client(api), immat="T" + uuid.uuid4().hex[:6].upper())
    r = api.post("/api/or", json={"vehicule_id": vehicule_id, "motif": "Bruit au freinage", **kw})
    assert r.status_code == 201, r.json
    return r.json["ordre"]["id"]


def status(api, or_id, statut, **kw):
    return api.post(f"/api/or/{or_id}/status", json={"statut": statut, **kw})


def get_or(api, or_id):
    return api.get(f"/api/or/{or_id}").json


LIGNES = [{"type": "main_oeuvre", "designation": "Plaquettes", "quantite": 1, "prix_unitaire": 20000}]


def mk_devis_for(api, or_id):
    o = get_or(api, or_id)["ordre"]
    r = api.post("/api/devis", json={"client_id": o["client_id"], "vehicule_id": o["vehicule_id"], "or_id": or_id, "lignes": LIGNES})
    assert r.status_code == 201, r.json
    return r.json["devis"]["id"]


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


# ------------------------------------------------------------------ création
def test_create_or_numbers_it_and_logs_the_first_status(garage):
    cid = mk_client(garage)
    vid = mk_vehicule(garage, cid)
    r = garage.post("/api/or", json={"vehicule_id": vid, "motif": "Vidange", "symptomes": "Voyant huile", "urgent": True,
                                     "niveau_carburant": 25, "date_sortie_prevue": "2030-01-15"})
    assert r.status_code == 201
    o = r.json["ordre"]
    assert o["numero"] == f"OR-{YEAR}-0001" and o["statut"] == "en_attente" and o["urgent"] is True
    assert o["client_id"] == cid and o["client"]["nom_affiche"].startswith("Marc")  # client = propriétaire du véhicule
    assert o["date_sortie_prevue"].startswith("2030-01-15") and o["niveau_carburant"] == 25
    hist = get_or(garage, o["id"])["historique"]
    assert [(h["ancien_statut"], h["nouveau_statut"]) for h in hist] == [(None, "en_attente")]
    mk_or(garage, vid)  # 2e ordre sur le même véhicule
    assert garage.get("/api/or").json["total"] == 2


def test_numbers_are_sequential_per_garage_and_independent_from_quotes(two):
    a, b = two
    first = mk_or(a)
    d = mk_devis_for(a, first)
    a.post(f"/api/devis/{d}/send")  # consomme DEV-...-0001, pas OR
    second = mk_or(a)
    assert get_or(a, first)["ordre"]["numero"].endswith("0001") and get_or(a, second)["ordre"]["numero"].endswith("0002")
    assert get_or(b, mk_or(b))["ordre"]["numero"] == f"OR-{YEAR}-0001"


def test_vehicle_without_owner_needs_an_explicit_client(garage):
    vid = mk_vehicule(garage)
    r = garage.post("/api/or", json={"vehicule_id": vid, "motif": "Test"})
    assert r.status_code == 422 and "client_id" in r.json["details"]
    cid = mk_client(garage)
    r = garage.post("/api/or", json={"vehicule_id": vid, "client_id": cid, "motif": "Test"})
    assert r.status_code == 201 and r.json["ordre"]["client_id"] == cid


def test_create_validation(garage):
    vid = mk_vehicule(garage, mk_client(garage))

    def post(**kw):
        return garage.post("/api/or", json={"vehicule_id": vid, "motif": "Test", **kw})

    assert garage.post("/api/or", json={"vehicule_id": vid}).json["details"].get("motif")
    assert garage.post("/api/or", json={"motif": "x"}).status_code == 422
    assert post(niveau_carburant=150).status_code == 422
    assert post(kilometrage_entree=-5).status_code == 422
    assert post(date_sortie_prevue="demain").status_code == 422
    assert post(urgent="oui").status_code == 422
    assert post(mecanicien_id=str(uuid.uuid4())).status_code == 422
    assert post(client_id="nope").status_code == 422
    assert garage.post("/api/or", data="pas du json").status_code == 400


def test_archived_vehicle_or_client_is_refused(garage):
    cid = mk_client(garage)
    vid = mk_vehicule(garage, cid)
    garage.post(f"/api/clients/{cid}/archive")
    assert garage.post("/api/or", json={"vehicule_id": vid, "motif": "x"}).status_code == 422
    garage.post(f"/api/clients/{cid}/restore")
    garage.post(f"/api/vehicules/{vid}/archive")
    assert garage.post("/api/or", json={"vehicule_id": vid, "motif": "x"}).status_code == 422


def test_entry_mileage_updates_the_vehicle_but_never_lowers_it(garage):
    vid = mk_vehicule(garage, mk_client(garage), kilometrage_actuel=50000)
    r = garage.post("/api/or", json={"vehicule_id": vid, "motif": "x", "kilometrage_entree": 40000})
    assert r.status_code == 422 and "kilometrage_entree" in r.json["details"]
    assert garage.get(f"/api/vehicules/{vid}").json["vehicule"]["kilometrage_actuel"] == 50000
    assert garage.post("/api/or", json={"vehicule_id": vid, "motif": "x", "kilometrage_entree": 51000}).status_code == 201
    assert garage.get(f"/api/vehicules/{vid}").json["vehicule"]["kilometrage_actuel"] == 51000


def test_second_open_order_on_the_same_vehicle_gives_a_warning(garage):
    vid = mk_vehicule(garage, mk_client(garage))
    first = garage.post("/api/or", json={"vehicule_id": vid, "motif": "A"})
    assert first.json["avertissements"] == []
    second = garage.post("/api/or", json={"vehicule_id": vid, "motif": "B"})
    assert second.status_code == 201 and second.json["avertissements"]


# ------------------------------------------------------------------ statuts
def test_full_status_flow_with_history(garage):
    oid = mk_or(garage)
    for target in ("diagnostic", "en_cours", "attente_pieces", "en_cours", "termine", "livre"):
        r = status(garage, oid, target)
        assert r.status_code == 200, (target, r.json)
    detail = get_or(garage, oid)
    assert detail["ordre"]["statut"] == "livre" and detail["ordre"]["date_livraison"]
    assert [h["nouveau_statut"] for h in detail["historique"]] == ["en_attente", "diagnostic", "en_cours", "attente_pieces", "en_cours", "termine", "livre"]
    assert detail["transitions_possibles"] == []


def test_invalid_transitions_are_refused(garage):
    oid = mk_or(garage)
    r = status(garage, oid, "termine")
    assert r.status_code == 409 and r.json["code"] == "transition_invalide"
    assert status(garage, oid, "livre").status_code == 409
    assert status(garage, oid, "facture").status_code == 409  # réservé à la facturation
    assert status(garage, oid, "n'importe quoi").status_code == 422
    assert status(garage, oid, "en_attente").status_code == 200  # même statut : sans effet
    assert get_or(garage, oid)["ordre"]["statut"] == "en_attente"
    assert "facture" not in get_or(garage, oid)["transitions_possibles"]


def test_cancel_needs_a_reason_and_closes_the_order(garage):
    oid = mk_or(garage)
    assert status(garage, oid, "annule").status_code == 422
    assert status(garage, oid, "annule", note="Le client renonce").status_code == 200
    detail = get_or(garage, oid)
    assert detail["historique"][-1]["commentaire"] == "Le client renonce"
    assert garage.patch(f"/api/or/{oid}", json={"motif": "x"}).status_code == 409
    assert status(garage, oid, "diagnostic").status_code == 409
    assert garage.post(f"/api/or/{oid}/authorize", json={"nom": "X"}).status_code == 409
    assert garage.post("/api/devis", json={"client_id": detail["ordre"]["client_id"], "or_id": oid, "lignes": LIGNES}).status_code == 422


def test_work_without_authorization_gives_a_warning_then_not(garage):
    oid = mk_or(garage)
    r = status(garage, oid, "en_cours")
    assert r.status_code == 200 and r.json["avertissements"]
    oid2 = mk_or(garage)
    assert garage.post(f"/api/or/{oid2}/authorize", json={}).status_code == 422
    r = garage.post(f"/api/or/{oid2}/authorize", json={"nom": "Marc Houngbo"})
    assert r.status_code == 200 and r.json["ordre"]["autorisation"]["nom"] == "Marc Houngbo"
    assert status(garage, oid2, "en_cours").json["avertissements"] == []
    assert any("Marc Houngbo" in (h["commentaire"] or "") for h in get_or(garage, oid2)["historique"])


def test_patch_fields(garage):
    oid = mk_or(garage)
    r = garage.patch(f"/api/or/{oid}", json={"diagnostic": "Plaquettes usées\nDisques voilés", "travaux_effectues": "Remplacement",
                                             "urgent": True, "niveau_carburant": 50, "date_sortie_prevue": "2030-02-01", "motif": "Freins"})
    o = r.json["ordre"]
    assert r.status_code == 200 and o["urgent"] and "\n" in o["diagnostic"] and o["motif"] == "Freins" and o["niveau_carburant"] == 50
    assert garage.patch(f"/api/or/{oid}", json={"motif": ""}).status_code == 422
    assert garage.patch(f"/api/or/{oid}", json={"urgent": False, "date_sortie_prevue": ""}).json["ordre"]["date_sortie_prevue"] is None


# ------------------------------------------------------------------ devis liés
def test_sending_and_accepting_a_linked_quote_moves_the_order(garage):
    oid = mk_or(garage)
    did = mk_devis_for(garage, oid)
    assert garage.get(f"/api/devis/{did}").json["devis"]["ordre"]["numero"].startswith("OR-")
    assert garage.post(f"/api/devis/{did}/send").status_code == 200
    detail = get_or(garage, oid)
    assert detail["ordre"]["statut"] == "devis_envoye" and detail["devis"][0]["id"] == did
    assert any("envoyé" in (h["commentaire"] or "") for h in detail["historique"])
    assert garage.post(f"/api/devis/{did}/accept", json={"nom": "Marc"}).status_code == 200
    assert get_or(garage, oid)["ordre"]["statut"] == "devis_accepte"


def test_client_acceptance_through_the_public_link_moves_the_order(garage, new_api):
    oid = mk_or(garage)
    did = mk_devis_for(garage, oid)
    garage.post(f"/api/devis/{did}/send")
    token = garage.post(f"/api/devis/{did}/public-link").json["url"].rsplit("/", 1)[1]
    assert new_api().post(f"/api/public/devis/{token}/accept", json={"nom": "Marc H."}).status_code == 200
    detail = get_or(garage, oid)
    assert detail["ordre"]["statut"] == "devis_accepte"
    assert detail["historique"][-1]["par"] is None and "client" in detail["historique"][-1]["commentaire"]


def test_quote_does_not_move_an_order_that_is_already_further(garage):
    oid = mk_or(garage)
    status(garage, oid, "en_cours")
    did = mk_devis_for(garage, oid)
    garage.post(f"/api/devis/{did}/send")
    assert get_or(garage, oid)["ordre"]["statut"] == "en_cours"


def test_new_quote_version_stays_linked_to_the_order(garage):
    oid = mk_or(garage)
    did = mk_devis_for(garage, oid)
    garage.post(f"/api/devis/{did}/send")
    v2 = garage.post(f"/api/devis/{did}/new-version").json["devis"]
    assert v2["or_id"] == oid
    assert len(get_or(garage, oid)["devis"]) == 2


def test_quote_link_to_an_order_requires_the_same_client(garage):
    oid = mk_or(garage)
    other = mk_client(garage, "Zinsou", "+229 90 00 00 02")
    r = garage.post("/api/devis", json={"client_id": other, "or_id": oid, "lignes": LIGNES})
    assert r.status_code == 422 and "or_id" in r.json["details"]
    assert garage.post("/api/devis", json={"client_id": other, "or_id": "nope", "lignes": LIGNES}).status_code == 422


# ------------------------------------------------------------------ liste et recherche
def test_list_filters_and_search(garage):
    c1, c2 = mk_client(garage), mk_client(garage, "Zinsou", "+229 90 00 00 02")
    v1, v2 = mk_vehicule(garage, c1, "AB 1234 RB"), mk_vehicule(garage, c2, "CD 5678 EF")
    mk_or(garage, v1, motif="Vidange")
    o2 = mk_or(garage, v2, motif="Freins", urgent=True)
    o3 = mk_or(garage, v1, motif="Pneus")
    status(garage, o3, "annule", note="Annulé")
    assert garage.get("/api/or").json["total"] == 2  # "ouverts" par défaut
    assert garage.get("/api/or", query_string={"statut": "tous"}).json["total"] == 3
    assert garage.get("/api/or", query_string={"statut": "annule"}).json["total"] == 1
    assert [o["id"] for o in garage.get("/api/or").json["ordres"]][0] == o2  # les urgences d'abord
    assert garage.get("/api/or", query_string={"urgent": "1"}).json["total"] == 1
    assert garage.get("/api/or", query_string={"q": "ab1234"}).json["total"] == 1
    assert garage.get("/api/or", query_string={"q": "zinsou"}).json["total"] == 1
    assert garage.get("/api/or", query_string={"q": "0001"}).json["total"] == 1
    assert garage.get("/api/or", query_string={"q": "vidange"}).json["total"] == 1
    assert garage.get("/api/or", query_string={"q": "%"}).json["total"] == 0
    assert garage.get("/api/or", query_string={"vehicule_id": v1, "statut": "tous"}).json["total"] == 2
    assert garage.get("/api/or", query_string={"client_id": c2}).json["total"] == 1
    assert garage.get("/api/or", query_string={"client_id": "nope"}).status_code == 422


# ------------------------------------------------------------------ rôles
def test_mechanic_permissions(garage, app, new_api):
    oid = mk_or(garage)
    meca = login_staff(app, new_api, "mecanicien", "meca@example.com")
    meca_id = str(User.query.filter_by(email="meca@example.com").one().id)
    assert garage.patch(f"/api/or/{oid}", json={"mecanicien_id": meca_id}).status_code == 200
    assert meca.get("/api/or", query_string={"mecanicien_id": "moi"}).json["total"] == 1
    detail = meca.get(f"/api/or/{oid}").json
    assert detail["ordre"]["client"]["telephone"] is None and detail["devis"] == []  # pas de téléphone ni de devis pour le mécanicien
    r = meca.patch(f"/api/or/{oid}", json={"diagnostic": "Disques voilés", "travaux_effectues": "À faire"})
    assert r.status_code == 200 and r.json["ordre"]["diagnostic"] == "Disques voilés"
    assert meca.patch(f"/api/or/{oid}", json={"motif": "Autre"}).status_code == 403
    assert meca.patch(f"/api/or/{oid}", json={"urgent": True}).status_code == 403
    assert status(meca, oid, "diagnostic").status_code == 200
    assert meca.post(f"/api/or/{oid}/authorize", json={"nom": "X"}).status_code == 403
    assert meca.post("/api/or", json={"vehicule_id": str(uuid.uuid4()), "motif": "x"}).status_code == 403
    assert meca.get("/api/or/mecaniciens").status_code == 200
    assert meca.get("/api/clients").status_code == 403


def test_comptable_reads_but_does_not_write(garage, app, new_api):
    oid = mk_or(garage)
    compta = login_staff(app, new_api, "comptable", "compta@example.com")
    assert compta.get(f"/api/or/{oid}").status_code == 200
    assert compta.get(f"/api/or/{oid}").json["ordre"]["client"]["telephone"]  # peut lire les clients
    assert status(compta, oid, "diagnostic").status_code == 403
    assert compta.patch(f"/api/or/{oid}", json={"diagnostic": "x"}).status_code == 403


def test_receptionist_can_run_the_order(garage, app, new_api):
    recep = login_staff(app, new_api, "receptionniste", "recep@example.com")
    cid = mk_client(recep)
    vid = mk_vehicule(recep, cid)
    oid = mk_or(recep, vid)
    assert recep.post(f"/api/or/{oid}/authorize", json={"nom": "Marc"}).status_code == 200
    assert new_api().get("/api/or").status_code == 401


# ------------------------------------------------------------------ isolation
def test_garage_b_cannot_reach_garage_a_orders(two):
    a, b = two
    oid = mk_or(a)
    assert b.get("/api/or").json["total"] == 0
    assert b.get("/api/or", query_string={"q": "freinage", "statut": "tous"}).json["total"] == 0
    for method, url, body in (("get", f"/api/or/{oid}", None), ("patch", f"/api/or/{oid}", {"motif": "x"}),
                              ("post", f"/api/or/{oid}/status", {"statut": "diagnostic"}),
                              ("post", f"/api/or/{oid}/authorize", {"nom": "x"}), ("get", f"/api/or/{oid}/pdf", None)):
        assert getattr(b, method)(url, **({"json": body} if body is not None else {})).status_code == 404, url
    assert get_or(a, oid)["ordre"]["statut"] == "en_attente"


def test_garage_b_cannot_open_an_order_on_a_vehicle_of_garage_a(two):
    a, b = two
    vid_a = mk_vehicule(a, mk_client(a))
    r = b.post("/api/or", json={"vehicule_id": vid_a, "motif": "x"})
    assert r.status_code == 422 and "vehicule_id" in r.json["details"]
    own = mk_vehicule(b, mk_client(b), "ZZ 9 ZZ")
    r = b.post("/api/or", json={"vehicule_id": own, "client_id": mk_client(a, "Autre", "+229 91 00 00 03"), "motif": "x"})
    assert r.status_code == 422 and "client_id" in r.json["details"]
    assert a.get("/api/or", query_string={"statut": "tous"}).json["total"] == 0


def test_garage_b_cannot_link_a_quote_to_an_order_of_garage_a(two):
    a, b = two
    oid_a = mk_or(a)
    client_b = mk_client(b)
    r = b.post("/api/devis", json={"client_id": client_b, "or_id": oid_a, "lignes": LIGNES})
    assert r.status_code == 422 and "or_id" in r.json["details"]
    assert len(get_or(a, oid_a)["devis"]) == 0


def test_mechanics_list_is_scoped_to_the_garage(two):
    a, b = two
    assert [m["role"] for m in a.get("/api/or/mecaniciens").json["mecaniciens"]] == ["owner"]
    assert a.get("/api/or/mecaniciens").json != b.get("/api/or/mecaniciens").json


# ------------------------------------------------------------------ PDF, pages, règles
def test_pdf(garage):
    oid = mk_or(garage, symptomes="Grince à froid\nVibre au freinage", etat_arrivee="Rayure aile gauche")
    r = garage.get(f"/api/or/{oid}/pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert get_or(garage, oid)["ordre"]["numero"] in r.headers["Content-Disposition"]


def test_pages_render(new_api):
    anon = new_api()
    for url in ("/or", "/or/nouveau", f"/or/{uuid.uuid4()}"):
        assert anon.get(url).status_code == 200, url
    assert anon.get("/or/pas-un-uuid").status_code == 404


def test_transition_table_is_consistent():
    assert set(OR_TRANSITIONS) == set(OR_STATUTS)
    assert OR_TRANSITIONS["livre"] == OR_TRANSITIONS["annule"] == set()
    assert [s for s, nxt in OR_TRANSITIONS.items() if "facture" in nxt] == ["termine"]
    reachable, todo = {"en_attente"}, ["en_attente"]
    while todo:
        for nxt in OR_TRANSITIONS[todo.pop()]:
            if nxt not in reachable:
                reachable.add(nxt)
                todo.append(nxt)
    assert reachable == set(OR_STATUTS)
