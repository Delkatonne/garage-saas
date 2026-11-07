"""Ordres de réparation et historique de leurs statuts (Phase 2, étape 3)."""
from sqlalchemy import DateTime, ForeignKey, Index, Uuid

from app.extensions import db
from .base import TenantMixin, Timestamps, UUIDPk, utcnow

OR_STATUTS = ("en_attente", "diagnostic", "devis_envoye", "devis_accepte", "en_cours", "attente_pieces",
              "termine", "facture", "livre", "annule")
OR_FERMES = ("livre", "annule")

# Transitions autorisées. "facture" est réservé à la facturation (attribué automatiquement, jamais à la main).
OR_TRANSITIONS = {
    "en_attente": {"diagnostic", "devis_envoye", "devis_accepte", "en_cours", "annule"},
    "diagnostic": {"devis_envoye", "devis_accepte", "en_cours", "attente_pieces", "termine", "annule"},
    "devis_envoye": {"devis_accepte", "diagnostic", "annule"},
    "devis_accepte": {"en_cours", "attente_pieces", "annule"},
    "en_cours": {"attente_pieces", "termine", "annule"},
    "attente_pieces": {"en_cours", "annule"},
    "termine": {"en_cours", "livre", "facture"},
    "facture": {"livre"},
    "livre": set(),
    "annule": set(),
}


class OrdreReparation(UUIDPk, TenantMixin, Timestamps, db.Model):
    __tablename__ = "ordres_reparation"

    numero = db.Column(db.String(40), nullable=False)
    client_id = db.Column(Uuid, ForeignKey("clients.id"), nullable=False, index=True)
    vehicule_id = db.Column(Uuid, ForeignKey("vehicules.id"), nullable=False, index=True)
    statut = db.Column(db.String(20), nullable=False, default="en_attente")
    urgent = db.Column(db.Boolean, nullable=False, default=False)
    motif = db.Column(db.String(255), nullable=False)
    symptomes = db.Column(db.Text)
    kilometrage_entree = db.Column(db.Integer)
    niveau_carburant = db.Column(db.Integer)  # 0 à 100 (%)
    etat_arrivee = db.Column(db.Text)  # rayures, accessoires laissés dans le véhicule...
    diagnostic = db.Column(db.Text)
    travaux_effectues = db.Column(db.Text)
    mecanicien_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    date_entree = db.Column(DateTime(timezone=True), nullable=False, default=utcnow)
    date_sortie_prevue = db.Column(DateTime(timezone=True))
    date_livraison = db.Column(DateTime(timezone=True))
    signature_nom = db.Column(db.String(120))   # autorisation de travaux donnée par le client
    signature_date = db.Column(DateTime(timezone=True))
    signature_ip = db.Column(db.String(45))
    cree_par_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (
        Index("uq_or_garage_numero", "garage_id", "numero", unique=True),
        Index("ix_or_garage_statut", "garage_id", "statut"),
    )


class OrStatutHistorique(UUIDPk, TenantMixin, db.Model):
    __tablename__ = "or_statut_historique"

    or_id = db.Column(Uuid, ForeignKey("ordres_reparation.id", ondelete="CASCADE"), nullable=False, index=True)
    ancien_statut = db.Column(db.String(20))
    nouveau_statut = db.Column(db.String(20), nullable=False)
    user_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    commentaire = db.Column(db.String(255))
    created_at = db.Column(DateTime(timezone=True), nullable=False, default=utcnow)
