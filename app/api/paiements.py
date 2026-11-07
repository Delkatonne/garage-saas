"""Paiements : encaissement (facture ou acompte d'ordre), reçu automatique, annulation, caisse du jour."""
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user
from sqlalchemy.exc import IntegrityError

from app import validators as v
from app.api._common import json_body, pagination
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import (MOYENS_PAIEMENT, Client, Facture, Garage, OrdreReparation, Paiement, Recu, utcnow)
from app.permissions import require_permission
from app.serializers import paiement_dict
from app.services.audit import audit
from app.services.factures_core import paid_amount
from app.services.numbering import next_number
from app.services.pdf_facture import logo_for, pdf_response, render_recu_pdf
from app.tenancy import unscoped

bp = Blueprint("paiements", __name__, url_prefix="/api/paiements")
KEY_RE = re.compile(r"^[A-Za-z0-9._\-]{8,80}$")


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _garage():
    with unscoped():
        return db.session.get(Garage, current_user.garage_id)


def _get(paiement_id) -> Paiement:
    p = db.session.scalar(sa.select(Paiement).where(Paiement.id == paiement_id))
    if p is None:
        raise ApiError("Paiement introuvable.", 404, "paiement_introuvable")
    return p


def _recu_of(p):
    return db.session.scalar(sa.select(Recu).where(Recu.paiement_id == p.id))


def _facture_brief(p):
    if not p.facture_id:
        return None
    f = db.session.scalar(sa.select(Facture).where(Facture.id == p.facture_id))
    paid = paid_amount(f.id)
    return {"id": str(f.id), "numero": f.numero, "total_ttc": float(f.total_ttc), "total_paye": float(paid),
            "reste_a_payer": float(Decimal(f.total_ttc) - paid)}


def _payload(p, replay=False):
    out = {"paiement": paiement_dict(p, _recu_of(p)), "facture": _facture_brief(p)}
    if replay:
        out["rejoue"] = True
    return out


def _parse_date(data, errors):
    value = data.get("date_paiement")
    if value in (None, ""):
        return utcnow()
    try:
        if not isinstance(value, str):
            raise ValueError
        day = date.fromisoformat(value[:10])
    except ValueError:
        errors["date_paiement"] = "La date du paiement est invalide (format AAAA-MM-JJ)."
        return None
    when = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    if when > utcnow() + timedelta(days=1):
        errors["date_paiement"] = "La date du paiement ne peut pas être dans le futur."
        return None
    return when


@bp.post("")
@require_permission("paiements.create")
def create_paiement():
    data = json_body()
    key = request.headers.get("Idempotency-Key")
    if key:
        if not KEY_RE.match(key):
            raise validation_error({"idempotency_key": "Clé d'idempotence invalide (8 à 80 caractères : lettres, chiffres, . _ -)."})
        existing = db.session.scalar(sa.select(Paiement).where(Paiement.idempotency_key == key))
        if existing is not None:  # requête renvoyée (réseau instable) : on retrouve le paiement, sans encaisser deux fois
            return jsonify(_payload(existing, replay=True)), 200
    garage = _garage()
    errors = {}
    has_facture, has_or = data.get("facture_id") not in (None, ""), data.get("or_id") not in (None, "")
    if has_facture == has_or:
        errors["facture_id"] = "Indiquez la facture OU l'ordre de réparation (acompte)."
    facture = ordre = None
    if has_facture:
        fid = _uuid(data["facture_id"])
        facture = db.session.scalar(sa.select(Facture).where(Facture.id == fid).with_for_update()) if fid else None  # verrou : pas de double encaissement
        if facture is None:
            errors["facture_id"] = "Facture introuvable."
    elif has_or:
        oid = _uuid(data["or_id"])
        ordre = db.session.scalar(sa.select(OrdreReparation).where(OrdreReparation.id == oid)) if oid else None
        if ordre is None:
            errors["or_id"] = "Ordre de réparation introuvable."
    decimals = facture.devise_decimales if facture is not None else garage.devise_decimales
    montant = None
    try:
        montant = v.decimal_value(data.get("montant"), label="Le montant", minimum=str(Decimal(1).scaleb(-decimals)),
                                  maximum="1000000000", places=decimals)
    except ValueError as exc:
        errors["montant"] = str(exc)
    moyen = v.choice(data, "moyen", errors, MOYENS_PAIEMENT, label="Le moyen de paiement", required=True)
    reference = v.text(data, "reference_transaction", errors, max_len=100, required=False, label="La référence")
    when = _parse_date(data, errors)
    if errors:
        raise validation_error(errors)

    reste = None
    if facture is not None:
        if facture.statut == "brouillon":
            raise ApiError("Émettez la facture avant d'enregistrer un paiement.", 409, "facture_non_emise")
        if facture.statut == "annulee":
            raise ApiError("Cette facture est annulée.", 409, "facture_annulee")
        reste = Decimal(facture.total_ttc) - paid_amount(facture.id)
        if reste <= 0:
            raise ApiError("Cette facture est déjà soldée.", 409, "facture_soldee")
        if montant > reste:
            raise validation_error({"montant": f"Le montant dépasse le reste à payer ({reste})."})
        client_id, devise, or_id = facture.client_id, facture.devise, facture.or_id
    else:
        if ordre.statut == "annule":
            raise ApiError("Cet ordre de réparation est annulé.", 409, "or_clos")
        issued = db.session.scalar(sa.select(Facture).where(Facture.or_id == ordre.id, Facture.statut == "emise").limit(1))
        if issued is not None:
            raise ApiError("Une facture est déjà émise pour cet ordre : enregistrez le paiement sur la facture.", 409, "facture_existe")
        client_id, devise, or_id = ordre.client_id, garage.devise, ordre.id

    p = Paiement(facture_id=facture.id if facture is not None else None, or_id=or_id, client_id=client_id, montant=montant,
                 devise=devise, moyen=moyen, reference_transaction=reference, date_paiement=when,
                 encaisse_par_id=current_user.id, statut="valide", idempotency_key=key or None)
    db.session.add(p)
    db.session.flush()
    client = db.session.scalar(sa.select(Client).where(Client.id == client_id))
    solde = (reste - montant) if reste is not None else None
    snapshot = {
        "garage": {"nom_garage": garage.nom_garage, "adresse": garage.adresse, "ville": garage.ville, "telephone": garage.telephone,
                   "email": garage.email, "ifu": garage.ifu, "rccm": garage.rccm, "logo_url": garage.logo_url},
        "client": client.nom_affiche if client else "", "montant": str(montant), "devise": devise, "decimales": decimals, "moyen": moyen,
        "reference": reference, "date": when.isoformat(), "encaisse_par": current_user.nom_complet,
        "facture_numero": facture.numero if facture is not None else None,
        "total_facture": str(facture.total_ttc) if facture is not None else None,
        "or_numero": ordre.numero if ordre is not None else None,
    }
    db.session.add(Recu(paiement_id=p.id, numero=next_number("REC", garage.id), solde_restant=solde, snapshot=snapshot))
    audit("paiement.cree", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="paiement", entity_id=p.id,
          details={"montant": str(montant), "moyen": moyen})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = db.session.scalar(sa.select(Paiement).where(Paiement.idempotency_key == key)) if key else None
        if existing is not None:
            return jsonify(_payload(existing, replay=True)), 200
        raise ApiError("Conflit de données, réessayez.", 409, "conflit")
    return jsonify(_payload(p)), 201


