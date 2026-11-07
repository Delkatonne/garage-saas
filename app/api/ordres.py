"""Ordres de réparation : accueil du véhicule, suivi des statuts, notes de l'atelier, autorisation de travaux, PDF."""
import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy.exc import IntegrityError

from app import validators as v
from app.api._common import json_body, pagination
from app.api.vehicules import _current_owner
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import (OR_FERMES, OR_STATUTS, OR_TRANSITIONS, Client, Devis, Garage, OrdreReparation,
                        OrStatutHistorique, User, Vehicule, utcnow)
from app.permissions import has_permission, require_permission
from app.serializers import devis_dict, or_dict
from app.services.audit import audit
from app.services.numbering import next_number
from app.services.or_workflow import change_status, log_status
from app.services.pdf_or import pdf_or_response
from app.tenancy import unscoped

bp = Blueprint("ordres", __name__, url_prefix="/api/or")

NOTES_ONLY = {"diagnostic", "travaux_effectues"}  # ce que peut écrire un mécanicien (sans la permission "or.update")


# ------------------------------------------------------------------ accès aux données (filtrées par garage)
def _get_or(or_id) -> OrdreReparation:
    ordre = db.session.scalar(sa.select(OrdreReparation).where(OrdreReparation.id == or_id))
    if ordre is None:
        raise ApiError("Ordre de réparation introuvable.", 404, "or_introuvable")
    return ordre


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Conflit de données, réessayez.", 409, "conflit")


def _context(ordre):
    client = db.session.scalar(sa.select(Client).where(Client.id == ordre.client_id))
    vehicule = db.session.scalar(sa.select(Vehicule).where(Vehicule.id == ordre.vehicule_id))
    mecano = (db.session.scalar(sa.select(User).where(User.id == ordre.mecanicien_id))
              if ordre.mecanicien_id else None)
    return client, vehicule, mecano


def _dict(ordre):
    client, vehicule, mecano = _context(ordre)
    return or_dict(ordre, client, vehicule, mecano, show_phone=has_permission(current_user, "clients.read"))


def _find_mecanicien(value, errors):
    uid = _uuid(value)
    user = db.session.scalar(sa.select(User).where(User.id == uid)) if uid else None
    if user is None or not user.actif or user.role not in ("mecanicien", "owner"):
        errors["mecanicien_id"] = "Mécanicien introuvable."
        return None
    return user


def _parse_date(data, field, errors, label):
    value = data.get(field)
    if value in (None, ""):
        return None
    try:
        if not isinstance(value, str):
            raise ValueError
        day = date.fromisoformat(value[:10])
    except ValueError:
        errors[field] = f"{label} est invalide (format AAAA-MM-JJ)."
        return None
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _parse(data, errors, partial, only=None):
    """Valide les champs fournis. `only` : ensemble de champs autorisés (rôle limité) ; les autres sont refusés."""
    changes = {}

    def wanted(field):
        if only is not None and field in data and field not in only:
            raise ApiError("Vous ne pouvez modifier que le diagnostic et les travaux effectués.", 403, "permission_refusee")
        return field in data or not partial

    if wanted("motif"):
        changes["motif"] = v.text(data, "motif", errors, max_len=255, label="Le motif")
    for field, label in (("symptomes", "Les symptômes"), ("etat_arrivee", "L'état à l'arrivée"),
                         ("diagnostic", "Le diagnostic"), ("travaux_effectues", "Les travaux effectués")):
        if wanted(field):
            changes[field] = v.long_text(data, field, errors, label=label)
    if wanted("kilometrage_entree"):
        changes["kilometrage_entree"] = v.integer(data, "kilometrage_entree", errors, label="Le kilométrage",
                                                  minimum=0, maximum=9_999_999)
    if wanted("niveau_carburant"):
        changes["niveau_carburant"] = v.integer(data, "niveau_carburant", errors, label="Le niveau de carburant",
                                                minimum=0, maximum=100)
    if wanted("urgent"):
        if data.get("urgent") not in (None, True, False):
            errors["urgent"] = "Booléen attendu."
        changes["urgent"] = bool(data.get("urgent"))
    if wanted("date_sortie_prevue"):
        changes["date_sortie_prevue"] = _parse_date(data, "date_sortie_prevue", errors, "La date de sortie prévue")
    if wanted("mecanicien_id"):
        if data.get("mecanicien_id") in (None, ""):
            changes["mecanicien_id"] = None
        else:
            mecano = _find_mecanicien(data["mecanicien_id"], errors)
            changes["mecanicien_id"] = mecano.id if mecano else None
    return changes


def _next_statuses(ordre):
    return [s for s in OR_STATUTS if s in OR_TRANSITIONS[ordre.statut] and s != "facture"]


# ------------------------------------------------------------------ liste, création, détail
@bp.get("/mecaniciens")
@require_permission("or.read")
def mecaniciens():
    users = db.session.scalars(sa.select(User).where(User.actif.is_(True), User.role.in_(("mecanicien", "owner")))
                               .order_by(sa.func.lower(User.nom_complet))).all()
    return jsonify({"mecaniciens": [{"id": str(u.id), "nom": u.nom_complet, "role": u.role} for u in users]})


