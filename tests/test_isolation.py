"""Preuves automatisées : un garage A ne peut ni lire ni modifier les données d'un garage B."""
import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models import AuditLog, Garage, User
from app.tenancy import TenantViolation, set_garage, unscoped
from conftest import TenantThing, make_staff


@pytest.fixture()
def two_garages(make_garage):
    a = make_garage("Garage A", "a@example.com")
    b = make_garage("Garage B", "b@example.com")
    return a, b


def test_list_and_read_are_isolated(two_garages):
    a, b = two_garages
    ida = a.post("/api/_test/things", json={"nom": "chose-A"}).json["id"]
    idb = b.post("/api/_test/things", json={"nom": "chose-B"}).json["id"]
    assert a.get("/api/_test/things").json == ["chose-A"]
    assert b.get("/api/_test/things").json == ["chose-B"]
    assert a.get(f"/api/_test/things/{ida}").status_code == 200
    # A tente de lire l'objet de B par son identifiant exact -> introuvable
    assert a.get(f"/api/_test/things/{idb}").status_code == 404
    assert b.get(f"/api/_test/things/{ida}").status_code == 404


def test_update_and_delete_cross_garage_are_blocked(two_garages):
    a, b = two_garages
    idb = b.post("/api/_test/things", json={"nom": "chose-B"}).json["id"]
    assert a.patch(f"/api/_test/things/{idb}", json={"nom": "piraté"}).status_code == 404
    assert a.delete(f"/api/_test/things/{idb}").json["supprimes"] == 0
    assert b.get(f"/api/_test/things/{idb}").json["nom"] == "chose-B"
    assert b.delete(f"/api/_test/things/{idb}").json["supprimes"] == 1


def test_client_cannot_choose_garage_id(two_garages):
    a, b = two_garages
    gid_b = str(Garage.query.filter_by(email="b@example.com").one().id)
    a.post("/api/_test/things", json={"nom": "x", "garage_id": gid_b})
    assert b.get("/api/_test/things").json == []
    row = TenantThing.query.one()
    assert str(row.garage_id) == str(Garage.query.filter_by(email="a@example.com").one().id)


def test_profile_endpoints_ignore_garage_id_in_payload(two_garages):
    a, b = two_garages
    gid_b = str(Garage.query.filter_by(email="b@example.com").one().id)
    r = a.patch("/api/garage/profile", json={"ville": "Porto-Novo", "garage_id": gid_b, "id": gid_b, "email": "x@y.z"})
    assert r.status_code == 200 and r.json["garage"]["email"] == "a@example.com"
    assert b.get("/api/garage/profile").json["garage"]["ville"] is None
    assert a.get(f"/api/garage/profile?garage_id={gid_b}").json["garage"]["nom_garage"] == "Garage A"


def test_forged_jwt_garage_claim_is_rejected(two_garages, new_api, app):
    a, b = two_garages
    user_a = User.query.filter_by(email="a@example.com").one()
    gid_b = str(Garage.query.filter_by(email="b@example.com").one().id)
    forged = create_access_token(f"u:{user_a.id}", additional_claims={"garage_id": gid_b, "scope": "garage"})
    r = new_api().get("/api/garage/profile", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_orm_level_isolation_users_and_audit(app, two_garages):
    ga = Garage.query.filter_by(email="a@example.com").one()
    gb = Garage.query.filter_by(email="b@example.com").one()
    with app.test_request_context():
        set_garage(ga.id)
        assert {u.email for u in User.query.all()} == {"a@example.com"}
        assert all(a.garage_id == ga.id for a in AuditLog.query.all()) and AuditLog.query.count() > 0
    with app.test_request_context():
        set_garage(gb.id)
        assert {u.email for u in User.query.all()} == {"b@example.com"}


def test_deny_by_default_without_garage_context(app, two_garages):
    with app.test_request_context():  # requête HTTP sans utilisateur authentifié
        assert User.query.count() == 0 and TenantThing.query.count() == 0
        with unscoped():
            assert User.query.count() == 2


def test_writes_without_context_or_in_other_garage_are_refused(app, two_garages):
    ga = Garage.query.filter_by(email="a@example.com").one()
    gb = Garage.query.filter_by(email="b@example.com").one()
    with app.test_request_context():
        db.session.add(TenantThing(nom="orpheline", garage_id=ga.id))
        with pytest.raises(TenantViolation):
            db.session.flush()
        db.session.rollback()
    with app.test_request_context():
        set_garage(ga.id)
        db.session.add(TenantThing(nom="chez B", garage_id=gb.id))
        with pytest.raises(TenantViolation):
            db.session.flush()
        db.session.rollback()
        t = TenantThing(nom="ok")  # garage_id posé automatiquement
        db.session.add(t)
        db.session.flush()
        assert t.garage_id == ga.id
        t.garage_id = gb.id  # tentative de "déménager" un objet
        with pytest.raises(TenantViolation):
            db.session.flush()
        db.session.rollback()


def test_all_business_tables_carry_garage_id(app):
    """Garde-fou : toute table (hors tables techniques/globales) doit avoir garage_id."""
    global_tables = {"garages", "platform_admins", "revoked_tokens"}
    for table in db.metadata.sorted_tables:
        if table.name not in global_tables:
            assert "garage_id" in table.c, f"{table.name} n'a pas de garage_id"
            assert not table.c.garage_id.nullable


def test_garage_user_cannot_use_admin_api(two_garages):
    a, _ = two_garages
    assert a.get("/api/admin/garages").status_code == 403
    assert a.post("/api/admin/garages/xxx/suspendre").status_code == 403


def test_staff_sees_only_own_garage(app, two_garages, new_api):
    make_staff(app, "a@example.com", "meca@example.com")
    api = new_api()
    assert api.post("/api/auth/login", json={"email": "meca@example.com", "mot_de_passe": "Garage2026x"}).status_code == 200
    api.post("/api/_test/things", json={"nom": "meca-A"})
    assert api.get("/api/_test/things").json == ["meca-A"]
    assert two_garages[1].get("/api/_test/things").json == []
