"""Devis : brouillon, envoi (numérotation), versions, acceptation, lien client et PDF."""
import hashlib
import secrets
import uuid
from datetime import timedelta

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy.exc import IntegrityError

from app import validators as v
from app.api._common import json_body, pagination
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import LIGNE_TYPES, Client, Devis, DevisLigne, Garage, Vehicule, as_utc, utcnow
from app.permissions import require_permission
from app.serializers import devis_dict
from app.services import devis_calc as calc
from app.services.audit import audit
from app.services.numbering import next_number
from app.services.pdf_devis import pdf_response
from app.tenancy import unscoped

bp = Blueprint("devis", __name__, url_prefix="/api/devis")

DEFAULT_CONDITIONS = ("Devis valable pendant la durée indiquée. Les prix pourront être révisés si des travaux "
                      "supplémentaires s'avèrent nécessaires après démontage.")
MAX_LIGNES = 100


# ------------------------------------------------------------------ accès aux données (toujours filtrées par garage)
def _get_devis(devis_id) -> Devis:
    devis = db.session.scalar(sa.select(Devis).where(Devis.id == devis_id))
    if devis is None:
        raise ApiError("Devis introuvable.", 404, "devis_introuvable")
    return devis


def _garage() -> Garage:
    with unscoped():
        return db.session.get(Garage, current_user.garage_id)


def _client(devis):
    return db.session.scalar(sa.select(Client).where(Client.id == devis.client_id))


def _vehicule(devis):
    if not devis.vehicule_id:
        return None
    return db.session.scalar(sa.select(Vehicule).where(Vehicule.id == devis.vehicule_id))


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _find_client(value, errors):
    cid = _uuid(value)
    client = db.session.scalar(sa.select(Client).where(Client.id == cid)) if cid else None
    if client is None:
        errors["client_id"] = "Client introuvable."
    elif not client.actif:
        errors["client_id"] = "Ce client est archivé."
    else:
        return client
    return None


def _find_vehicule(value, errors):
    vid = _uuid(value)
    vehicule = db.session.scalar(sa.select(Vehicule).where(Vehicule.id == vid)) if vid else None
    if vehicule is None:
        errors["vehicule_id"] = "Véhicule introuvable."
    elif not vehicule.actif:
        errors["vehicule_id"] = "Ce véhicule est archivé."
    else:
        return vehicule
    return None


def _commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Conflit de données, réessayez.", 409, "conflit")


# ------------------------------------------------------------------ lecture / calcul
def _parse_lignes(raw, decimals, errors):
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_LIGNES:
        errors["lignes"] = f"La liste des lignes est invalide ({MAX_LIGNES} lignes maximum)."
        return []
    parsed, problems = [], []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            problems.append(f"Ligne {index} : format invalide.")
            continue
        local = {}
        kind = v.choice(item, "type", local, LIGNE_TYPES, label="Le type") or "main_oeuvre"
        designation = v.text(item, "designation", local, max_len=200, label="La désignation")
        unite = v.text(item, "unite", local, max_len=20, required=False, label="L'unité")
        try:
            quantite = v.decimal_value(item.get("quantite"), label="La quantité", minimum="0.01", maximum="100000", places=2)
            prix = v.decimal_value(item.get("prix_unitaire"), label="Le prix unitaire", minimum="0", maximum="1000000000",
                                   places=decimals)
            remise = v.decimal_value(item.get("remise_pct", 0) if item.get("remise_pct") not in (None, "") else 0,
                                     label="La remise", minimum="0", maximum="100", places=2)
        except ValueError as exc:
            local["_"] = str(exc)
            quantite = prix = remise = None
        if local:
            problems.append(f"Ligne {index} : " + " ".join(local.values()))
            continue
        parsed.append({"type": kind, "designation": designation, "unite": unite, "quantite": quantite,
                       "prix_unitaire": prix, "remise_pct": remise})
    if problems:
        errors["lignes"] = " ".join(problems)
    return parsed


def _snapshot(devis, garage):
    devis.devise = garage.devise
    devis.devise_decimales = garage.devise_decimales
    devis.tva_active = garage.tva_active
    devis.tva_taux = garage.tva_taux


