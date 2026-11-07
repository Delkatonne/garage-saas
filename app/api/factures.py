"""Factures : brouillon, émission (numéro légal, données figées, empreinte), avoir et PDF."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy.exc import IntegrityError

from app import validators as v
from app.api._common import json_body, pagination
from app.api.devis import _find_client, _find_vehicule, _parse_lignes, _remise
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import (Avoir, Client, Devis, Facture, FactureLigne, Garage, OrdreReparation, Paiement, Recu, Vehicule,
                        as_utc, utcnow)
from app.permissions import require_permission
from app.serializers import facture_dict, paiement_dict
from app.services import devis_calc as calc
from app.services.audit import audit
from app.services.factures_core import build_snapshot, compute_hash, due_date, paid_amount, paid_map
from app.services.numbering import next_number
from app.services.or_workflow import change_status
from app.services.pdf_facture import logo_for, pdf_response, render_facture_pdf
from app.tenancy import unscoped

bp = Blueprint("factures", __name__, url_prefix="/api/factures")

DEFAULT_CONDITIONS = "Paiement à réception de la facture. Toute somme non réglée à l'échéance peut donner lieu à des pénalités de retard."


# ------------------------------------------------------------------ accès (toujours filtré par garage)
def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _get(facture_id, lock=False) -> Facture:
    stmt = sa.select(Facture).where(Facture.id == facture_id)
    if lock:
        stmt = stmt.with_for_update()
    f = db.session.scalar(stmt)
    if f is None:
        raise ApiError("Facture introuvable.", 404, "facture_introuvable")
    return f


def _garage() -> Garage:
    with unscoped():
        return db.session.get(Garage, current_user.garage_id)


def _one(model, value):
    return db.session.scalar(sa.select(model).where(model.id == value)) if value else None


def _commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("Conflit de données, réessayez.", 409, "conflit")


def _snapshot_params(f, garage):
    f.devise, f.devise_decimales, f.tva_active, f.tva_taux = garage.devise, garage.devise_decimales, garage.tva_active, garage.tva_taux


def _set_lignes(f, items):
    f.lignes.clear()
    for position, item in enumerate(items):
        f.lignes.append(FactureLigne(position=position, **item, total_ht=calc.line_total(
            item["quantite"], item["prix_unitaire"], item["remise_pct"], f.devise_decimales)))


def _recompute(f):
    try:
        sous, remise, ht, tva, ttc = calc.totals([l.total_ht for l in f.lignes], f.remise_globale or 0, f.tva_active, f.tva_taux,
                                                 f.devise_decimales)
    except ValueError as exc:
        raise validation_error({"remise_globale": str(exc)})
    f.sous_total_ht, f.remise_globale, f.total_ht, f.total_tva, f.total_ttc = sous, remise, ht, tva, ttc


def _require_draft(f):
    if f.statut != "brouillon":
        raise _locked()


def _locked():
    return ApiError("Une facture émise ne peut plus être modifiée ni supprimée : émettez un avoir.", 409, "document_verrouille")


def _context(f):
    return (_one(Client, f.client_id), _one(Vehicule, f.vehicule_id), _one(OrdreReparation, f.or_id), _one(Devis, f.devis_id))


def _full(f):
    client, vehicule, ordre, devis = _context(f)
    return facture_dict(f, paid_amount(f.id), client, vehicule, ordre, devis)


def _existing_invoice(or_id=None, devis_id=None, exclude=None):
    conds = []
    if or_id:
        conds.append(Facture.or_id == or_id)
    if devis_id:
        conds.append(Facture.devis_id == devis_id)
    if not conds:
        return None
    stmt = sa.select(Facture).where(sa.or_(*conds), Facture.statut != "annulee")
    if exclude:
        stmt = stmt.where(Facture.id != exclude)
    return db.session.scalar(stmt.limit(1))


def _items_from_devis(devis):
    return [{"type": l.type, "designation": l.designation, "unite": l.unite, "quantite": l.quantite,
             "prix_unitaire": l.prix_unitaire, "remise_pct": l.remise_pct} for l in devis.lignes]


# ------------------------------------------------------------------ liste, création, détail
@bp.get("")
@require_permission("factures.read")
def list_factures():
    page, par_page = pagination()
    now = utcnow()
    paid = (sa.select(sa.func.coalesce(sa.func.sum(Paiement.montant), 0))
            .where(Paiement.facture_id == Facture.id, Paiement.statut == "valide", Paiement.garage_id == Facture.garage_id)
            .correlate(Facture).scalar_subquery())
    filters = []
    statut = request.args.get("statut", "tous")
    if statut in ("brouillon", "emise", "annulee"):
        filters.append(Facture.statut == statut)
    elif statut == "impayees":
        filters += [Facture.statut == "emise", paid == 0]
    elif statut == "partielles":
        filters += [Facture.statut == "emise", paid > 0, paid < Facture.total_ttc]
    elif statut == "payees":
        filters += [Facture.statut == "emise", paid >= Facture.total_ttc]
    elif statut == "en_retard":
        filters += [Facture.statut == "emise", Facture.echeance < now, paid < Facture.total_ttc]
    for param, column in (("client_id", Facture.client_id), ("or_id", Facture.or_id), ("vehicule_id", Facture.vehicule_id)):
        if request.args.get(param):
            value = _uuid(request.args[param])
            if value is None:
                raise validation_error({param: "Identifiant invalide."})
            filters.append(column == value)
    q = (request.args.get("q") or "").strip()
    if q:
        pattern = v.like_pattern(q[:100])
        names = sa.select(Client.id).where(Client.garage_id == Facture.garage_id, sa.or_(
            *(c.ilike(pattern, escape="\\") for c in (Client.nom, Client.prenom, Client.raison_sociale))))
        filters.append(sa.or_(Facture.numero.ilike(pattern, escape="\\"), Facture.client_id.in_(names)))
    total = db.session.scalar(sa.select(sa.func.count(Facture.id)).where(*filters))
    rows = db.session.scalars(sa.select(Facture).where(*filters).order_by(Facture.created_at.desc())
                              .limit(par_page).offset((page - 1) * par_page)).all()
    clients = {}
    if rows:
        for c in db.session.scalars(sa.select(Client).where(Client.id.in_({f.client_id for f in rows}))):
            clients[c.id] = c
    paid_by = paid_map({f.id for f in rows})
    return jsonify({"factures": [facture_dict(f, paid_by.get(f.id, 0), clients.get(f.client_id), with_lignes=False) for f in rows],
                    "total": total, "page": page, "par_page": par_page})


@bp.post("")
@require_permission("factures.create")
def create_facture():
    """Crée un brouillon : vide, ou à partir d'un devis accepté et/ou d'un ordre de réparation (lignes recopiées du devis)."""
    data = json_body()
    garage = _garage()
    errors = {}
    ordre = devis = None
    if data.get("or_id"):
        ordre = _one(OrdreReparation, _uuid(data["or_id"]))
        if ordre is None:
            errors["or_id"] = "Ordre de réparation introuvable."
        elif ordre.statut == "annule":
            errors["or_id"] = "Cet ordre de réparation est annulé."
    if data.get("devis_id"):
        devis = _one(Devis, _uuid(data["devis_id"]))
        if devis is None:
            errors["devis_id"] = "Devis introuvable."
        elif devis.statut != "accepte":
            errors["devis_id"] = "Seul un devis accepté peut être facturé."
    if devis is not None and ordre is None and devis.or_id:
        ordre = _one(OrdreReparation, devis.or_id)
    if devis is None and ordre is not None and "lignes" not in data:  # dernier devis accepté de l'ordre
        devis = db.session.scalar(sa.select(Devis).where(Devis.or_id == ordre.id, Devis.statut == "accepte")
                                  .order_by(Devis.accepte_le.desc()).limit(1))
    if devis is not None and ordre is not None and devis.or_id and devis.or_id != ordre.id:
        errors["devis_id"] = "Ce devis concerne un autre ordre de réparation."
    client_ref = data.get("client_id") or (devis.client_id if devis else None) or (ordre.client_id if ordre else None)
    client = _find_client(client_ref, errors) if client_ref else None
    if not client_ref:
        errors["client_id"] = "Indiquez le client."
    if client is not None:
        for source, field in ((devis, "devis_id"), (ordre, "or_id")):
            if source is not None and source.client_id != client.id:
                errors[field] = "Ce document concerne un autre client."
    vehicule = None
    if data.get("vehicule_id"):
        vehicule = _find_vehicule(data["vehicule_id"], errors)
    elif ordre is not None or devis is not None:
        vehicule = _one(Vehicule, (ordre.vehicule_id if ordre else None) or (devis.vehicule_id if devis else None))
    items = _parse_lignes(data["lignes"], garage.devise_decimales, errors) if "lignes" in data else (
        _items_from_devis(devis) if devis is not None else [])
    remise = _remise(data, errors) if "remise_globale" in data else (devis.remise_globale if devis is not None else Decimal(0))
    conditions = v.long_text(data, "conditions", errors, label="Les conditions") if "conditions" in data else DEFAULT_CONDITIONS
    if errors:
        raise validation_error(errors)
    twin = _existing_invoice(ordre.id if ordre else None, devis.id if devis else None)
    if twin is not None:
        raise ApiError("Une facture existe déjà pour ce devis ou cet ordre de réparation.", 409, "facture_existe", {"facture_id": str(twin.id)})
    f = Facture(client_id=client.id, vehicule_id=vehicule.id if vehicule else None, or_id=ordre.id if ordre else None,
                devis_id=devis.id if devis else None, statut="brouillon", conditions=conditions, remise_globale=remise,
                cree_par_id=current_user.id)
    _snapshot_params(f, garage)
    _set_lignes(f, items)
    _recompute(f)
    db.session.add(f)
    db.session.flush()
    audit("facture.cree", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="facture", entity_id=f.id)
    _commit()
    return jsonify({"facture": _full(f)}), 201


@bp.get("/<uuid:facture_id>")
@require_permission("factures.read")
def get_facture(facture_id):
    f = _get(facture_id)
    payments = db.session.scalars(sa.select(Paiement).where(Paiement.facture_id == f.id).order_by(Paiement.date_paiement, Paiement.created_at)).all()
    receipts = {r.paiement_id: r for r in db.session.scalars(sa.select(Recu).where(Recu.paiement_id.in_({p.id for p in payments})))} if payments else {}
    avoir = db.session.scalar(sa.select(Avoir).where(Avoir.facture_id == f.id))
    return jsonify({
        "facture": _full(f),
        "paiements": [paiement_dict(p, receipts.get(p.id)) for p in payments],
        "avoir": ({"numero": avoir.numero, "date": avoir.emis_le.isoformat(), "motif": avoir.motif} if avoir else None),
    })


@bp.patch("/<uuid:facture_id>")
@require_permission("factures.update")
def update_facture(facture_id):
    f = _get(facture_id)
    _require_draft(f)
    data = json_body()
    garage = _garage()
    errors = {}
    if "client_id" in data:
        client = _find_client(data["client_id"], errors)
        if client:
            f.client_id = client.id
    if "vehicule_id" in data:
        if data["vehicule_id"] in (None, ""):
            f.vehicule_id = None
        else:
            vehicule = _find_vehicule(data["vehicule_id"], errors)
            if vehicule:
                f.vehicule_id = vehicule.id
    if "remise_globale" in data:
        f.remise_globale = _remise(data, errors)
    if "conditions" in data:
        f.conditions = v.long_text(data, "conditions", errors, label="Les conditions")
    items = _parse_lignes(data["lignes"], garage.devise_decimales, errors) if "lignes" in data else None
    if errors:
        db.session.rollback()
        raise validation_error(errors)
    _snapshot_params(f, garage)  # un brouillon suit le profil du garage (devise, TVA)
    if items is not None:
        _set_lignes(f, items)
    else:
        for l in f.lignes:
            l.total_ht = calc.line_total(l.quantite, l.prix_unitaire, l.remise_pct, f.devise_decimales)
    _recompute(f)
    audit("facture.modifiee", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="facture", entity_id=f.id)
    _commit()
    return jsonify({"facture": _full(f)})


@bp.delete("/<uuid:facture_id>")
@require_permission("factures.delete")
def delete_facture(facture_id):
    f = _get(facture_id)
    _require_draft(f)
    audit("facture.supprimee", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="facture", entity_id=f.id)
    db.session.delete(f)
    _commit()
    return jsonify({"message": "Brouillon supprimé."})


# ------------------------------------------------------------------ émission et annulation
@bp.post("/<uuid:facture_id>/emit")
@require_permission("factures.emit")
def emit_facture(facture_id):
    """Brouillon -> émise : numéro légal, montants et parties figés, empreinte, acomptes rattachés, ordre -> « facturé »."""
    f = _get(facture_id, lock=True)
    _require_draft(f)
    body = request.get_json(silent=True) if request.is_json else {}
    errors = {}
    days = v.integer(body or {}, "echeance_jours", errors, label="Le délai de paiement (jours)", minimum=0, maximum=365)
    if errors:
        raise validation_error(errors)
    days = current_app.config["FACTURE_ECHEANCE_JOURS"] if days is None else days
    if not f.lignes:
        raise validation_error({"lignes": "Ajoutez au moins une ligne avant d'émettre la facture."})
    client = _one(Client, f.client_id)
    if client is None or not client.actif:
        raise validation_error({"client_id": "Le client est introuvable ou archivé."})
    if _existing_invoice(f.or_id, f.devis_id, exclude=f.id) is not None:
        raise ApiError("Une autre facture existe déjà pour ce devis ou cet ordre de réparation.", 409, "facture_existe")
    garage = _garage()
    _snapshot_params(f, garage)
    for l in f.lignes:
        l.total_ht = calc.line_total(l.quantite, l.prix_unitaire, l.remise_pct, f.devise_decimales)
    _recompute(f)
    if f.total_ttc <= 0:
        raise validation_error({"lignes": "Le total de la facture doit être supérieur à zéro."})
    acomptes = []
    if f.or_id:
        acomptes = db.session.scalars(sa.select(Paiement).where(Paiement.or_id == f.or_id, Paiement.facture_id.is_(None),
                                                                Paiement.statut == "valide")).all()
        advance = sum((Decimal(a.montant) for a in acomptes), Decimal(0))
        if advance > Decimal(f.total_ttc):
            raise ApiError(f"Les acomptes déjà encaissés ({advance}) dépassent le total de la facture.", 409, "acomptes_excessifs")
    vehicule = _one(Vehicule, f.vehicule_id)
    now = utcnow()
    f.numero = next_number("FAC", garage.id)
    f.statut, f.emise_le, f.echeance = "emise", now, due_date(days)
    f.snapshot = build_snapshot(garage, client, vehicule)
    f.hash_integrite = compute_hash(f)
    for acompte in acomptes:
        acompte.facture_id = f.id  # les acomptes de l'ordre deviennent des paiements de la facture
    if f.or_id:
        ordre = _one(OrdreReparation, f.or_id)
        if ordre is not None:
            change_status(ordre, "facture", current_user.id, f"Facture {f.numero} émise", auto=True)
    audit("facture.emise", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="facture", entity_id=f.id,
          details={"numero": f.numero})
    _commit()
    return jsonify({"facture": _full(f)})


@bp.post("/<uuid:facture_id>/cancel")
@require_permission("factures.cancel")
def cancel_facture(facture_id):
    """Annule une facture émise par un AVOIR total (la facture elle-même ne change pas). Impossible si des paiements sont encaissés."""
    f = _get(facture_id, lock=True)
    if f.statut != "emise":
        raise ApiError("Seule une facture émise peut être annulée par un avoir.", 409, "statut_invalide")
    errors = {}
    motif = v.text(json_body(), "motif", errors, max_len=255, label="Le motif")
    if errors:
        raise validation_error(errors)
    if paid_amount(f.id) > 0:
        raise ApiError("Des paiements sont encaissés sur cette facture : annulez-les d'abord (remboursement).", 409, "paiements_existants")
    now = utcnow()
    db.session.add(Avoir(facture_id=f.id, numero=next_number("AV", current_user.garage_id), motif=motif, devise=f.devise,
                         total_ht=f.total_ht, total_tva=f.total_tva, total_ttc=f.total_ttc, emis_le=now, cree_par_id=current_user.id))
    f.statut, f.annulee_le, f.motif_annulation = "annulee", now, motif
    audit("facture.annulee", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="facture", entity_id=f.id,
          details={"motif": motif})
    _commit()
    return jsonify({"facture": _full(f)})


# ------------------------------------------------------------------ PDF et vérification
def pdf_doc(f, garage, mode="facture", avoir=None):
    """Contenu du PDF. Une facture émise utilise ses données FIGÉES (snapshot), jamais l'état actuel du garage ou du client."""
    snap = f.snapshot if f.statut != "brouillon" and f.snapshot else None
    client, vehicule = _one(Client, f.client_id), _one(Vehicule, f.vehicule_id)
    g = snap["garage"] if snap else {"nom_garage": garage.nom_garage, "adresse": garage.adresse, "ville": garage.ville,
                                      "telephone": garage.telephone, "email": garage.email, "ifu": garage.ifu, "rccm": garage.rccm,
                                      "logo_url": garage.logo_url}
    c = snap["client"] if snap else {"nom_affiche": client.nom_affiche, "adresse": client.adresse, "telephone": client.telephone,
                                     "email": client.email, "ifu": client.ifu}
    veh = snap["vehicule"] if snap else ({"libelle": f"{vehicule.marque} {vehicule.modele}", "immatriculation": vehicule.immatriculation,
                                          "kilometrage": vehicule.kilometrage_actuel} if vehicule else None)
    payments = db.session.scalars(sa.select(Paiement).where(Paiement.facture_id == f.id, Paiement.statut == "valide")
                                  .order_by(Paiement.date_paiement)).all()
    paid = sum((Decimal(p.montant) for p in payments), Decimal(0))
    doc = {
        "mode": mode, "statut": f.statut, "numero": avoir.numero if avoir else f.numero, "facture_numero": f.numero,
        "date": avoir.emis_le if avoir else f.emise_le, "echeance": f.echeance, "garage": g, "client": c, "vehicule": veh,
        "devise": f.devise, "decimales": f.devise_decimales, "tva_active": f.tva_active, "tva_taux": f.tva_taux,
        "sous_total": f.sous_total_ht, "remise": f.remise_globale, "total_ht": f.total_ht, "total_tva": f.total_tva, "total_ttc": f.total_ttc,
        "lignes": [{"designation": l.designation, "type": l.type, "unite": l.unite, "quantite": l.quantite,
                    "prix_unitaire": l.prix_unitaire, "remise_pct": l.remise_pct, "total_ht": l.total_ht} for l in f.lignes],
        "conditions": f.conditions, "paye": paid, "reste": Decimal(f.total_ttc) - paid, "motif": avoir.motif if avoir else None,
        "paiements": [{"date": p.date_paiement, "moyen": p.moyen, "reference": p.reference_transaction, "montant": p.montant} for p in payments],
        "hash": f.hash_integrite,
    }
    other = db.session.scalar(sa.select(Avoir).where(Avoir.facture_id == f.id))
    doc["avoir"] = {"numero": other.numero, "date": other.emis_le} if other else None
    return doc


