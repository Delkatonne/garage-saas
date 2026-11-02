"""Phase 2, étape 1 : clients, véhicules, propriétaires, permissions et isolation entre garages."""
import uuid

import pytest

from app import validators as v
from app.models import AuditLog, VehiculeProprietaire
from conftest import PASSWORD, make_staff


def client_data(**kw):
    data = {"type": "particulier", "nom": "Houngbo", "prenom": "Marc", "telephone": "+229 97 00 00 01"}
    data.update(kw)
    return data


def vehicule_data(**kw):
    data = {"type": "voiture", "marque": "Toyota", "modele": "Corolla", "immatriculation": "ab 1234 rb",
            "annee": 2015, "kilometrage_actuel": 120000}
    data.update(kw)
    return data


def new_client(api, **kw):
    r = api.post("/api/clients", json=client_data(**kw))
    assert r.status_code == 201, r.json
    return r.json["client"]["id"]


def new_vehicule(api, client_id=None, **kw):
    data = vehicule_data(**kw)
    if client_id:
        data["client_id"] = client_id
    r = api.post("/api/vehicules", json=data)
    assert r.status_code == 201, r.json
    return r.json["vehicule"]["id"]


@pytest.fixture()
def garage(make_garage):
    return make_garage("Garage Alpha", "alpha@example.com")


# ------------------------------------------------------------------ clients
def test_create_list_and_search_clients(garage):
    new_client(garage)
    new_client(garage, nom="Agbodjan", prenom="Léa", telephone="+229 96 11 22 33")
    r = garage.get("/api/clients")
    assert r.status_code == 200 and r.json["total"] == 2
    assert garage.get("/api/clients?q=houng").json["total"] == 1
    assert garage.get("/api/clients", query_string={"q": "96 11"}).json["total"] == 1
    assert garage.get("/api/clients", query_string={"q": "%"}).json["total"] == 0  # le joker % est saisi littéralement


def test_client_validation(garage):
    r = garage.post("/api/clients", json={"type": "particulier"})
    assert r.status_code == 422 and "nom" in r.json["details"]
    r = garage.post("/api/clients", json={"type": "entreprise", "nom": "Contact"})
    assert r.status_code == 422 and "raison_sociale" in r.json["details"]
    r = garage.post("/api/clients", json=client_data(telephone="abc"))
    assert r.status_code == 422 and "telephone" in r.json["details"]
    r = garage.post("/api/clients", json=client_data(email="pas-un-email"))
    assert r.status_code == 422 and "email" in r.json["details"]
    r = garage.post("/api/clients", json=client_data(type="inconnu"))
    assert r.status_code == 422 and "type" in r.json["details"]
    assert garage.post("/api/clients", data="pas du json").status_code == 400


def test_company_client_needs_raison_sociale_only(garage):
    r = garage.post("/api/clients", json={"type": "entreprise", "raison_sociale": "Transports Zinsou SARL"})
    assert r.status_code == 201
    assert r.json["client"]["nom_affiche"] == "Transports Zinsou SARL"


def test_update_archive_and_restore_client(garage):
    cid = new_client(garage)
    r = garage.patch(f"/api/clients/{cid}", json={"telephone": "+229 95 55 55 55", "notes": "Client fidèle\nPaie cash"})
    assert r.status_code == 200 and r.json["client"]["telephone"] == "+229 95 55 55 55"
    assert "\n" in r.json["client"]["notes"]
    # passer en entreprise sans raison sociale est refusé
    assert garage.patch(f"/api/clients/{cid}", json={"type": "entreprise"}).status_code == 422
    assert garage.post(f"/api/clients/{cid}/archive").json["client"]["actif"] is False
    assert garage.get("/api/clients").json["total"] == 0
    assert garage.get("/api/clients?statut=archives").json["total"] == 1
    assert garage.get("/api/clients?statut=tous").json["total"] == 1
    assert garage.post(f"/api/clients/{cid}/restore").json["client"]["actif"] is True
    assert garage.get("/api/clients").json["total"] == 1


