"""Clients du garage : fiche, recherche, modification, archivage."""
import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy.exc import IntegrityError

from app import validators as v
from app.api._common import json_body, pagination
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import CLIENT_TYPES, Client, Vehicule, VehiculeProprietaire
from app.permissions import require_permission
from app.serializers import client_dict, vehicule_dict
from app.services.audit import audit

bp = Blueprint("clients", __name__, url_prefix="/api/clients")

_FIELDS = ("type", "nom", "prenom", "raison_sociale", "telephone", "whatsapp", "email", "adresse", "ifu", "notes")


def _get_client(client_id) -> Client:
    # Requête filtrée automatiquement par garage : le client d'un autre garage est "introuvable".
    client = db.session.scalar(sa.select(Client).where(Client.id == client_id))
    if client is None:
        raise ApiError("Client introuvable.", 404, "client_introuvable")
    return client


def _parse(data, errors, partial, existing=None):
    """Valide les champs fournis et retourne les modifications à appliquer."""
    changes = {}

    def wanted(field):
        return (not partial) or (field in data)

    if wanted("type"):
        changes["type"] = v.choice(data, "type", errors, CLIENT_TYPES, label="Le type de client") or "particulier"
    if wanted("nom"):
        changes["nom"] = v.text(data, "nom", errors, required=False, label="Le nom")
    if wanted("prenom"):
        changes["prenom"] = v.text(data, "prenom", errors, required=False, label="Le prénom")
    if wanted("raison_sociale"):
        changes["raison_sociale"] = v.text(data, "raison_sociale", errors, max_len=160, required=False,
                                           label="La raison sociale")
    if wanted("telephone"):
        changes["telephone"] = v.phone(data, "telephone", errors)
    if wanted("whatsapp"):
        changes["whatsapp"] = v.phone(data, "whatsapp", errors)
    if wanted("email"):
        changes["email"] = v.optional_email(data, "email", errors)
    if wanted("adresse"):
        changes["adresse"] = v.text(data, "adresse", errors, max_len=255, required=False, label="L'adresse")
    if wanted("ifu"):
        changes["ifu"] = v.admin_id(data, "ifu", errors, "L'IFU")
    if wanted("notes"):
        changes["notes"] = v.long_text(data, "notes", errors, label="Les notes")

    final = {f: getattr(existing, f) for f in _FIELDS} if existing is not None else {}
    final.update(changes)
    if (final.get("type") or "particulier") == "particulier":
        if not final.get("nom"):
            errors.setdefault("nom", "Le nom est obligatoire.")
    elif not final.get("raison_sociale"):
        errors.setdefault("raison_sociale", "La raison sociale est obligatoire.")
    return changes


def _commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Conflit de données, réessayez.", 409, "conflit")


@bp.get("")
@require_permission("clients.read")
def list_clients():
    page, par_page = pagination()
    statut = request.args.get("statut", "actifs")
    filters = []
    if statut == "actifs":
        filters.append(Client.actif.is_(True))
    elif statut == "archives":
        filters.append(Client.actif.is_(False))
    kind = request.args.get("type")
    if kind in CLIENT_TYPES:
        filters.append(Client.type == kind)
    q = (request.args.get("q") or "").strip()
    if q:
        pattern = v.like_pattern(q[:100])
        filters.append(sa.or_(*(col.ilike(pattern, escape="\\") for col in (
            Client.nom, Client.prenom, Client.raison_sociale, Client.telephone, Client.whatsapp, Client.email))))
    total = db.session.scalar(sa.select(sa.func.count(Client.id)).where(*filters))
    rows = db.session.scalars(
        sa.select(Client).where(*filters)
        .order_by(sa.func.lower(sa.func.coalesce(Client.raison_sociale, Client.nom, "")), Client.created_at.desc())
        .limit(par_page).offset((page - 1) * par_page)
    ).all()
    return jsonify({"clients": [client_dict(c) for c in rows], "total": total, "page": page, "par_page": par_page})


@bp.post("")
@require_permission("clients.create")
def create_client():
    data = json_body()
    errors = {}
    changes = _parse(data, errors, partial=False)
    if errors:
        raise validation_error(errors)
    client = Client(**changes)
    db.session.add(client)
    db.session.flush()
    audit("client.cree", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="client", entity_id=client.id)
    warnings = []
    if client.telephone:
        twin = db.session.scalar(sa.select(Client).where(
            Client.telephone == client.telephone, Client.id != client.id).limit(1))
        if twin:
            warnings.append(f"Un autre client a déjà ce téléphone : {twin.nom_affiche}.")
    _commit()
    return jsonify({"client": client_dict(client), "avertissements": warnings}), 201


@bp.get("/<uuid:client_id>")
@require_permission("clients.read")
def get_client(client_id):
    client = _get_client(client_id)
    vehicles = db.session.scalars(
        sa.select(Vehicule)
        .join(VehiculeProprietaire, sa.and_(VehiculeProprietaire.vehicule_id == Vehicule.id,
                                            VehiculeProprietaire.garage_id == Vehicule.garage_id))
        .where(VehiculeProprietaire.client_id == client.id, VehiculeProprietaire.date_fin.is_(None))
        .order_by(Vehicule.marque, Vehicule.modele)
    ).all()
    return jsonify({"client": client_dict(client), "vehicules": [vehicule_dict(x, client) for x in vehicles]})


@bp.patch("/<uuid:client_id>")
@require_permission("clients.update")
def update_client(client_id):
    client = _get_client(client_id)
    data = json_body()
    errors = {}
    changes = _parse(data, errors, partial=True, existing=client)
    if errors:
        raise validation_error(errors)
    for field, value in changes.items():
        setattr(client, field, value)
    audit("client.modifie", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="client", entity_id=client.id, details={"champs": sorted(changes)})
    _commit()
    return jsonify({"client": client_dict(client)})


@bp.post("/<uuid:client_id>/archive")
@require_permission("clients.archive")
def archive_client(client_id):
    client = _get_client(client_id)
    client.actif = False
    audit("client.archive", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="client", entity_id=client.id)
    _commit()
    return jsonify({"client": client_dict(client)})


@bp.post("/<uuid:client_id>/restore")
@require_permission("clients.archive")
def restore_client(client_id):
    client = _get_client(client_id)
    client.actif = True
    audit("client.restaure", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="client", entity_id=client.id)
    _commit()
    return jsonify({"client": client_dict(client)})