def _set_lignes(devis, parsed):
    devis.lignes.clear()
    for position, item in enumerate(parsed):
        devis.lignes.append(DevisLigne(
            position=position, **item,
            total_ht=calc.line_total(item["quantite"], item["prix_unitaire"], item["remise_pct"], devis.devise_decimales)))


def _recompute(devis):
    try:
        sous, remise, total_ht, tva, ttc = calc.totals(
            [l.total_ht for l in devis.lignes], devis.remise_globale or 0, devis.tva_active, devis.tva_taux,
            devis.devise_decimales)
    except ValueError as exc:
        raise validation_error({"remise_globale": str(exc)})
    devis.sous_total_ht, devis.remise_globale, devis.total_ht, devis.total_tva, devis.total_ttc = sous, remise, total_ht, tva, ttc


def _require_draft(devis):
    if devis.statut != "brouillon":
        raise ApiError("Un devis envoyé ne peut plus être modifié : créez une nouvelle version.", 409, "devis_verrouille")


def _full(devis):
    return devis_dict(devis, _client(devis), _vehicule(devis))


# ------------------------------------------------------------------ liste, création, détail
@bp.get("")
@require_permission("devis.read")
def list_devis():
    page, par_page = pagination()
    now = utcnow()
    filters = []
    statut = request.args.get("statut", "tous")
    if statut == "expire":
        filters += [Devis.statut == "envoye", Devis.date_validite < now]
    elif statut == "envoye":
        filters += [Devis.statut == "envoye", Devis.date_validite >= now]
    elif statut in ("brouillon", "accepte", "refuse", "remplace"):
        filters.append(Devis.statut == statut)
    for param, column in (("client_id", Devis.client_id), ("vehicule_id", Devis.vehicule_id)):
        if request.args.get(param):
            value = _uuid(request.args[param])
            if value is None:
                raise validation_error({param: "Identifiant invalide."})
            filters.append(column == value)
    q = (request.args.get("q") or "").strip()
    if q:
        pattern = v.like_pattern(q[:100])
        names = sa.select(Client.id).where(
            Client.garage_id == Devis.garage_id,
            sa.or_(*(c.ilike(pattern, escape="\\") for c in (Client.nom, Client.prenom, Client.raison_sociale))))
        filters.append(sa.or_(Devis.numero.ilike(pattern, escape="\\"), Devis.client_id.in_(names)))
    total = db.session.scalar(sa.select(sa.func.count(Devis.id)).where(*filters))
    rows = db.session.scalars(
        sa.select(Devis).where(*filters).order_by(Devis.created_at.desc()).limit(par_page).offset((page - 1) * par_page)
    ).all()
    clients = {}
    if rows:
        for client in db.session.scalars(sa.select(Client).where(Client.id.in_({d.client_id for d in rows}))):
            clients[client.id] = client
    return jsonify({"devis": [devis_dict(d, clients.get(d.client_id), None, with_lignes=False) for d in rows],
                    "total": total, "page": page, "par_page": par_page})


