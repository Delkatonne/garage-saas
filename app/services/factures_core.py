"""Règles communes de la facturation : empreinte, figeage des données, montants payés."""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal

import sqlalchemy as sa

from app.extensions import db
from app.models import Paiement, as_utc, utcnow

ZERO = Decimal(0)


def build_snapshot(garage, client, vehicule) -> dict:
    """Données du garage, du client et du véhicule telles qu'à l'émission : la facture ne change plus ensuite."""
    return {
        "garage": {"nom_garage": garage.nom_garage, "adresse": garage.adresse, "ville": garage.ville, "telephone": garage.telephone,
                   "email": garage.email, "ifu": garage.ifu, "rccm": garage.rccm, "logo_url": garage.logo_url},
        "client": {"nom_affiche": client.nom_affiche, "adresse": client.adresse, "telephone": client.telephone,
                   "email": client.email, "ifu": client.ifu},
        "vehicule": ({"libelle": f"{vehicule.marque} {vehicule.modele}", "immatriculation": vehicule.immatriculation,
                      "vin": vehicule.vin, "kilometrage": vehicule.kilometrage_actuel} if vehicule else None),
    }


def _dec(value) -> str:
    return f"{Decimal(value):.3f}"


def compute_hash(f) -> str:
    """Empreinte SHA-256 du contenu légal de la facture émise (numéro, date, montants, lignes, parties)."""
    payload = {
        "numero": f.numero, "emise_le": as_utc(f.emise_le).isoformat(), "devise": f.devise, "tva_active": bool(f.tva_active),
        "tva_taux": _dec(f.tva_taux), "client_id": str(f.client_id),
        "totaux": [_dec(f.sous_total_ht), _dec(f.remise_globale), _dec(f.total_ht), _dec(f.total_tva), _dec(f.total_ttc)],
        "lignes": [[l.position, l.type, l.designation, l.unite, _dec(l.quantite), _dec(l.prix_unitaire), _dec(l.remise_pct), _dec(l.total_ht)]
                   for l in f.lignes],
        "snapshot": f.snapshot,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def paid_amount(facture_id) -> Decimal:
    total = db.session.scalar(sa.select(sa.func.coalesce(sa.func.sum(Paiement.montant), 0)).where(
        Paiement.facture_id == facture_id, Paiement.statut == "valide"))
    return Decimal(total or 0)


def paid_map(facture_ids) -> dict:
    if not facture_ids:
        return {}
    rows = db.session.execute(
        sa.select(Paiement.facture_id, sa.func.sum(Paiement.montant))
        .where(Paiement.facture_id.in_(list(facture_ids)), Paiement.statut == "valide").group_by(Paiement.facture_id)).all()
    return {fid: Decimal(total or 0) for fid, total in rows}


def payment_status(f, paid) -> str:
    """brouillon | annulee | payee | partielle | en_retard | impayee."""
    if f.statut != "emise":
        return f.statut
    paid = Decimal(paid or 0)
    if paid >= Decimal(f.total_ttc):
        return "payee"
    if f.echeance and as_utc(f.echeance) < utcnow():
        return "en_retard"
    return "partielle" if paid > 0 else "impayee"


def due_date(days: int):
    return utcnow() + timedelta(days=days)
