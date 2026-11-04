"""Devis, lignes de devis et séquences de numérotation (Phase 2, étape 2)."""
from sqlalchemy import DateTime, ForeignKey, Index, Uuid

from app.extensions import db
from .base import TenantMixin, Timestamps, UUIDPk, as_utc, utcnow

DEVIS_STATUTS = ("brouillon", "envoye", "accepte", "refuse", "expire", "remplace")
LIGNE_TYPES = ("main_oeuvre", "piece", "forfait", "consommable", "autre")


class SequenceDocument(UUIDPk, TenantMixin, db.Model):
    """Compteur de numérotation par garage, type (DEV, FAC...) et année : incrémenté sous verrou, sans trous."""

    __tablename__ = "sequences_documents"

    type = db.Column(db.String(10), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    dernier_numero = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (Index("uq_sequences_garage_type_annee", "garage_id", "type", "annee", unique=True),)


class Devis(UUIDPk, TenantMixin, Timestamps, db.Model):
    __tablename__ = "devis"

    numero = db.Column(db.String(40))  # attribué à l'envoi (un brouillon n'a pas de numéro : pas de trou)
    version = db.Column(db.Integer, nullable=False, default=1)
    devis_parent_id = db.Column(Uuid, ForeignKey("devis.id"))
    client_id = db.Column(Uuid, ForeignKey("clients.id"), nullable=False, index=True)
    vehicule_id = db.Column(Uuid, ForeignKey("vehicules.id"), index=True)
    statut = db.Column(db.String(20), nullable=False, default="brouillon")
    date_emission = db.Column(DateTime(timezone=True))
    date_validite = db.Column(DateTime(timezone=True))

    # Paramètres monétaires figés à l'envoi (un brouillon suit le profil du garage)
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

    token_public_hash = db.Column(db.String(64))  # empreinte du lien client (le lien lui-même n'est jamais stocké)
    accepte_le = db.Column(DateTime(timezone=True))
    acceptation_nom = db.Column(db.String(120))
    acceptation_mode = db.Column(db.String(20))  # "atelier" (saisi par le garage) ou "lien" (par le client)
    acceptation_ip = db.Column(db.String(45))
    refuse_le = db.Column(DateTime(timezone=True))
    refus_motif = db.Column(db.String(255))
    cree_par_id = db.Column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    lignes = db.relationship("DevisLigne", order_by="DevisLigne.position", cascade="all, delete-orphan",
                             lazy="selectin")

    @property
    def statut_effectif(self) -> str:
        """Un devis envoyé dont la validité est dépassée est "expire" (calculé, pas besoin de tâche planifiée)."""
        if self.statut == "envoye" and self.date_validite and as_utc(self.date_validite) < utcnow():
            return "expire"
        return self.statut

    __table_args__ = (
        Index("uq_devis_garage_numero", "garage_id", "numero", unique=True),
        Index("ix_devis_garage_statut", "garage_id", "statut"),
        Index("uq_devis_token", "token_public_hash", unique=True),
    )


class DevisLigne(UUIDPk, TenantMixin, db.Model):
    __tablename__ = "devis_lignes"

    devis_id = db.Column(Uuid, ForeignKey("devis.id", ondelete="CASCADE"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False, default="main_oeuvre")
    designation = db.Column(db.String(200), nullable=False)
    unite = db.Column(db.String(20))
    quantite = db.Column(db.Numeric(10, 2), nullable=False)
    prix_unitaire = db.Column(db.Numeric(14, 3), nullable=False)
    remise_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    total_ht = db.Column(db.Numeric(14, 3), nullable=False, default=0)