@bp.post("")
@require_permission("devis.create")
def create_devis():
    data = json_body()
    garage = _garage()
    errors = {}
    client = _find_client(data.get("client_id"), errors)
    vehicule = _find_vehicule(data["vehicule_id"], errors) if data.get("vehicule_id") else None
    remise = _remise(data, errors)
    lignes = _parse_lignes(data.get("lignes"), garage.devise_decimales, errors)
    conditions = v.long_text(data, "conditions", errors, label="Les conditions") if "conditions" in data else DEFAULT_CONDITIONS
    if errors:
        raise validation_error(errors)
    devis = Devis(client_id=client.id, vehicule_id=vehicule.id if vehicule else None, statut="brouillon", version=1,
                  conditions=conditions, remise_globale=remise, cree_par_id=current_user.id)
    _snapshot(devis, garage)
    _set_lignes(devis, lignes)
    _recompute(devis)
    db.session.add(devis)
    db.session.flush()
    audit("devis.cree", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis", entity_id=devis.id)
    _commit()
    return jsonify({"devis": _full(devis)}), 201


def _remise(data, errors):
    from decimal import Decimal

    if data.get("remise_globale") in (None, ""):
        return Decimal(0)
    try:
        return v.decimal_value(data["remise_globale"], label="La remise", minimum="0", maximum="1000000000", places=3)
    except ValueError as exc:
        errors["remise_globale"] = str(exc)
        return Decimal(0)


@bp.get("/<uuid:devis_id>")
@require_permission("devis.read")
def get_devis(devis_id):
    return jsonify({"devis": _full(_get_devis(devis_id))})


@bp.patch("/<uuid:devis_id>")
@require_permission("devis.update")
def update_devis(devis_id):
    devis = _get_devis(devis_id)
    _require_draft(devis)
    data = json_body()
    garage = _garage()
    errors = {}
    if "client_id" in data:
        client = _find_client(data["client_id"], errors)
        if client:
            devis.client_id = client.id
    if "vehicule_id" in data:
        if data["vehicule_id"] in (None, ""):
            devis.vehicule_id = None
        else:
            vehicule = _find_vehicule(data["vehicule_id"], errors)
            if vehicule:
                devis.vehicule_id = vehicule.id
    if "remise_globale" in data:
        devis.remise_globale = _remise(data, errors)
    if "conditions" in data:
        devis.conditions = v.long_text(data, "conditions", errors, label="Les conditions")
    parsed = _parse_lignes(data["lignes"], garage.devise_decimales, errors) if "lignes" in data else None
    if errors:
        db.session.rollback()
        raise validation_error(errors)
    _snapshot(devis, garage)  # un brouillon suit toujours le profil du garage (devise, TVA)
    if parsed is not None:
        _set_lignes(devis, parsed)
    else:  # la devise ou la TVA ont pu changer : on recalcule chaque ligne
        for ligne in devis.lignes:
            ligne.total_ht = calc.line_total(ligne.quantite, ligne.prix_unitaire, ligne.remise_pct, devis.devise_decimales)
    _recompute(devis)
    audit("devis.modifie", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis",
          entity_id=devis.id, details={"champs": sorted(k for k in data if k in ("client_id", "vehicule_id", "remise_globale", "conditions", "lignes"))})
    _commit()
    return jsonify({"devis": _full(devis)})


@bp.delete("/<uuid:devis_id>")
@require_permission("devis.delete")
def delete_devis(devis_id):
    devis = _get_devis(devis_id)
    _require_draft(devis)
    audit("devis.supprime", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis", entity_id=devis.id)
    db.session.delete(devis)
    _commit()
    return jsonify({"message": "Brouillon supprimé."})


# ------------------------------------------------------------------ cycle de vie
@bp.post("/<uuid:devis_id>/send")
@require_permission("devis.send")
def send_devis(devis_id):
    """Brouillon -> envoyé : attribue le numéro légal, fige les montants et fixe la validité."""
    devis = _get_devis(devis_id)
    _require_draft(devis)
    body = request.get_json(silent=True) if request.is_json else {}
    errors = {}
    jours = v.integer(body or {}, "validite_jours", errors, label="La validité (jours)", minimum=1, maximum=365)
    if errors:
        raise validation_error(errors)
    jours = jours or current_app.config["DEVIS_VALIDITE_JOURS"]
    if not devis.lignes:
        raise validation_error({"lignes": "Ajoutez au moins une ligne avant d'envoyer le devis."})
    client = _client(devis)
    if client is None or not client.actif:
        raise validation_error({"client_id": "Le client est introuvable ou archivé."})
    garage = _garage()
    _snapshot(devis, garage)
    for ligne in devis.lignes:
        ligne.total_ht = calc.line_total(ligne.quantite, ligne.prix_unitaire, ligne.remise_pct, devis.devise_decimales)
    _recompute(devis)
    if devis.total_ttc <= 0:
        raise validation_error({"lignes": "Le total du devis doit être supérieur à zéro."})
    parent = db.session.scalar(sa.select(Devis).where(Devis.id == devis.devis_parent_id)) if devis.devis_parent_id else None
    if parent is not None and parent.numero:
        devis.numero = f"{parent.numero.split('-V')[0]}-V{devis.version}"  # même numéro de base, suffixe de version
        parent.statut = "remplace"
    else:
        devis.numero = next_number("DEV", garage.id)
    now = utcnow()
    devis.statut, devis.date_emission, devis.date_validite = "envoye", now, now + timedelta(days=jours)
    audit("devis.envoye", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis",
          entity_id=devis.id, details={"numero": devis.numero})
    _commit()
    return jsonify({"devis": _full(devis)})


@bp.post("/<uuid:devis_id>/new-version")
@require_permission("devis.create")
def new_version(devis_id):
    src = _get_devis(devis_id)
    if src.statut_effectif not in ("envoye", "refuse", "expire"):
        raise ApiError("On ne peut créer une nouvelle version que d'un devis envoyé, refusé ou expiré.", 409, "statut_invalide")
    pending = db.session.scalar(sa.select(Devis).where(Devis.devis_parent_id == src.id, Devis.statut == "brouillon"))
    if pending is not None:
        return jsonify({"devis": _full(pending)})  # déjà une version en préparation : on la retrouve
    garage = _garage()
    new = Devis(client_id=src.client_id, vehicule_id=src.vehicule_id, statut="brouillon", version=src.version + 1,
                devis_parent_id=src.id, conditions=src.conditions, remise_globale=src.remise_globale,
                cree_par_id=current_user.id)
    _snapshot(new, garage)
    _set_lignes(new, [{"type": l.type, "designation": l.designation, "unite": l.unite, "quantite": l.quantite,
                       "prix_unitaire": l.prix_unitaire, "remise_pct": l.remise_pct} for l in src.lignes])
    _recompute(new)
    db.session.add(new)
    db.session.flush()
    audit("devis.nouvelle_version", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis",
          entity_id=new.id, details={"depuis": str(src.id)})
    _commit()
    return jsonify({"devis": _full(new)}), 201


def _require_open(devis):
    effective = devis.statut_effectif
    if effective == "expire":
        raise ApiError("Ce devis a expiré : créez une nouvelle version.", 409, "devis_expire")
    if effective != "envoye":
        raise ApiError("Seul un devis envoyé peut être accepté ou refusé.", 409, "statut_invalide")


@bp.post("/<uuid:devis_id>/accept")
@require_permission("devis.respond")
def accept_devis(devis_id):
    """Le client a donné son accord au garage (en personne, par téléphone, WhatsApp...)."""
    devis = _get_devis(devis_id)
    _require_open(devis)
    errors = {}
    nom = v.text(json_body(), "nom", errors, label="Le nom de la personne qui accepte")
    if errors:
        raise validation_error(errors)
    devis.statut, devis.accepte_le, devis.acceptation_nom, devis.acceptation_mode = "accepte", utcnow(), nom, "atelier"
    audit("devis.accepte", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis", entity_id=devis.id)
    _commit()
    return jsonify({"devis": _full(devis)})


@bp.post("/<uuid:devis_id>/refuse")
@require_permission("devis.respond")
def refuse_devis(devis_id):
    devis = _get_devis(devis_id)
    _require_open(devis)
    errors = {}
    body = request.get_json(silent=True) if request.is_json else {}
    motif = v.text(body or {}, "motif", errors, max_len=255, required=False, label="Le motif")
    if errors:
        raise validation_error(errors)
    devis.statut, devis.refuse_le, devis.refus_motif = "refuse", utcnow(), motif
    audit("devis.refuse", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis", entity_id=devis.id)
    _commit()
    return jsonify({"devis": _full(devis)})


@bp.post("/<uuid:devis_id>/public-link")
@require_permission("devis.send")
def public_link(devis_id):
    """Crée (ou remplace) le lien que le client ouvre pour consulter et accepter le devis. Seule l'empreinte est stockée."""
    devis = _get_devis(devis_id)
    if devis.statut != "envoye":
        raise ApiError("Le lien client n'est disponible que pour un devis envoyé.", 409, "statut_invalide")
    token = secrets.token_urlsafe(32)
    devis.token_public_hash = hashlib.sha256(token.encode()).hexdigest()  # l'ancien lien cesse de fonctionner
    audit("devis.lien_client", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="devis", entity_id=devis.id)
    _commit()
    return jsonify({"url": f"{current_app.config['APP_BASE_URL']}/d/{token}"})


@bp.get("/<uuid:devis_id>/pdf")
@require_permission("devis.read")
def devis_pdf(devis_id):
    devis = _get_devis(devis_id)
    return pdf_response(devis, _garage(), _client(devis), _vehicule(devis))