@bp.get("")
@require_permission("or.read")
def list_or():
    page, par_page = pagination()
    filters = []
    statut = request.args.get("statut", "ouverts")
    if statut == "ouverts":
        filters.append(OrdreReparation.statut.notin_(OR_FERMES))
    elif statut in OR_STATUTS:
        filters.append(OrdreReparation.statut == statut)
    for param, column in (("client_id", OrdreReparation.client_id), ("vehicule_id", OrdreReparation.vehicule_id)):
        if request.args.get(param):
            value = _uuid(request.args[param])
            if value is None:
                raise validation_error({param: "Identifiant invalide."})
            filters.append(column == value)
    if request.args.get("mecanicien_id") == "moi":
        filters.append(OrdreReparation.mecanicien_id == current_user.id)
    elif request.args.get("mecanicien_id"):
        value = _uuid(request.args["mecanicien_id"])
        if value is None:
            raise validation_error({"mecanicien_id": "Identifiant invalide."})
        filters.append(OrdreReparation.mecanicien_id == value)
    if request.args.get("urgent") == "1":
        filters.append(OrdreReparation.urgent.is_(True))
    q = (request.args.get("q") or "").strip()
    if q:
        pattern = v.like_pattern(q[:100])
        key = "".join(ch for ch in q.upper() if ch.isalnum())
        vehicle_conds = [c.ilike(pattern, escape="\\") for c in (Vehicule.immatriculation, Vehicule.marque, Vehicule.modele)]
        if key:
            vehicle_conds.append(Vehicule.immatriculation_cle.like(f"%{key}%"))
        vehicles = sa.select(Vehicule.id).where(Vehicule.garage_id == OrdreReparation.garage_id, sa.or_(*vehicle_conds))
        clients = sa.select(Client.id).where(
            Client.garage_id == OrdreReparation.garage_id,
            sa.or_(*(c.ilike(pattern, escape="\\") for c in (Client.nom, Client.prenom, Client.raison_sociale))))
        filters.append(sa.or_(OrdreReparation.numero.ilike(pattern, escape="\\"),
                              OrdreReparation.motif.ilike(pattern, escape="\\"),
                              OrdreReparation.vehicule_id.in_(vehicles), OrdreReparation.client_id.in_(clients)))
    total = db.session.scalar(sa.select(sa.func.count(OrdreReparation.id)).where(*filters))
    rows = db.session.scalars(
        sa.select(OrdreReparation).where(*filters)
        .order_by(OrdreReparation.urgent.desc(), OrdreReparation.date_entree.desc())
        .limit(par_page).offset((page - 1) * par_page)
    ).all()
    clients, vehicles = {}, {}
    if rows:
        for c in db.session.scalars(sa.select(Client).where(Client.id.in_({o.client_id for o in rows}))):
            clients[c.id] = c
        for x in db.session.scalars(sa.select(Vehicule).where(Vehicule.id.in_({o.vehicule_id for o in rows}))):
            vehicles[x.id] = x
    show_phone = has_permission(current_user, "clients.read")
    return jsonify({"ordres": [or_dict(o, clients.get(o.client_id), vehicles.get(o.vehicule_id), None, show_phone) for o in rows],
                    "total": total, "page": page, "par_page": par_page})


@bp.post("")
@require_permission("or.create")
def create_or():
    data = json_body()
    errors = {}
    vid = _uuid(data.get("vehicule_id"))
    vehicule = db.session.scalar(sa.select(Vehicule).where(Vehicule.id == vid)) if vid else None
    client = None
    if vehicule is None:
        errors["vehicule_id"] = "Véhicule introuvable."
    elif not vehicule.actif:
        errors["vehicule_id"] = "Ce véhicule est archivé."
    if data.get("client_id") not in (None, ""):
        cid = _uuid(data["client_id"])
        client = db.session.scalar(sa.select(Client).where(Client.id == cid)) if cid else None
        if client is None:
            errors["client_id"] = "Client introuvable."
    elif vehicule is not None and "vehicule_id" not in errors:
        _, client = _current_owner(vehicule.id)
        if client is None:
            errors["client_id"] = "Ce véhicule n'a pas de propriétaire : indiquez le client."
    if client is not None and not client.actif:
        errors["client_id"] = "Ce client est archivé."
    changes = _parse(data, errors, partial=False)
    km = changes.get("kilometrage_entree")
    if km is not None and vehicule is not None and vehicule.kilometrage_actuel is not None and km < vehicule.kilometrage_actuel:
        errors["kilometrage_entree"] = (f"Inférieur au kilométrage enregistré ({vehicule.kilometrage_actuel} km). "
                                        "Corrigez d'abord le kilométrage sur la fiche du véhicule.")
    if errors:
        raise validation_error(errors)
    warnings = []
    others = db.session.scalar(sa.select(sa.func.count(OrdreReparation.id)).where(
        OrdreReparation.vehicule_id == vehicule.id, OrdreReparation.statut.notin_(OR_FERMES)))
    if others:
        warnings.append("Ce véhicule a déjà un autre ordre de réparation en cours.")
    ordre = OrdreReparation(client_id=client.id, vehicule_id=vehicule.id, statut="en_attente", date_entree=utcnow(),
                            numero=next_number("OR", current_user.garage_id), cree_par_id=current_user.id, **changes)
    if km is not None and (vehicule.kilometrage_actuel is None or km > vehicule.kilometrage_actuel):
        vehicule.kilometrage_actuel = km  # le compteur du véhicule suit l'entrée en atelier
    db.session.add(ordre)
    db.session.flush()
    log_status(ordre, None, "en_attente", current_user.id, "Ordre créé")
    audit("or.cree", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="or", entity_id=ordre.id,
          details={"numero": ordre.numero})
    _commit()
    return jsonify({"ordre": _dict(ordre), "avertissements": warnings}), 201


