from app.extensions import db
from app.models import AuditLog, Garage
from conftest import PASSWORD


def test_admin_login_and_list(admin_api, make_garage):
    make_garage("Garage A", "a@example.com")
    make_garage("Garage B", "b@example.com")
    r = admin_api.get("/api/admin/garages")
    assert r.status_code == 200 and r.json["total"] == 2
    assert {g["nom_garage"] for g in r.json["garages"]} == {"Garage A", "Garage B"}
    assert all(g["statut_abonnement"] == "essai" and g["nb_utilisateurs"] == 1 for g in r.json["garages"])
    assert admin_api.get("/api/admin/garages?q=garage b").json["total"] == 1


def test_admin_bad_login_is_generic(new_api, admin_api):
    r = new_api().post("/api/admin/auth/login", json={"email": "root@example.com", "mot_de_passe": "Faux12345"})
    assert r.status_code == 401 and r.json["code"] == "identifiants_invalides"


def test_suspend_blocks_login_and_existing_sessions_then_reactivate(admin_api, make_garage, new_api):
    user_api = make_garage("Garage A", "a@example.com")
    gid = str(Garage.query.one().id)
    r = admin_api.post(f"/api/admin/garages/{gid}/suspendre")
    assert r.status_code == 200 and r.json["garage"]["statut_abonnement"] == "suspendu"
    assert user_api.get("/api/auth/me").status_code == 401  # session existante coupée
    login = new_api().post("/api/auth/login", json={"email": "a@example.com", "mot_de_passe": PASSWORD})
    assert login.status_code == 403 and login.json["code"] == "garage_inactif"
    assert admin_api.post(f"/api/admin/garages/{gid}/activer").json["garage"]["statut_abonnement"] == "actif"
    assert new_api().post("/api/auth/login", json={"email": "a@example.com", "mot_de_passe": PASSWORD}).status_code == 200
    actions = {a.action for a in AuditLog.query.all()}
    assert {"admin.garage_suspendu", "admin.garage_active"} <= actions


def test_expired_trial_blocks_login(admin_api, make_garage, new_api):
    make_garage("Garage A", "a@example.com", login=False)
    gid = str(Garage.query.one().id)
    r = admin_api.patch(f"/api/admin/garages/{gid}/abonnement", json={"essai_fin": "2020-01-01T00:00:00+00:00"})
    assert r.status_code == 200
    login = new_api().post("/api/auth/login", json={"email": "a@example.com", "mot_de_passe": PASSWORD})
    assert login.status_code == 403 and "essai" in login.json["erreur"]
    admin_api.patch(f"/api/admin/garages/{gid}/abonnement", json={"statut_abonnement": "actif", "abonnement_fin": None})
    assert new_api().post("/api/auth/login", json={"email": "a@example.com", "mot_de_passe": PASSWORD}).status_code == 200


def test_subscription_validation_and_unknown_garage(admin_api, make_garage):
    make_garage("Garage A", "a@example.com", login=False)
    gid = str(Garage.query.one().id)
    r = admin_api.patch(f"/api/admin/garages/{gid}/abonnement", json={"statut_abonnement": "gratuit", "essai_fin": "demain"})
    assert r.status_code == 422 and {"statut_abonnement", "essai_fin"} <= set(r.json["details"])
    assert admin_api.get("/api/admin/garages/pas-un-uuid").status_code == 404
    assert admin_api.get("/api/admin/garages/00000000-0000-0000-0000-000000000000").status_code == 404
