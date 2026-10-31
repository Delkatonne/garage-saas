"""Adaptation Vercel : emails via Brevo, cron protégé, vérifications de configuration en production."""
import json
from datetime import timedelta

import pytest

from app.config import Config, get_config
from app.extensions import db
from app.models import AuthToken, Garage, RevokedToken, User, utcnow
from app.services import mailer


# ------------------------------------------------------------------ emails (API Brevo)
class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"{}"


def test_send_mail_uses_brevo_api_when_key_is_set(app, monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append((req, timeout))
        return _FakeResponse()

    monkeypatch.setitem(app.config, "BREVO_API_KEY", "cle-brevo-test")
    monkeypatch.setitem(app.config, "MAIL_DEFAULT_SENDER", "Garage SaaS <no-reply@exemple.bj>")
    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    mailer.send_mail("chef@example.com", "Sujet", "Texte", "<p>Texte</p>")

    (req, timeout), = calls
    body = json.loads(req.data)
    assert req.full_url == "https://api.brevo.com/v3/smtp/email"
    assert req.get_header("Api-key") == "cle-brevo-test"
    assert body["sender"] == {"email": "no-reply@exemple.bj", "name": "Garage SaaS"}
    assert body["to"] == [{"email": "chef@example.com"}]
    assert body["subject"] == "Sujet" and body["textContent"] == "Texte" and body["htmlContent"] == "<p>Texte</p>"
    assert timeout == 10


def test_brevo_failure_never_breaks_the_request(app, monkeypatch):
    def boom(req, timeout=None):
        raise OSError("réseau coupé")

    monkeypatch.setitem(app.config, "BREVO_API_KEY", "cle-brevo-test")
    monkeypatch.setattr(mailer.urllib.request, "urlopen", boom)
    mailer.send_mail("chef@example.com", "Sujet", "Texte")  # ne doit pas lever d'exception


# ------------------------------------------------------------------ cron
def _seed_tokens(app):
    garage = Garage(nom_garage="G", nom_chef_garage="C", email="g@example.com")
    db.session.add(garage)
    db.session.flush()
    user = User(garage_id=garage.id, email="g@example.com", nom_complet="C", password_hash="x")
    db.session.add(user)
    db.session.flush()
    past, future = utcnow() - timedelta(days=1), utcnow() + timedelta(days=1)
    db.session.add_all([
        AuthToken(garage_id=garage.id, user_id=user.id, purpose="verify_email", token_hash="a" * 64, expires_at=past),
        AuthToken(garage_id=garage.id, user_id=user.id, purpose="verify_email", token_hash="b" * 64, expires_at=future),
        RevokedToken(jti="vieux", token_type="access", expires_at=past),
        RevokedToken(jti="recent", token_type="access", expires_at=future),
    ])
    db.session.commit()


def test_cron_is_hidden_when_secret_not_configured(app, new_api):
    assert new_api().get("/api/cron/purge-tokens").status_code == 404


def test_cron_requires_the_secret(app, new_api, monkeypatch):
    monkeypatch.setitem(app.config, "CRON_SECRET", "secret-cron")
    api = new_api()
    assert api.get("/api/cron/purge-tokens").status_code == 401
    assert api.get("/api/cron/purge-tokens", headers={"Authorization": "Bearer faux"}).status_code == 401


def test_cron_purges_only_expired_tokens(app, new_api, monkeypatch):
    _seed_tokens(app)
    monkeypatch.setitem(app.config, "CRON_SECRET", "secret-cron")
    r = new_api().get("/api/cron/purge-tokens", headers={"Authorization": "Bearer secret-cron"})
    assert r.status_code == 200
    assert r.json == {"jetons_revoques": 1, "jetons_usage_unique": 1}
    assert [t.token_hash for t in db.session.scalars(db.select(AuthToken)).all()] == ["b" * 64]
    assert [t.jti for t in db.session.scalars(db.select(RevokedToken)).all()] == ["recent"]


# ------------------------------------------------------------------ configuration de production
@pytest.fixture()
def prod(monkeypatch):
    """Une configuration de production complète ; chaque test en retire un élément."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    for name, value in {
        "IS_PRODUCTION": True, "SECRET_KEY": "une-vraie-cle-secrete",
        "CLOUDINARY_URL": "cloudinary://k:s@nuage", "BREVO_API_KEY": "cle",
        "MAIL_SERVER": "", "APP_BASE_URL": "https://garage.example.com",
    }.items():
        monkeypatch.setattr(Config, name, value)
    return monkeypatch


def test_production_config_complete_is_accepted(prod):
    assert get_config() is Config


@pytest.mark.parametrize("attr, value, fragment", [
    ("SECRET_KEY", "dev-secret-change-me", "SECRET_KEY"),
    ("CLOUDINARY_URL", "", "CLOUDINARY_URL"),
    ("BREVO_API_KEY", "", "BREVO_API_KEY"),
    ("APP_BASE_URL", "http://localhost:5000", "APP_BASE_URL"),
])
def test_production_config_refuses_to_start_when_incomplete(prod, attr, value, fragment):
    prod.setattr(Config, attr, value)
    with pytest.raises(RuntimeError, match=fragment):
        get_config()


def test_production_config_refuses_without_database_url(prod):
    prod.delenv("DATABASE_URL")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_config()