@bp.get("/<uuid:or_id>")
@require_permission("or.read")
def get_or(or_id):
    ordre = _get_or(or_id)
    history = db.session.scalars(sa.select(OrStatutHistorique).where(OrStatutHistorique.or_id == ordre.id)
                                 .order_by(OrStatutHistorique.created_at, OrStatutHistorique.id)).all()
    names = {}
    ids = {h.user_id for h in history if h.user_id}
    if ids:
        names = {u.id: u.nom_complet for u in db.session.scalars(sa.select(User).where(User.id.in_(ids)))}
    quotes = db.session.scalars(sa.select(Devis).where(Devis.or_id == ordre.id).order_by(Devis.created_at.desc())).all()
    return jsonify({
        "ordre": _dict(ordre),
        "transitions_possibles": _next_statuses(ordre),
        "historique": [{"ancien_statut": h.ancien_statut, "nouveau_statut": h.nouveau_statut,
                        "commentaire": h.commentaire, "par": names.get(h.user_id), "date": h.created_at.isoformat()} for h in history],
        "devis": [devis_dict(d, with_lignes=False) for d in quotes] if has_permission(current_user, "devis.read") else [],
    })


@bp.patch("/<uuid:or_id>")
@require_permission("or.update_status")
def update_or(or_id):
    ordre = _get_or(or_id)
    if ordre.statut in OR_FERMES:
        raise ApiError("Cet ordre est clos : il n'est plus modifiable.", 409, "or_clos")
    data = json_body()
    errors = {}
    only = None if has_permission(current_user, "or.update") else NOTES_ONLY
    changes = _parse(data, errors, partial=True, only=only)
    if errors:
        raise validation_error(errors)
    for field, value in changes.items():
        setattr(ordre, field, value)
    audit("or.modifie", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="or", entity_id=ordre.id,
          details={"champs": sorted(changes)})
    _commit()
    return jsonify({"ordre": _dict(ordre)})


@bp.post("/<uuid:or_id>/status")
@require_permission("or.update_status")
def set_status(or_id):
    ordre = _get_or(or_id)
    data = json_body()
    target = data.get("statut")
    errors = {}
    if target not in OR_STATUTS:
        raise validation_error({"statut": "Statut inconnu."})
    if target == "facture":
        raise ApiError("Ce statut est attribué automatiquement lors de la facturation.", 409, "transition_invalide")
    note = v.text(data, "note", errors, max_len=255, required=(target == "annule"), label="Le motif")
    if errors:
        raise validation_error(errors)
    warnings = []
    if target == "en_cours" and not ordre.signature_nom and ordre.statut != "devis_accepte":
        warnings.append("Aucune autorisation de travaux n'est enregistrée pour cet ordre.")
    change_status(ordre, target, current_user.id, note)
    audit("or.statut", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="or", entity_id=ordre.id,
          details={"statut": target})
    _commit()
    return jsonify({"ordre": _dict(ordre), "transitions_possibles": _next_statuses(ordre), "avertissements": warnings})


@bp.post("/<uuid:or_id>/authorize")
@require_permission("or.update")
def authorize(or_id):
    """Le client autorise le garage à effectuer les travaux (en personne, par téléphone, WhatsApp...)."""
    ordre = _get_or(or_id)
    if ordre.statut in OR_FERMES:
        raise ApiError("Cet ordre est clos.", 409, "or_clos")
    errors = {}
    nom = v.text(json_body(), "nom", errors, label="Le nom de la personne qui autorise")
    if errors:
        raise validation_error(errors)
    ordre.signature_nom, ordre.signature_date = nom, utcnow()
    log_status(ordre, ordre.statut, ordre.statut, current_user.id, f"Travaux autorisés par {nom}")
    audit("or.autorisation", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="or", entity_id=ordre.id)
    _commit()
    return jsonify({"ordre": _dict(ordre)})


@bp.get("/<uuid:or_id>/pdf")
@require_permission("or.read")
def or_pdf(or_id):
    ordre = _get_or(or_id)
    client, vehicule, mecano = _context(ordre)
    with unscoped():
        garage = db.session.get(Garage, current_user.garage_id)
    return pdf_or_response(ordre, garage, client, vehicule, mecano)