@bp.get("/<uuid:facture_id>/pdf")
@require_permission("factures.read")
def facture_pdf(facture_id):
    f = _get(facture_id)
    doc = pdf_doc(f, _garage())
    return pdf_response(render_facture_pdf(doc, logo_for(doc["garage"])), f"Facture-{f.numero}" if f.numero else "Facture-brouillon")


@bp.get("/<uuid:facture_id>/avoir/pdf")
@require_permission("factures.read")
def avoir_pdf(facture_id):
    f = _get(facture_id)
    avoir = db.session.scalar(sa.select(Avoir).where(Avoir.facture_id == f.id))
    if avoir is None:
        raise ApiError("Aucun avoir pour cette facture.", 404, "avoir_introuvable")
    doc = pdf_doc(f, _garage(), mode="avoir", avoir=avoir)
    return pdf_response(render_facture_pdf(doc, logo_for(doc["garage"])), avoir.numero)


@bp.get("/<uuid:facture_id>/verify")
@require_permission("factures.read")
def verify_facture(facture_id):
    """Recalcule l'empreinte de la facture émise et la compare à celle enregistrée à l'émission."""
    f = _get(facture_id)
    if not f.hash_integrite:
        raise ApiError("Cette facture n'est pas émise.", 409, "statut_invalide")
    return jsonify({"integre": compute_hash(f) == f.hash_integrite, "empreinte": f.hash_integrite, "numero": f.numero})
