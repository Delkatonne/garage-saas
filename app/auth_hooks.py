"""Callbacks Flask-JWT-Extended : résolution de l'identité et pose du contexte garage.

Le `garage_id` utilisé pour filtrer les données vient de la BASE DE DONNÉES (utilisateur
résolu depuis le JWT), recoupé avec la claim du jeton. Il n'est jamais lu dans la requête.
"""
import math
import uuid

import sqlalchemy as sa
from flask import jsonify

from .extensions import db, jwt
from .models import Garage, PlatformAdmin, RevokedToken, User, as_utc
from .tenancy import set_garage, unscoped


def _err(message, code, status=401):
    return jsonify({"erreur": message, "code": code}), status


def _issued_before_password_change(payload, changed_at) -> bool:
    if changed_at is None:
        return False
    return payload.get("iat", 0) < math.floor(as_utc(changed_at).timestamp())


@jwt.user_lookup_loader
def load_identity(_header, payload):
    kind, _, raw_id = str(payload.get("sub", "")).partition(":")
    try:
        ident = uuid.UUID(raw_id)
    except ValueError:
        return None
    with unscoped():
        if kind == "u":
            user = db.session.get(User, ident)
            if not user or not user.actif or not user.email_verifie:
                return None
            if str(user.garage_id) != payload.get("garage_id"):
                return None
            garage = db.session.get(Garage, user.garage_id)
            if not garage or not garage.acces_autorise:
                return None
            if _issued_before_password_change(payload, user.password_changed_at):
                return None
            set_garage(user.garage_id)
            return user
        if kind == "a" and payload.get("scope") == "platform":
            admin = db.session.get(PlatformAdmin, ident)
            if not admin or not admin.actif or _issued_before_password_change(payload, admin.password_changed_at):
                return None
            return admin
    return None


@jwt.token_in_blocklist_loader
def is_revoked(_header, payload):
    with unscoped():
        return db.session.scalar(sa.select(RevokedToken.id).where(RevokedToken.jti == payload["jti"])) is not None


@jwt.expired_token_loader
def _expired(_h, _p):
    return _err("Session expirée.", "token_expire")


@jwt.invalid_token_loader
def _invalid(_reason):
    return _err("Session invalide.", "token_invalide")


@jwt.unauthorized_loader
def _missing(_reason):
    return _err("Authentification requise.", "non_authentifie")


@jwt.revoked_token_loader
def _revoked(_h, _p):
    return _err("Session révoquée, reconnectez-vous.", "token_revoque")


@jwt.user_lookup_error_loader
def _lookup_error(_h, _p):
    return _err("Compte indisponible ou session invalide.", "compte_indisponible")