def test_same_phone_gives_a_warning_not_an_error(garage):
    new_client(garage)
    r = garage.post("/api/clients", json=client_data(nom="Houngbo", prenom="Épouse"))
    assert r.status_code == 201 and r.json["avertissements"]


# ------------------------------------------------------------------ véhicules
def test_create_vehicule_with_owner(garage):
    cid = new_client(garage)
    vid = new_vehicule(garage, cid)
    r = garage.get(f"/api/vehicules/{vid}")
    assert r.status_code == 200
    assert r.json["vehicule"]["immatriculation"] == "AB 1234 RB"
    assert r.json["proprietaire"]["id"] == cid
    detail = garage.get(f"/api/clients/{cid}").json
    assert [x["id"] for x in detail["vehicules"]] == [vid]
    listing = garage.get("/api/vehicules").json
    assert listing["total"] == 1 and listing["vehicules"][0]["proprietaire"]["id"] == cid


def test_vehicule_without_owner_appears_in_list(garage):
    vid = new_vehicule(garage)
    listing = garage.get("/api/vehicules").json
    assert [x["id"] for x in listing["vehicules"]] == [vid] and listing["vehicules"][0]["proprietaire"] is None


def test_vehicule_needs_plate_or_vin_and_valid_fields(garage):
    r = garage.post("/api/vehicules", json={"marque": "Honda", "modele": "CG125"})
    assert r.status_code == 422 and "immatriculation" in r.json["details"]
    assert garage.post("/api/vehicules", json={"marque": "Honda", "modele": "CG125", "vin": "VIN12345"}).status_code == 201
    r = garage.post("/api/vehicules", json=vehicule_data(immatriculation="XY 99", annee=1800, type="avion", carburant="eau"))
    assert r.status_code == 422
    assert {"annee", "type", "carburant"} <= set(r.json["details"])
    r = garage.post("/api/vehicules", json={"modele": "X", "immatriculation": "ZZ 1"})
    assert r.status_code == 422 and "marque" in r.json["details"]


def test_plate_is_unique_whatever_the_formatting(garage):
    new_vehicule(garage)
    r = garage.post("/api/vehicules", json=vehicule_data(immatriculation="AB1234RB"))
    assert r.status_code == 409 and "immatriculation" in r.json["details"]
    r = garage.post("/api/vehicules", json=vehicule_data(immatriculation="ab-1234-rb"))
    assert r.status_code == 409


def test_vin_is_unique(garage):
    new_vehicule(garage, immatriculation="AA 1 BB", vin="VF1RFB00X56123456")
    r = garage.post("/api/vehicules", json=vehicule_data(immatriculation="CC 2 DD", vin="vf1rfb00x56123456"))
    assert r.status_code == 409 and "vin" in r.json["details"]


def test_search_vehicule_by_plate_ignores_spaces(garage):
    vid = new_vehicule(garage)
    assert [x["id"] for x in garage.get("/api/vehicules?q=ab1234").json["vehicules"]] == [vid]
    assert garage.get("/api/vehicules?q=toyota").json["total"] == 1
    assert garage.get("/api/vehicules?type=moto").json["total"] == 0


def test_mileage_cannot_decrease_unless_corrected(garage, app):
    vid = new_vehicule(garage)
    r = garage.patch(f"/api/vehicules/{vid}", json={"kilometrage_actuel": 100})
    assert r.status_code == 422 and "kilometrage_actuel" in r.json["details"]
    assert garage.patch(f"/api/vehicules/{vid}", json={"kilometrage_actuel": 125000}).status_code == 200
    r = garage.patch(f"/api/vehicules/{vid}", json={"kilometrage_actuel": 12500, "corriger_kilometrage": True})
    assert r.status_code == 200 and r.json["vehicule"]["kilometrage_actuel"] == 12500
    logs = AuditLog.query.filter_by(action="vehicule.modifie").all()
    assert any((log.details or {}).get("km_corrige") == {"avant": 125000, "apres": 12500} for log in logs)


