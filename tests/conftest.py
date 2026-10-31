import io
import re
import uuid

import pytest
from flask import Blueprint, jsonify, request
from PIL import Image

from app import create_app
from app.config import TestConfig
from app.extensions import db, mail
from app.models import Garage, PlatformAdmin, TenantMixin, User
from app.models.base import UUIDPk
from app.permissions import garage_user_required
from app.security import hash_password

PASSWORD = "Garage2026x"


# --- Modèle et routes de test : une ressource "métier" quelconque filtrée par garage_id ---
class TenantThing(UUIDPk, TenantMixin, db.Model):
    __tablename__ = "test_things"
    nom = db.Column(db.String(50), nullable=False)


things_bp = Blueprint("things", __name__, url_prefix="/api/_test/things")


@things_bp.post("")
@garage_user_required
def create_thing():
    # Le client peut tenter d'imposer un garage_id : il doit être ignoré.
    t = TenantThing(nom=(request.get_json() or {}).get("nom", "x"), garage_id=None)
    db.session.add(t)
    db.session.commit()
    return jsonify({"id": str(t.id)}), 201


@things_bp.get("")
@garage_user_required
def list_things():
    return jsonify([t.nom for t in db.session.scalars(db.select(TenantThing)).all()])


@things_bp.get("/<tid>")
@garage_user_required
def get_thing(tid):
    t = db.session.get(TenantThing, uuid.UUID(tid))  # session.get passe aussi par le filtre
    if not t:
        return jsonify({"erreur": "introuvable"}), 404
    return jsonify({"nom": t.nom})


@things_bp.patch("/<tid>")
@garage_user_required
def patch_thing(tid):
    t = db.session.scalar(db.select(TenantThing).where(TenantThing.id == uuid.UUID(tid)))
    if not t:
        return jsonify({"erreur": "introuvable"}), 404
    t.nom = request.get_json()["nom"]
    db.session.commit()
    return jsonify({"ok": True})


@things_bp.delete("/<tid>")
@garage_user_required
def delete_thing(tid):
    n = db.session.execute(db.delete(TenantThing).where(TenantThing.id == uuid.UUID(tid))).rowcount
    db.session.commit()
    return jsonify({"supprimes": n})


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    app.register_blueprint(things_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def outbox(app):
    with mail.record_messages() as box:
        yield box


class Api:
    """Client de test qui envoie automatiquement l'en-tête CSRF (comme le fait le JS)."""

    def __init__(self, client):
        self.c = client

    def _h(self, extra=None):
        h = dict(extra or {})
        ck = self.c.get_cookie("csrf_access_token")
        if ck:
            h.setdefault("X-CSRF-TOKEN", ck.value)
        return h

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


@pytest.fixture()
def new_api(app):
    return lambda: Api(app.test_client())


def token_from(outbox, index=-1):
    m = re.search(r"token=([\w\-]+)", outbox[index].body)
    assert m, outbox[index].body
    return m.group(1)


@pytest.fixture()
def make_garage(app, new_api, outbox):
    """Inscrit un garage, confirme l'email et retourne un client connecté."""

    def _make(nom="Garage Alpha", email="alpha@example.com", password=PASSWORD, login=True):
        api = new_api()
        r = api.post("/api/auth/register", json={
            "nom_garage": nom, "nom_chef_garage": "Chef " + nom, "email": email,
            "mot_de_passe": password, "confirmation_mot_de_passe": password})
        assert r.status_code == 201, r.json
        r = api.post("/api/auth/verify-email", json={"token": token_from(outbox)})
        assert r.status_code == 200, r.json
        if login:
            r = api.post("/api/auth/login", json={"email": email, "mot_de_passe": password})
            assert r.status_code == 200, r.json
        return api

    return _make


def make_staff(app, garage_email, email, role="mecanicien", password=PASSWORD):
    garage = Garage.query.filter_by(email=garage_email).one()
    u = User(garage_id=garage.id, email=email, nom_complet="Employé", role=role,
             password_hash=hash_password(password), email_verifie=True)
    db.session.add(u)
    db.session.commit()
    return u


def png_bytes(size=(64, 64), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, "#336699").save(buf, fmt)
    return buf.getvalue()


@pytest.fixture()
def admin_api(app, new_api):
    db.session.add(PlatformAdmin(email="root@example.com", nom="Root", password_hash=hash_password(PASSWORD)))
    db.session.commit()
    api = new_api()
    r = api.post("/api/admin/auth/login", json={"email": "root@example.com", "mot_de_passe": PASSWORD})
    assert r.status_code == 200, r.json
    return api
