"""Confirmation de l'email désactivée (réglage REQUIRE_EMAIL_VERIFICATION=false, valeur par défaut en production)."""
import pytest

from app.extensions import db
from app.models import AuthToken, Garage, User
from conftest import PASSWORD

VALID = {"nom_garage": "Garage Libre", "nom_chef_garage": "Afi", "email": "afi@example.com",
         "mot_de_passe": PASSWORD, "confirmation_mot_de_passe": PASSWORD}


@pytest.fixture()
def sans_confirmation(app):
    app.config["REQUIRE_EMAIL_VERIFICATION"] = False
    yield
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True


def test_register_then_login_without_email_confirmation(sans_confirmation, new_api, outbox):
    api = new_api()
    r = api.post("/api/auth/register", json=VALID)
    assert r.status_code == 201 and r.json["redirect"] == "/connexion"
    assert outbox == []  # aucun email de confirmation
    assert AuthToken.query.count() == 0
    assert User.query.one().email_verifie and Garage.query.one().email_verifie
    r = api.post("/api/auth/login", json={"email": VALID["email"], "mot_de_passe": PASSWORD})
    assert r.status_code == 200


def test_old_unverified_account_can_log_in_and_is_regularised(sans_confirmation, new_api, app):
    api = new_api()
    api.post("/api/auth/register", json=VALID)
    user, garage = User.query.one(), Garage.query.one()
    user.email_verifie = garage.email_verifie = False  # compte créé avant le changement
    db.session.commit()
    r = api.post("/api/auth/login", json={"email": VALID["email"], "mot_de_passe": PASSWORD})
    assert r.status_code == 200
    assert User.query.one().email_verifie and Garage.query.one().email_verifie


def test_password_reset_still_works_without_confirmation(sans_confirmation, new_api, outbox):
    api = new_api()
    api.post("/api/auth/register", json=VALID)
    api.post("/api/auth/forgot-password", json={"email": VALID["email"]})
    assert len(outbox) == 1 and "reinitialiser-mot-de-passe" in outbox[0].body