def test_patch_plate_to_an_existing_one_is_refused(garage):
    new_vehicule(garage)
    other = new_vehicule(garage, immatriculation="CD 5678 EF")
    r = garage.patch(f"/api/vehicules/{other}", json={"immatriculation": "ab 1234 rb"})
    assert r.status_code == 409
    # garder sa propre immatriculation reste possible
    assert garage.patch(f"/api/vehicules/{other}", json={"immatriculation": "cd 5678 ef", "couleur": "Rouge"}).status_code == 200


def test_transfer_keeps_the_history(garage):
    c1, c2 = new_client(garage), new_client(garage, nom="Zinsou", telephone="+229 90 00 00 02")
    vid = new_vehicule(garage, c1)
    r = garage.post(f"/api/vehicules/{vid}/transfer", json={"client_id": c2})
    assert r.status_code == 200 and r.json["vehicule"]["proprietaire"]["id"] == c2
    detail = garage.get(f"/api/vehicules/{vid}").json
    assert detail["proprietaire"]["id"] == c2
    assert [h["client_id"] for h in detail["historique_proprietaires"]] == [c2, c1]
    assert detail["historique_proprietaires"][1]["date_fin"] is not None
    assert VehiculeProprietaire.query.filter_by(date_fin=None).count() == 1  # une seule ligne ouverte
    assert garage.get(f"/api/clients/{c1}").json["vehicules"] == []
    # même propriétaire : refusé
    assert garage.post(f"/api/vehicules/{vid}/transfer", json={"client_id": c2}).status_code == 422
    assert garage.post(f"/api/vehicules/{vid}/transfer", json={"client_id": "pas-un-uuid"}).status_code == 422


def test_cannot_use_an_archived_client_as_owner(garage):
    cid = new_client(garage)
    garage.post(f"/api/clients/{cid}/archive")
    r = garage.post("/api/vehicules", json=vehicule_data(client_id=cid))
    assert r.status_code == 422 and "client_id" in r.json["details"]


def test_archive_and_restore_vehicule(garage):
    vid = new_vehicule(garage)
    assert garage.post(f"/api/vehicules/{vid}/archive").json["vehicule"]["actif"] is False
    assert garage.get("/api/vehicules").json["total"] == 0
    assert garage.get("/api/vehicules?statut=archives").json["total"] == 1
    assert garage.post(f"/api/vehicules/{vid}/restore").json["vehicule"]["actif"] is True


# ------------------------------------------------------------------ isolation entre garages
@pytest.fixture()
def two(make_garage):
    return make_garage("Garage A", "a@example.com"), make_garage("Garage B", "b@example.com")


def test_garage_b_cannot_see_or_touch_garage_a_data(two):
    a, b = two
    cid = new_client(a)
    vid = new_vehicule(a, cid)
    assert b.get("/api/clients").json["total"] == 0
    assert b.get("/api/vehicules").json["total"] == 0
    assert b.get("/api/clients?q=houngbo").json["total"] == 0
    assert b.get("/api/vehicules?q=ab1234").json["total"] == 0
    for url in (f"/api/clients/{cid}", f"/api/vehicules/{vid}"):
        assert b.get(url).status_code == 404
    assert b.patch(f"/api/clients/{cid}", json={"nom": "Piraté"}).status_code == 404
    assert b.patch(f"/api/vehicules/{vid}", json={"couleur": "Noir"}).status_code == 404
    assert b.post(f"/api/clients/{cid}/archive").status_code == 404
    assert b.post(f"/api/vehicules/{vid}/archive").status_code == 404
    assert b.post(f"/api/vehicules/{vid}/transfer", json={"client_id": new_client(b)}).status_code == 404
    # rien n'a changé chez A
    assert a.get(f"/api/clients/{cid}").json["client"]["nom"] == "Houngbo"
    assert a.get(f"/api/vehicules/{vid}").json["vehicule"]["couleur"] is None