@bp.get("")
@require_permission("paiements.read")
def list_paiements():
    page, par_page = pagination()
    filters = []
    statut = request.args.get("statut", "valide")
    if statut in ("valide", "annule"):
        filters.append(Paiement.statut == statut)
    for param, column in (("facture_id", Paiement.facture_id), ("or_id", Paiement.or_id), ("client_id", Paiement.client_id)):
        if request.args.get(param):
            value = _uuid(request.args[param])
            if value is None:
                raise validation_error({param: "Identifiant invalide."})
            filters.append(column == value)
    total = db.session.scalar(sa.select(sa.func.count(Paiement.id)).where(*filters))
    rows = db.session.scalars(sa.select(Paiement).where(*filters).order_by(Paiement.date_paiement.desc(), Paiement.created_at.desc())
                              .limit(par_page).offset((page - 1) * par_page)).all()
    receipts = {r.paiement_id: r for r in db.session.scalars(sa.select(Recu).where(Recu.paiement_id.in_({p.id for p in rows})))} if rows else {}
    return jsonify({"paiements": [paiement_dict(p, receipts.get(p.id)) for p in rows], "total": total, "page": page, "par_page": par_page})


@bp.get("/caisse")
@require_permission("paiements.read")
def caisse():
    """Encaissements d'une journée (UTC), par moyen de paiement."""
    raw = request.args.get("date")
    try:
        day = date.fromisoformat(raw) if raw else utcnow().date()
    except ValueError:
        raise validation_error({"date": "Date invalide (format AAAA-MM-JJ)."})
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    window = [Paiement.date_paiement >= start, Paiement.date_paiement < start + timedelta(days=1)]
    rows = db.session.execute(sa.select(Paiement.moyen, sa.func.sum(Paiement.montant), sa.func.count(Paiement.id))
                              .where(Paiement.statut == "valide", *window).group_by(Paiement.moyen)).all()
    cancelled = db.session.scalar(sa.select(sa.func.count(Paiement.id)).where(Paiement.statut == "annule", *window))
    garage = _garage()
    return jsonify({"date": day.isoformat(), "devise": garage.devise, "devise_decimales": garage.devise_decimales,
                    "total": float(sum((Decimal(t or 0) for _, t, _ in rows), Decimal(0))), "nombre": sum(n for _, _, n in rows),
                    "par_moyen": {moyen: float(Decimal(total or 0)) for moyen, total, _ in rows}, "annules": cancelled})


@bp.post("/<uuid:paiement_id>/cancel")
@require_permission("paiements.cancel")
def cancel_paiement(paiement_id):
    p = _get(paiement_id)
    if p.statut == "annule":
        raise ApiError("Ce paiement est déjà annulé.", 409, "statut_invalide")
    errors = {}
    motif = v.text(json_body(), "motif", errors, max_len=255, label="Le motif")
    if errors:
        raise validation_error(errors)
    p.statut, p.annule_le, p.motif_annulation = "annule", utcnow(), motif
    audit("paiement.annule", garage_id=current_user.garage_id, user_id=current_user.id, entity_type="paiement", entity_id=p.id,
          details={"motif": motif})
    db.session.commit()
    return jsonify(_payload(p))


@bp.get("/<uuid:paiement_id>/recu")
@require_permission("paiements.read")
def recu_pdf(paiement_id):
    p = _get(paiement_id)
    recu = _recu_of(p)
    snap = recu.snapshot
    doc = {**snap, "numero": recu.numero, "date": datetime.fromisoformat(snap["date"]), "montant": Decimal(snap["montant"]),
           "total_facture": Decimal(snap["total_facture"]) if snap.get("total_facture") else None,
           "solde_restant": recu.solde_restant if recu.solde_restant is not None else Decimal(0), "statut_paiement": p.statut}
    return pdf_response(render_recu_pdf(doc, logo_for(snap["garage"])), recu.numero)
