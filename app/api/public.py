"""Lien public d'un devis : le client le consulte, le télécharge et l'accepte ou le refuse, sans compte.

Sécurité : le lien contient un secret aléatoire de 256 bits (seule son empreinte SHA-256 est en base). Aucun
identifiant interne n'est renvoyé. Les routes sont limitées en fréquence et sont les seules à utiliser `unscoped()`
sur des données de garage : chaque requête est donc ramenée au seul devis désigné par le secret.
"""
import hashlib
from functools import wraps

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import validators as v
from app.api._common import json_body
from app.errors import ApiError, validation_error
from app.extensions import db, limiter
from app.models import Client, Devis, Garage, Vehicule, utcnow
from app.serializers import devis_public_dict
from app.services.audit import audit
from app.services.or_workflow import auto_status_for_devis
from app.services.pdf_devis import pdf_response
from app.tenancy import unscoped

bp = Blueprint("public", __name__, url_prefix="/api/public")


def public_view(fn):
    @wraps(fn)
    def wrapper(token, *args, **kwargs):
        with unscoped():
            if not isinstance(token, str) or not 20 <= len(token) <= 100:
                raise ApiError("Lien invalide ou expiré.", 404, "lien_invalide")
            digest = hashlib.sha256(token.encode()).hexdigest()
            devis = db.session.scalar(sa.select(Devis).where(Devis.token_public_hash == digest))
            if devis is None or devis.statut == "brouillon":
                raise ApiError("Lien invalide ou expiré.", 404, "lien_invalide")
            return fn(devis, *args, **kwargs)

    return wrapper


def _context(devis):
    garage = db.session.get(Garage, devis.garage_id)
    client = db.session.scalar(sa.select(Client).where(Client.id == devis.client_id, Client.garage_id == devis.garage_id))
    vehicule = None
    if devis.vehicule_id:
        vehicule = db.session.scalar(sa.select(Vehicule).where(Vehicule.id == devis.vehicule_id,
                                                               Vehicule.garage_id == devis.garage_id))
    return garage, client, vehicule


@bp.get("/devis/<token>")
@limiter.limit("60 per minute")
@public_view
def view_devis(devis):
    return jsonify(devis_public_dict(devis, *_context(devis)))


@bp.get("/devis/<token>/pdf")
@limiter.limit("20 per minute")
@public_view
def pdf(devis):
    return pdf_response(devis, *_context(devis))


def _require_open(devis):
    effective = devis.statut_effectif
    if effective == "expire":
        raise ApiError("Ce devis a expiré. Contactez le garage pour obtenir une nouvelle version.", 409, "devis_expire")
    if effective == "remplace":
        raise ApiError("Ce devis a été remplacé par une nouvelle version. Contactez le garage.", 409, "devis_remplace")
    if effective != "envoye":
        raise ApiError("Ce devis a déjà reçu une réponse.", 409, "statut_invalide")


@bp.post("/devis/<token>/accept")
@limiter.limit("10 per hour")
@public_view
def accept(devis):
    _require_open(devis)
    errors = {}
    nom = v.text(json_body(), "nom", errors, label="Votre nom")
    if errors:
        raise validation_error(errors)
    devis.statut, devis.accepte_le, devis.acceptation_nom, devis.acceptation_mode = "accepte", utcnow(), nom, "lien"
    devis.acceptation_ip = (request.remote_addr or "")[:45]
    audit("devis.accepte_par_client", garage_id=devis.garage_id, entity_type="devis", entity_id=devis.id,
          details={"nom": nom})
    auto_status_for_devis(devis, "devis_accepte", f"Devis {devis.numero} accepté par le client", None)
    db.session.commit()
    return jsonify({"message": "Merci ! Votre accord a bien été enregistré. Le garage va vous contacter."})


@bp.post("/devis/<token>/refuse")
@limiter.limit("10 per hour")
@public_view
def refuse(devis):
    _require_open(devis)
    errors = {}
    body = request.get_json(silent=True) if request.is_json else {}
    motif = v.text(body or {}, "motif", errors, max_len=255, required=False, label="Le motif")
    if errors:
        raise validation_error(errors)
    devis.statut, devis.refuse_le, devis.refus_motif = "refuse", utcnow(), motif
    audit("devis.refuse_par_client", garage_id=devis.garage_id, entity_type="devis", entity_id=devis.id)
    db.session.commit()
    return jsonify({"message": "Votre réponse a bien été enregistrée. Merci."})
