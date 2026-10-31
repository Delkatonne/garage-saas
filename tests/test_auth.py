import time
from datetime import timedelta

from app.extensions import db
from app.models import AuthToken, User, utcnow
from conftest import PASSWORD, png_bytes, token_from

VALID = {"nom_garage": "Garage Test", "nom_chef_garage": "Koffi", "email": "koffi@example.com",
         "mot_de_passe": PASSWORD, "confirmation_mot_de_passe": PASSWORD}


def test_register_validation_errors(new_api):
    api = new_api()
    r = api.post("/api/auth/register", json={"nom_garage": "", "email": "pas-un-email",
                                             "mot_de_passe": "court", "confirmation_mot_de_passe": "autre"})
    assert r.status_code == 422
    d = r.json["details"]
    assert {"nom_garage", "nom_chef_garage", "email", "mot_de_passe"} <= set(d)


def test_register_password_rules(new_api):
    api = new_api()
    for bad in ("1234567", "abcdefgh", "12345678", "password123"):
        r = api.post("/api/auth/register", json={**VALID, "mot_de_passe": bad, "confirmation_mot_de_passe": bad})
        assert r.status_code == 422 and "mot_de_passe" in r.json["details"], bad
    r = api.post("/api/auth/register", json={**VALID, "confirmation_mot_de_passe": "Different1"})
    assert "confirmation_mot_de_passe" in r.json["details"]


def test_register_ok_sends_verification_and_stores_hash(new_api, outbox):
    r = new_api().post("/api/auth/register", json=VALID)
    assert r.status_code == 201
    assert len(outbox) == 1 and outbox[0].recipients == ["koffi@example.com"]
    user = User.query.one()
    assert user.role == "owner" and user.password_hash.startswith("$argon2") and not user.email_verifie
    raw = token_from(outbox)
    assert AuthToken.query.one().token_hash != raw  # seul le hash est stocké


def test_register_duplicate_email(new_api):
    api = new_api()
    assert api.post("/api/auth/register", json=VALID).status_code == 201
    r = api.post("/api/auth/register", json={**VALID, "email": "KOFFI@example.com"})
    assert r.status_code == 409 and r.json["code"] == "email_deja_utilise"


