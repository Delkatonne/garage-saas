"""Factures, paiements, reçus et avoirs (Phase 2, étape 4)."""
from sqlalchemy import DateTime, ForeignKey, Index, Uuid, event, inspect
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.extensions import db
from .base import TenantMixin, Timestamps, UUIDPk, utcnow

FACTURE_STATUTS = ("brouillon", "emise", "annulee")
MOYENS_PAIEMENT = ("especes", "momo_mtn", "momo_moov", "momo_celtiis", "virement", "carte", "cheque", "autre")
MOYEN_LABELS = {"especes": "Espèces", "momo_mtn": "MTN MoMo", "momo_moov": "Moov Money", "momo_celtiis": "Celtiis Cash",
                "virement": "Virement", "carte": "Carte bancaire", "cheque": "Chèque", "autre": "Autre"}


class Facture(UUIDPk, TenantMixin, Timestamps, db.Model):
    __tablename__ = "factures"

    numero = db.Column(db.String(40))  # attribué à l'émission : un brouillon n'a pas de numéro (pas de trou dans la séquence)
    or_id = db.Column(Uuid, ForeignKey("ordres_reparation.id"), index=True)
    devis_id = db.Column(Uuid, ForeignKey("devis.id"), index=True)
    client_id = db.Column(Uuid, ForeignKey("clients.id"), nullable=False, index=True)
    vehicule_id = db.Column(Uuid, ForeignKey("vehicules.id"), index=True)
    statut = db.Column(db.String(20), nullable=False, default="brouillon")
    emise_le = db.Column(DateTime(timezone=True))
    echeance = db.Column(DateTime(timezone=True))

    devise = db.Column(db.String(3), nullable=False)
    devise_decimales = db.Column(db.Integer, nullable=False)
    tva_active = db.Column(db.Boolean, nullable=False, default=False)
    tva_taux = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    sous_total_ht = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    remise_globale = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    total_ht = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    total_tva = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    total_ttc = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    conditions = db.Column(db.Text)

    snapshot = db.Column(db.JSON)          # garage, client, véhicule tels qu'à l'émission (figés)
    hash_integrite = db.Column(db.String(64))  # empreinte SHA-256 du document émis
    annulee_le = db.Column(DateTime(timezone=True))
    motif_annulation = db.Column(db.String(255))
    cree_par_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    lignes = db.relationship("FactureLigne", order_by="FactureLigne.position", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("uq_factures_garage_numero", "garage_id", "numero", unique=True),
        Index("ix_factures_garage_statut", "garage_id", "statut"),
    )


class FactureLigne(UUIDPk, TenantMixin, db.Model):
    __tablename__ = "facture_lignes"

    facture_id = db.Column(Uuid, ForeignKey("factures.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False, default="main_oeuvre")
    designation = db.Column(db.String(200), nullable=False)
    unite = db.Column(db.String(20))
    quantite = db.Column(db.Numeric(10, 2), nullable=False)
    prix_unitaire = db.Column(db.Numeric(14, 3), nullable=False)
    remise_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    total_ht = db.Column(db.Numeric(14, 3), nullable=False, default=0)


class Paiement(UUIDPk, TenantMixin, Timestamps, db.Model):
    """Encaissement. Rattaché à une facture émise, ou à un ordre de réparation (acompte) puis rattaché à la facture à son émission."""

    __tablename__ = "paiements"

    facture_id = db.Column(Uuid, ForeignKey("factures.id"), index=True)
    or_id = db.Column(Uuid, ForeignKey("ordres_reparation.id"), index=True)
    client_id = db.Column(Uuid, ForeignKey("clients.id"), nullable=False, index=True)
    montant = db.Column(db.Numeric(14, 3), nullable=False)
    devise = db.Column(db.String(3), nullable=False)
    moyen = db.Column(db.String(20), nullable=False)
    reference_transaction = db.Column(db.String(100))
    date_paiement = db.Column(DateTime(timezone=True), nullable=False, default=utcnow)
    encaisse_par_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    statut = db.Column(db.String(10), nullable=False, default="valide")  # valide | annule
    motif_annulation = db.Column(db.String(255))
    annule_le = db.Column(DateTime(timezone=True))
    idempotency_key = db.Column(db.String(80))  # évite le double encaissement si la requête est renvoyée (réseau instable)

    __table_args__ = (
        Index("uq_paiements_garage_idem", "garage_id", "idempotency_key", unique=True),
        Index("ix_paiements_garage_date", "garage_id", "date_paiement"),
    )


class Recu(UUIDPk, TenantMixin, db.Model):
    """Reçu de paiement, créé avec chaque paiement ; son contenu est figé (snapshot)."""

    __tablename__ = "recus"

    numero = db.Column(db.String(40), nullable=False)
    paiement_id = db.Column(Uuid, ForeignKey("paiements.id"), nullable=False)
    solde_restant = db.Column(db.Numeric(14, 3))  # None pour un acompte versé avant la facture
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("uq_recus_garage_numero", "garage_id", "numero", unique=True),
        Index("uq_recus_paiement", "paiement_id", unique=True),
    )


class Avoir(UUIDPk, TenantMixin, db.Model):
    """Avoir total : seule manière de « corriger » une facture émise (qui, elle, ne change jamais)."""

    __tablename__ = "avoirs"

    numero = db.Column(db.String(40), nullable=False)
    facture_id = db.Column(Uuid, ForeignKey("factures.id"), nullable=False)
    motif = db.Column(db.String(255), nullable=False)
    devise = db.Column(db.String(3), nullable=False)
    total_ht = db.Column(db.Numeric(14, 3), nullable=False)
    total_tva = db.Column(db.Numeric(14, 3), nullable=False)
    total_ttc = db.Column(db.Numeric(14, 3), nullable=False)
    emis_le = db.Column(DateTime(timezone=True), nullable=False, default=utcnow)
    cree_par_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        Index("uq_avoirs_garage_numero", "garage_id", "numero", unique=True),
        Index("uq_avoirs_facture", "facture_id", unique=True),
    )


# ---------------------------------------------------------------- inviolabilité d'une facture émise
PROTEGES = ("numero", "or_id", "devis_id", "client_id", "vehicule_id", "emise_le", "echeance", "devise", "devise_decimales",
            "tva_active", "tva_taux", "sous_total_ht", "remise_globale", "total_ht", "total_tva", "total_ttc", "conditions",
            "snapshot", "hash_integrite")


def _locked(message="Une facture émise ne peut plus être modifiée ni supprimée : émettez un avoir."):
    return ApiError(message, 409, "document_verrouille")


def _was_issued(obj) -> bool:
    """Vrai si la facture était DÉJÀ émise avant les modifications en cours (l'émission elle-même reste permise)."""
    history = inspect(obj).attrs.emise_le.load_history()
    old = (history.deleted or history.unchanged or [None])[0]
    return old is not None


@event.listens_for(Session, "before_flush")
def _protect_issued_invoices(session, flush_context, instances):
    for obj in list(session.deleted):
        if isinstance(obj, Facture) and _was_issued(obj):
            raise _locked()
    for obj in list(session.dirty):
        if isinstance(obj, Facture):
            if not _was_issued(obj):
                continue
            state = inspect(obj)
            if any(state.attrs[col].history.has_changes() for col in PROTEGES) or state.attrs.lignes.history.has_changes():
                raise _locked()
        elif isinstance(obj, FactureLigne) and obj.facture_id is not None and session.is_modified(obj):
            parent = session.get(Facture, obj.facture_id)  # lecture dans la session : pas de requête pendant le flush
            if parent is not None and _was_issued(parent):
                raise _locked()
