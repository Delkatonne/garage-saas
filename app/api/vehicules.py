"""Véhicules du garage (voitures, motos, scooters, quads) et historique des propriétaires."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy.exc import IntegrityError

from app import validators as v
from app.api._common import json_body, pagination
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import CARBURANTS, VEHICULE_TYPES, Client, Vehicule, VehiculeProprietaire
from app.permissions import require_permission
from app.serializers import client_dict, vehicule_dict
from app.services.audit import audit

bp = Blueprint("vehicules", __name__, url_prefix="/api/vehicules")

_FIELDS = ("type", "marque", "modele", "version", "immatriculation", "immatriculation_cle", "vin", "annee",
           "couleur", "carburant", "cylindree_cc", "kilometrage_actuel", "notes")


def _now():
    return datetime.now(timezone.utc)


def _get_vehicule(vehicule_id) -> Vehicule:
    vehicule = db.session.scalar(sa.select(Vehicule).where(Vehicule.id == vehicule_id))
    if vehicule is None:
        raise ApiError("Véhicule introuvable.", 404, "vehicule_introuvable")
    return vehicule


def _current_owner(vehicule_id):
    """(ligne de propriété ouverte, client) ou (None, None)."""
    row = db.session.execute(
        sa.select(VehiculeProprietaire, Client)
        .join(Client, sa.and_(Client.id == VehiculeProprietaire.client_id,
                              Client.garage_id == VehiculeProprietaire.garage_id))
        .where(VehiculeProprietaire.vehicule_id == vehicule_id, VehiculeProprietaire.date_fin.is_(None))
    ).first()
    return (row[0], row[1]) if row else (None, None)


def _client_from(value, errors, field="client_id"):
    """Retourne le client (actif) du garage courant désigné par `value`, ou None avec une erreur."""
    try:
        cid = uuid.UUID(str(value))
    except (ValueError, TypeError):
        errors[field] = "Client invalide."
        return None
    client = db.session.scalar(sa.select(Client).where(Client.id == cid))  # filtré par garage
    if client is None:
        errors[field] = "Client introuvable."
    elif not client.actif:
        errors[field] = "Ce client est archivé."
    else:
        return client
    return None


def _commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Conflit de données (immatriculation ou châssis déjà utilisé ?). Réessayez.", 409, "conflit")


def _parse(data, errors, partial, existing=None):
    changes = {}

    def wanted(field):
        return (not partial) or (field in data)

    if wanted("type"):
        changes["type"] = v.choice(data, "type", errors, VEHICULE_TYPES, label="Le type de véhicule") or "voiture"
    if wanted("marque"):
        changes["marque"] = v.text(data, "marque", errors, max_len=80, label="La marque")
    if wanted("modele"):
        changes["modele"] = v.text(data, "modele", errors, max_len=80, label="Le modèle")
    if wanted("version"):
        changes["version"] = v.text(data, "version", errors, max_len=80, required=False, label="La version")
    if wanted("immatriculation"):
        changes["immatriculation"], changes["immatriculation_cle"] = v.plate(data, "immatriculation", errors)
    if wanted("vin"):
        changes["vin"] = v.vin(data, "vin", errors)
    if wanted("annee"):
        changes["annee"] = v.integer(data, "annee", errors, label="L'année", minimum=1900,
                                     maximum=datetime.now().year + 1)
    if wanted("couleur"):
        changes["couleur"] = v.text(data, "couleur", errors, max_len=40, required=False, label="La couleur")
    if wanted("carburant"):
        changes["carburant"] = v.choice(data, "carburant", errors, CARBURANTS, label="Le carburant")
    if wanted("cylindree_cc"):
        changes["cylindree_cc"] = v.integer(data, "cylindree_cc", errors, label="La cylindrée", minimum=1,
                                            maximum=20000)
    if wanted("notes"):
        changes["notes"] = v.long_text(data, "notes", errors, label="Les notes")
    if wanted("kilometrage_actuel"):
        km = v.integer(data, "kilometrage_actuel", errors, label="Le kilométrage", minimum=0, maximum=9_999_999)
        old = existing.kilometrage_actuel if existing is not None else None
        if km is not None and old is not None and km < old and not data.get("corriger_kilometrage"):
            errors["kilometrage_actuel"] = (f"Le kilométrage ne peut pas diminuer (actuel : {old} km). "
                                            "Cochez « corriger une erreur de saisie » si besoin.")
        changes["kilometrage_actuel"] = km

    final = {f: getattr(existing, f) for f in _FIELDS} if existing is not None else {}
    final.update(changes)
    if not final.get("immatriculation") and not final.get("vin"):
        errors.setdefault("immatriculation", "Indiquez l'immatriculation ou le numéro de châssis (VIN).")
    return changes


def _check_unique(changes, exclude_id=None):
    """Messages d'erreur clairs avant l'écriture (la base garantit aussi l'unicité)."""
    errors = {}
    checks = (("immatriculation_cle", "immatriculation", "Cette immatriculation existe déjà dans votre garage"),
              ("vin", "vin", "Ce numéro de châssis existe déjà dans votre garage"))
    for column, field, message in checks:
        value = changes.get(column)
        if value:
            stmt = sa.select(Vehicule).where(getattr(Vehicule, column) == value)
            if exclude_id:
                stmt = stmt.where(Vehicule.id != exclude_id)
            twin = db.session.scalar(stmt.limit(1))
            if twin:
                suffix = " (véhicule archivé)." if not twin.actif else "."
                errors[field] = message + suffix
    if errors:
        raise ApiError("Ce véhicule existe déjà.", 409, "vehicule_existe", errors)


@bp.get("")
@require_permission("vehicules.read")
def list_vehicules():
    page, par_page = pagination()
    statut = request.args.get("statut", "actifs")
    filters = []
    if statut == "actifs":
        filters.append(Vehicule.actif.is_(True))
    elif statut == "archives":
        filters.append(Vehicule.actif.is_(False))
    kind = request.args.get("type")
    if kind in VEHICULE_TYPES:
        filters.append(Vehicule.type == kind)
    q = (request.args.get("q") or "").strip()
    if q:
        pattern = v.like_pattern(q[:100])
        key = "".join(ch for ch in q.upper() if ch.isalnum())
        cols = [Vehicule.marque, Vehicule.modele, Vehicule.immatriculation, Vehicule.vin, Vehicule.couleur]
        conds = [c.ilike(pattern, escape="\\") for c in cols]
        if key:
            conds.append(Vehicule.immatriculation_cle.like(f"%{key}%"))  # "ab1234" retrouve "AB 1234 RB"
        filters.append(sa.or_(*conds))
    client_id = request.args.get("client_id")
    if client_id:
        try:
            cid = uuid.UUID(client_id)
        except ValueError:
            raise ApiError("Client invalide.", 422, "validation_echouee", {"client_id": "Client invalide."})
        filters.append(Vehicule.id.in_(
            sa.select(VehiculeProprietaire.vehicule_id).where(
                VehiculeProprietaire.client_id == cid, VehiculeProprietaire.date_fin.is_(None),
                VehiculeProprietaire.garage_id == Vehicule.garage_id)))
    total = db.session.scalar(sa.select(sa.func.count(Vehicule.id)).where(*filters))
    vehicles = db.session.scalars(
        sa.select(Vehicule).where(*filters)
        .order_by(sa.func.lower(Vehicule.marque), sa.func.lower(Vehicule.modele), Vehicule.created_at.desc())
        .limit(par_page).offset((page - 1) * par_page)
    ).all()
    owners = {}
    if vehicles:  # 2e requête (jointure interne) : évite qu'un filtre de garage transforme une jointure externe
        for vehicule_id, client in db.session.execute(
            sa.select(VehiculeProprietaire.vehicule_id, Client)
            .join(Client, sa.and_(Client.id == VehiculeProprietaire.client_id,
                                  Client.garage_id == VehiculeProprietaire.garage_id))
            .where(VehiculeProprietaire.vehicule_id.in_([x.id for x in vehicles]),
                   VehiculeProprietaire.date_fin.is_(None))
        ).all():
            owners[vehicule_id] = client
    return jsonify({"vehicules": [vehicule_dict(x, owners.get(x.id)) for x in vehicles],
                    "total": total, "page": page, "par_page": par_page})


@bp.post("")
@require_permission("vehicules.create")
def create_vehicule():
    data = json_body()
    errors = {}
    changes = _parse(data, errors, partial=False)
    owner = None
    if data.get("client_id") not in (None, ""):
        owner = _client_from(data.get("client_id"), errors)
    if errors:
        raise validation_error(errors)
    _check_unique(changes)
    vehicule = Vehicule(**changes)
    db.session.add(vehicule)
    db.session.flush()
    if owner is not None:
        db.session.add(VehiculeProprietaire(vehicule_id=vehicule.id, client_id=owner.id, date_debut=_now()))
    audit("vehicule.cree", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="vehicule", entity_id=vehicule.id)
    _commit()
    return jsonify({"vehicule": vehicule_dict(vehicule, owner)}), 201


@bp.get("/<uuid:vehicule_id>")
@require_permission("vehicules.read")
def get_vehicule(vehicule_id):
    vehicule = _get_vehicule(vehicule_id)
    _, owner = _current_owner(vehicule.id)
    history = db.session.execute(
        sa.select(VehiculeProprietaire, Client)
        .join(Client, sa.and_(Client.id == VehiculeProprietaire.client_id,
                              Client.garage_id == VehiculeProprietaire.garage_id))
        .where(VehiculeProprietaire.vehicule_id == vehicule.id)
        .order_by(VehiculeProprietaire.date_debut.desc())
    ).all()
    return jsonify({
        "vehicule": vehicule_dict(vehicule, owner),
        "proprietaire": client_dict(owner) if owner else None,
        "historique_proprietaires": [
            {"client_id": str(c.id), "nom_affiche": c.nom_affiche,
             "date_debut": p.date_debut.isoformat() if p.date_debut else None,
             "date_fin": p.date_fin.isoformat() if p.date_fin else None}
            for p, c in history
        ],
    })


@bp.patch("/<uuid:vehicule_id>")
@require_permission("vehicules.update")
def update_vehicule(vehicule_id):
    vehicule = _get_vehicule(vehicule_id)
    data = json_body()
    errors = {}
    old_km = vehicule.kilometrage_actuel
    changes = _parse(data, errors, partial=True, existing=vehicule)
    if errors:
        raise validation_error(errors)
    _check_unique(changes, exclude_id=vehicule.id)
    for field, value in changes.items():
        setattr(vehicule, field, value)
    details = {"champs": sorted(changes)}
    if "kilometrage_actuel" in changes and old_km is not None and changes["kilometrage_actuel"] is not None \
            and changes["kilometrage_actuel"] < old_km:
        details["km_corrige"] = {"avant": old_km, "apres": changes["kilometrage_actuel"]}
    audit("vehicule.modifie", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="vehicule", entity_id=vehicule.id, details=details)
    _commit()
    _, owner = _current_owner(vehicule.id)
    return jsonify({"vehicule": vehicule_dict(vehicule, owner)})


@bp.post("/<uuid:vehicule_id>/transfer")
@require_permission("vehicules.transfer")
def transfer_vehicule(vehicule_id):
    """Change le propriétaire sans perdre l'historique."""
    vehicule = _get_vehicule(vehicule_id)
    data = json_body()
    errors = {}
    target = _client_from(data.get("client_id"), errors)
    if errors:
        raise validation_error(errors)
    current_row, current_client = _current_owner(vehicule.id)
    if current_client is not None and current_client.id == target.id:
        raise validation_error({"client_id": "Ce client est déjà le propriétaire actuel."})
    if current_row is not None:
        current_row.date_fin = _now()
        db.session.flush()  # ferme l'ancienne ligne AVANT d'ouvrir la nouvelle (index unique partiel)
    db.session.add(VehiculeProprietaire(vehicule_id=vehicule.id, client_id=target.id, date_debut=_now()))
    audit("vehicule.transfere", garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="vehicule", entity_id=vehicule.id,
          details={"de": str(current_client.id) if current_client else None, "vers": str(target.id)})
    _commit()
    return jsonify({"vehicule": vehicule_dict(vehicule, target)})


def _set_actif(vehicule_id, actif, action):
    vehicule = _get_vehicule(vehicule_id)
    vehicule.actif = actif
    audit(action, garage_id=current_user.garage_id, user_id=current_user.id,
          entity_type="vehicule", entity_id=vehicule.id)
    _commit()
    _, owner = _current_owner(vehicule.id)
    return jsonify({"vehicule": vehicule_dict(vehicule, owner)})


@bp.post("/<uuid:vehicule_id>/archive")
@require_permission("vehicules.archive")
def archive_vehicule(vehicule_id):
    return _set_actif(vehicule_id, False, "vehicule.archive")


@bp.post("/<uuid:vehicule_id>/restore")
@require_permission("vehicules.archive")
def restore_vehicule(vehicule_id):
    return _set_actif(vehicule_id, True, "vehicule.restaure")
