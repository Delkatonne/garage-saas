"""Back-office de la plateforme (super-admin) : liste, activation/suspension, abonnements."""
import uuid

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, current_user, set_access_cookies
from datetime import datetime

from app import validators as v
from app.errors import ApiError, validation_error
from app.extensions import db, limiter
from app.models import SUBSCRIPTION_STATUSES, Garage, User
from app.permissions import platform_admin_required
from app.serializers import garage_dict
from app.services import auth_service as svc
from app.services.audit import audit
from app.models import as_utc

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _get_garage(garage_id) -> Garage:
    try:
        garage = db.session.get(Garage, uuid.UUID(str(garage_id)))
    except ValueError:
        garage = None
    if not garage:
        raise ApiError("Garage introuvable.", 404, "introuvable")
    return garage


@bp.post("/auth/login")
@limiter.limit("5 per minute")
def admin_login():
    data = request.get_json(silent=True) or {}
    email, pwd = data.get("email"), data.get("mot_de_passe")
    if not isinstance(email, str) or not isinstance(pwd, str):
        raise ApiError(svc.GENERIC_LOGIN_ERROR, 401, "identifiants_invalides")
    admin = svc.authenticate_admin(email.strip().lower(), pwd)
    resp = jsonify({"admin": {"id": str(admin.id), "nom": admin.nom, "email": admin.email}})
    # Pas de refresh token pour le back-office : session courte, reconnexion demandée.
    set_access_cookies(resp, create_access_token(f"a:{admin.id}", additional_claims={"scope": "platform"}))
    return resp


@bp.get("/garages")
@platform_admin_required
def list_garages():
    q = sa.select(Garage).order_by(Garage.created_at.desc())
    if statut := request.args.get("statut"):
        q = q.where(Garage.statut_abonnement == statut)
    if search := (request.args.get("q") or "").strip():
        like = f"%{search.lower()}%"
        q = q.where(sa.or_(sa.func.lower(Garage.nom_garage).like(like), sa.func.lower(Garage.email).like(like)))
    page = max(request.args.get("page", 1, type=int), 1)
    size = min(max(request.args.get("taille", 25, type=int), 1), 100)
    rows = db.session.scalars(q.limit(size).offset((page - 1) * size)).all()
    total = db.session.scalar(sa.select(sa.func.count()).select_from(q.order_by(None).subquery()))
    counts = dict(db.session.execute(
        sa.select(User.garage_id, sa.func.count()).where(User.garage_id.in_([g.id for g in rows])).group_by(User.garage_id)
    ).all()) if rows else {}
    return jsonify({"total": total, "page": page,
                    "garages": [{**garage_dict(g), "nb_utilisateurs": counts.get(g.id, 0)} for g in rows]})


@bp.get("/garages/<garage_id>")
@platform_admin_required
def get_garage(garage_id):
    return jsonify({"garage": garage_dict(_get_garage(garage_id))})


def _set_active(garage_id, active: bool):
    garage = _get_garage(garage_id)
    garage.actif = active
    if not active:
        garage.statut_abonnement = "suspendu"
    elif garage.statut_abonnement == "suspendu":
        garage.statut_abonnement = "actif"
    audit("admin.garage_active" if active else "admin.garage_suspendu", garage_id=garage.id,
          entity_type="garage", entity_id=garage.id, details={"admin": str(current_user.id)})
    db.session.commit()
    return jsonify({"garage": garage_dict(garage)})


@bp.post("/garages/<garage_id>/suspendre")
@platform_admin_required
def suspend(garage_id):
    return _set_active(garage_id, False)


@bp.post("/garages/<garage_id>/activer")
@platform_admin_required
def activate(garage_id):
    return _set_active(garage_id, True)


@bp.patch("/garages/<garage_id>/abonnement")
@platform_admin_required
def update_subscription(garage_id):
    data, errors = request.get_json(silent=True) or {}, {}
    garage = _get_garage(garage_id)
    if "statut_abonnement" in data:
        if data["statut_abonnement"] not in SUBSCRIPTION_STATUSES:
            errors["statut_abonnement"] = f"Valeurs possibles : {', '.join(SUBSCRIPTION_STATUSES)}."
        else:
            garage.statut_abonnement = data["statut_abonnement"]
            garage.actif = data["statut_abonnement"] != "suspendu"
    for field in ("essai_fin", "abonnement_fin"):
        if field in data:
            try:
                value = None if data[field] is None else as_utc(datetime.fromisoformat(data[field]))
                setattr(garage, field, value)
            except (TypeError, ValueError):
                errors[field] = "Date ISO 8601 attendue (ex. 2027-01-31T00:00:00+00:00)."
    if errors:
        db.session.rollback()
        raise validation_error(errors)
    audit("admin.abonnement_modifie", garage_id=garage.id, entity_type="garage", entity_id=garage.id,
          details={"admin": str(current_user.id), "champs": sorted(k for k in data if k in ("statut_abonnement", "essai_fin", "abonnement_fin"))})
    db.session.commit()
    return jsonify({"garage": garage_dict(garage)})