def test_register_with_logo_and_bad_logos(new_api):
    import io
    api = new_api()
    form = {k: v for k, v in VALID.items()}
    r = api.post("/api/auth/register", data={**form, "logo": (io.BytesIO(b"pas une image"), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 422 and "logo" in r.json["details"]
    r = api.post("/api/auth/register", data={**form, "logo": (io.BytesIO(png_bytes()), "x.gif")},
                 content_type="multipart/form-data")
    assert r.status_code == 422
    big = io.BytesIO(b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10))
    r = api.post("/api/auth/register", data={**form, "logo": (big, "x.png")}, content_type="multipart/form-data")
    assert r.status_code == 422 and "2 Mo" in r.json["details"]["logo"]
    r = api.post("/api/auth/register", data={**form, "logo": (io.BytesIO(png_bytes()), "logo.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 201


def test_login_requires_verified_email(new_api, outbox):
    api = new_api()
    api.post("/api/auth/register", json=VALID)
    r = api.post("/api/auth/login", json={"email": VALID["email"], "mot_de_passe": PASSWORD})
    assert r.status_code == 403 and r.json["code"] == "email_non_verifie"
    # mauvais mot de passe : message générique, ne révèle pas l'état du compte
    r = api.post("/api/auth/login", json={"email": VALID["email"], "mot_de_passe": "Mauvais123"})
    assert r.status_code == 401


def test_verify_email_single_use_and_expiry(new_api, outbox):
    api = new_api()
    api.post("/api/auth/register", json=VALID)
    raw = token_from(outbox)
    assert api.post("/api/auth/verify-email", json={"token": raw}).status_code == 200
    assert api.post("/api/auth/verify-email", json={"token": raw}).status_code == 400
    assert api.post("/api/auth/verify-email", json={"token": "n-importe-quoi"}).status_code == 400
    api.post("/api/auth/resend-verification", json={"email": VALID["email"]})
    assert len(outbox) == 1  # déjà confirmé : aucun nouvel email


def test_verify_email_expired(new_api, outbox):
    api = new_api()
    api.post("/api/auth/register", json=VALID)
    tok = AuthToken.query.one()
    tok.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert api.post("/api/auth/verify-email", json={"token": token_from(outbox)}).status_code == 400


def test_login_ok_sets_httponly_cookies_and_me(make_garage):
    api = make_garage()
    cookie = api.c.get_cookie("access_token_cookie")
    assert cookie is not None and cookie.http_only
    r = api.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json["garage"]["nom_garage"] == "Garage Alpha" and r.json["utilisateur"]["role"] == "owner"
    assert r.json["garage"]["devise"] == "XOF" and r.json["garage"]["devise_decimales"] == 0
    assert "password_hash" not in r.get_data(as_text=True)


def test_login_generic_errors_identical(new_api, make_garage):
    make_garage()
    api = new_api()
    a = api.post("/api/auth/login", json={"email": "inconnu@example.com", "mot_de_passe": "Whatever123"})
    b = api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": "Whatever123"})
    assert a.status_code == b.status_code == 401 and a.json == b.json


def test_lockout_after_failed_attempts(new_api, make_garage):
    make_garage(login=False)
    api = new_api()
    for _ in range(5):
        assert api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": "Faux12345"}).status_code == 401
    # même avec le BON mot de passe, le compte est verrouillé 15 min (message identique)
    r = api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": PASSWORD})
    assert r.status_code == 401 and r.json["code"] == "identifiants_invalides"
    user = User.query.one()
    user.locked_until = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": PASSWORD}).status_code == 200


def test_csrf_required_for_cookie_auth(make_garage):
    api = make_garage()
    r = api.c.patch("/api/garage/profile", json={"ville": "Cotonou"})  # sans en-tête CSRF
    assert r.status_code == 401
    assert api.patch("/api/garage/profile", json={"ville": "Cotonou"}).status_code == 200


def test_protected_routes_need_auth(new_api):
    api = new_api()
    assert api.get("/api/auth/me").status_code == 401
    assert api.get("/api/garage/profile").status_code == 401


def test_forgot_password_generic_and_reset_flow(new_api, make_garage, outbox):
    make_garage(login=False)
    api = new_api()
    sent = len(outbox)
    r1 = api.post("/api/auth/forgot-password", json={"email": "inconnu@example.com"})
    assert len(outbox) == sent  # aucun email pour un compte inexistant
    r2 = api.post("/api/auth/forgot-password", json={"email": "alpha@example.com"})
    assert r1.status_code == r2.status_code == 200 and r1.json == r2.json
    assert len(outbox) == sent + 1
    raw = token_from(outbox)
    assert api.post("/api/auth/reset-password", json={"token": raw, "mot_de_passe": "weak", "confirmation_mot_de_passe": "weak"}).status_code == 422
    new_pwd = "NouveauMdp2026"
    assert api.post("/api/auth/reset-password", json={"token": raw, "mot_de_passe": new_pwd, "confirmation_mot_de_passe": new_pwd}).status_code == 200
    # usage unique
    assert api.post("/api/auth/reset-password", json={"token": raw, "mot_de_passe": "Autre2026xx", "confirmation_mot_de_passe": "Autre2026xx"}).status_code == 400
    assert api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": PASSWORD}).status_code == 401
    assert api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": new_pwd}).status_code == 200


def test_reset_link_expires_after_30_minutes(new_api, make_garage, outbox):
    make_garage(login=False)
    api = new_api()
    api.post("/api/auth/forgot-password", json={"email": "alpha@example.com"})
    tok = AuthToken.query.filter_by(purpose="reset_password").one()
    assert timedelta(minutes=29) < (tok.expires_at.replace(tzinfo=None) - utcnow().replace(tzinfo=None)) <= timedelta(minutes=30)
    tok.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    r = api.post("/api/auth/reset-password", json={"token": token_from(outbox), "mot_de_passe": "Nouveau2026x", "confirmation_mot_de_passe": "Nouveau2026x"})
    assert r.status_code == 400


def test_new_reset_request_invalidates_previous_link(new_api, make_garage, outbox):
    make_garage(login=False)
    api = new_api()
    api.post("/api/auth/forgot-password", json={"email": "alpha@example.com"})
    first = token_from(outbox)
    api.post("/api/auth/forgot-password", json={"email": "alpha@example.com"})
    r = api.post("/api/auth/reset-password", json={"token": first, "mot_de_passe": "Nouveau2026x", "confirmation_mot_de_passe": "Nouveau2026x"})
    assert r.status_code == 400


def test_password_reset_invalidates_existing_sessions(new_api, make_garage, outbox):
    old = make_garage()
    old_access = old.c.get_cookie("access_token_cookie").value
    time.sleep(1.1)
    api = new_api()
    api.post("/api/auth/forgot-password", json={"email": "alpha@example.com"})
    api.post("/api/auth/reset-password", json={"token": token_from(outbox), "mot_de_passe": "Nouveau2026x", "confirmation_mot_de_passe": "Nouveau2026x"})
    r = new_api().get("/api/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert r.status_code == 401


def test_change_password(make_garage, new_api):
    api = make_garage()
    bad = api.post("/api/auth/change-password", json={"ancien_mot_de_passe": "Faux12345", "mot_de_passe": "Nouveau2026x", "confirmation_mot_de_passe": "Nouveau2026x"})
    assert bad.status_code == 400
    same = api.post("/api/auth/change-password", json={"ancien_mot_de_passe": PASSWORD, "mot_de_passe": PASSWORD, "confirmation_mot_de_passe": PASSWORD})
    assert same.status_code == 422
    ok = api.post("/api/auth/change-password", json={"ancien_mot_de_passe": PASSWORD, "mot_de_passe": "Nouveau2026x", "confirmation_mot_de_passe": "Nouveau2026x"})
    assert ok.status_code == 200
    assert api.get("/api/auth/me").status_code == 200  # session rouverte
    assert new_api().post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": "Nouveau2026x"}).status_code == 200


def test_refresh_rotation_and_reuse_detection(make_garage, new_api):
    api = make_garage()
    old_refresh = api.c.get_cookie("refresh_token_cookie", path="/api/auth/").value
    csrf = api.c.get_cookie("csrf_refresh_token").value
    r = api.c.post("/api/auth/refresh", headers={"X-CSRF-TOKEN": csrf})
    assert r.status_code == 200
    reuse = new_api().post("/api/auth/refresh", headers={"Authorization": f"Bearer {old_refresh}"})
    assert reuse.status_code == 401 and reuse.json["code"] == "token_revoque"


def test_logout_revokes_tokens(make_garage, new_api):
    api = make_garage()
    access = api.c.get_cookie("access_token_cookie").value
    assert api.post("/api/auth/logout").status_code == 200
    assert api.get("/api/auth/me").status_code == 401
    assert new_api().get("/api/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401


def test_pages_and_pwa_served(new_api):
    api = new_api()
    for path in ("/", "/inscription", "/connexion", "/mot-de-passe-oublie", "/tableau-de-bord", "/profil",
                 "/manifest.webmanifest", "/sw.js", "/healthz"):
        assert api.get(path).status_code == 200, path
    r = api.get("/connexion")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"] and "<script>" not in r.get_data(as_text=True)
    assert api.get("/api/inconnu").json["code"] == "http_404"