def test_garage_b_cannot_attach_its_vehicle_to_a_client_of_garage_a(two):
    a, b = two
    client_a = new_client(a)
    r = b.post("/api/vehicules", json=vehicule_data(client_id=client_a))
    assert r.status_code == 422 and "client_id" in r.json["details"]
    own = new_vehicule(b)
    r = b.post(f"/api/vehicules/{own}/transfer", json={"client_id": client_a})
    assert r.status_code == 422
    assert b.get("/api/vehicules").json["vehicules"][0]["proprietaire"] is None
    assert a.get(f"/api/clients/{client_a}").json["vehicules"] == []


def test_two_garages_can_use_the_same_plate_and_phone(two):
    a, b = two
    new_vehicule(a, vin="VF1RFB00X56123456")
    new_vehicule(b, vin="VF1RFB00X56123456")  # même plaque, même châssis : autre garage, aucun conflit
    new_client(a)
    r = b.post("/api/clients", json=client_data())
    assert r.status_code == 201 and r.json["avertissements"] == []  # pas d'alerte doublon inter-garages


def test_client_id_in_body_cannot_override_the_garage(two):
    a, b = two
    r = b.post("/api/clients", json=client_data(garage_id=str(uuid.uuid4())))
    assert r.status_code == 201
    assert a.get("/api/clients").json["total"] == 0 and b.get("/api/clients").json["total"] == 1


# ------------------------------------------------------------------ permissions
def login_staff(app, new_api, role, email):
    make_staff(app, "alpha@example.com", email, role)
    api = new_api()
    r = api.post("/api/auth/login", json={"email": email, "mot_de_passe": PASSWORD})
    assert r.status_code == 200, r.json
    return api


def test_roles_and_permissions(garage, app, new_api):
    cid = new_client(garage)
    vid = new_vehicule(garage, cid)
    meca = login_staff(app, new_api, "mecanicien", "meca@example.com")
    assert meca.get("/api/vehicules").status_code == 200
    assert meca.get(f"/api/vehicules/{vid}").status_code == 200
    assert meca.get("/api/clients").status_code == 403
    assert meca.post("/api/clients", json=client_data()).status_code == 403
    assert meca.post("/api/vehicules", json=vehicule_data(immatriculation="ZZ 9 ZZ")).status_code == 403
    assert meca.post(f"/api/vehicules/{vid}/archive").status_code == 403
    recep = login_staff(app, new_api, "receptionniste", "recep@example.com")
    assert recep.post("/api/clients", json=client_data(nom="Autre", telephone="+229 91 00 00 03")).status_code == 201
    assert recep.post(f"/api/vehicules/{vid}/archive").status_code == 200
    compta = login_staff(app, new_api, "comptable", "compta@example.com")
    assert compta.get("/api/clients").status_code == 200
    assert compta.post("/api/clients", json=client_data()).status_code == 403


def test_endpoints_require_authentication(new_api):
    anon = new_api()
    assert anon.get("/api/clients").status_code == 401
    assert anon.post("/api/vehicules", json=vehicule_data()).status_code == 401


# ------------------------------------------------------------------ pages et utilitaires
def test_pages_render(new_api):
    anon = new_api()
    for url in ("/clients", "/vehicules", f"/clients/{uuid.uuid4()}", f"/vehicules/{uuid.uuid4()}"):
        assert anon.get(url).status_code == 200, url
    assert anon.get("/clients/pas-un-uuid").status_code == 404


def test_validator_helpers():
    assert v.plate({"p": "ab-12 34"}, "p", {}) == ("AB-12 34", "AB1234")
    errors = {}
    assert v.plate({"p": "!"}, "p", errors) == (None, None) and "p" in errors
    assert v.vin({"x": " vf1 rfb 00 "}, "x", {}) == "VF1RFB00"
    assert v.like_pattern("50%_\\") == "%50\\%\\_\\\\%"
