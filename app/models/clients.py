"""Clients, véhicules et historique des propriétaires (Phase 2, étape 1)."""
from sqlalchemy import DateTime, ForeignKey, Index, Uuid, text

from app.extensions import db
from .base import TenantMixin, Timestamps, UUIDPk, utcnow

CLIENT_TYPES = ("particulier", "entreprise", "flotte")
VEHICULE_TYPES = ("voiture", "moto", "scooter", "quad")
CARBURANTS = ("essence", "diesel", "hybride", "electrique", "gpl", "autre")


class Client(UUIDPk, TenantMixin, Timestamps, db.Model):
    __tablename__ = "clients"

    type = db.Column(db.String(20), nullable=False, default="particulier")
    nom = db.Column(db.String(120))            # nom de famille (particulier) ou nom du contact (entreprise/flotte)
    prenom = db.Column(db.String(120))
    raison_sociale = db.Column(db.String(160))  # entreprise / flotte
    telephone = db.Column(db.String(30))
    whatsapp = db.Column(db.String(30))
    email = db.Column(db.String(255))
    adresse = db.Column(db.String(255))
    ifu = db.Column(db.String(50))
    notes = db.Column(db.Text)
    actif = db.Column(db.Boolean, nullable=False, default=True)  # False = archivé (jamais supprimé : historique)

    __table_args__ = (
        Index("ix_clients_garage_telephone", "garage_id", "telephone"),
        Index("ix_clients_garage_nom", "garage_id", "nom"),
    )

    @property
    def nom_affiche(self) -> str:
        if self.type in ("entreprise", "flotte") and self.raison_sociale:
            return self.raison_sociale
        return " ".join(p for p in (self.prenom, self.nom) if p) or self.raison_sociale or "Sans nom"


class Vehicule(UUIDPk, TenantMixin, Timestamps, db.Model):
    __tablename__ = "vehicules"

    type = db.Column(db.String(20), nullable=False, default="voiture")
    marque = db.Column(db.String(80), nullable=False)
    modele = db.Column(db.String(80), nullable=False)
    version = db.Column(db.String(80))
    immatriculation = db.Column(db.String(20))       # telle qu'affichée (majuscules)
    immatriculation_cle = db.Column(db.String(20))   # lettres et chiffres seulement : sert à l'unicité
    vin = db.Column(db.String(30))                   # VIN / numéro de châssis
    annee = db.Column(db.Integer)
    couleur = db.Column(db.String(40))
    carburant = db.Column(db.String(20))
    cylindree_cc = db.Column(db.Integer)
    kilometrage_actuel = db.Column(db.Integer)
    notes = db.Column(db.Text)
    actif = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("uq_vehicules_garage_immat", "garage_id", "immatriculation_cle", unique=True),
        Index("uq_vehicules_garage_vin", "garage_id", "vin", unique=True,
              postgresql_where=text("vin IS NOT NULL"), sqlite_where=text("vin IS NOT NULL")),
    )


class VehiculeProprietaire(UUIDPk, TenantMixin, db.Model):
    """Historique des propriétaires. `date_fin` NULL = propriétaire actuel (une seule ligne ouverte par véhicule)."""

    __tablename__ = "vehicule_proprietaires"

    vehicule_id = db.Column(Uuid, ForeignKey("vehicules.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = db.Column(Uuid, ForeignKey("clients.id"), nullable=False, index=True)
    date_debut = db.Column(DateTime(timezone=True), nullable=False, default=utcnow)
    date_fin = db.Column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_vehicule_proprietaire_ouvert", "vehicule_id", unique=True,
              postgresql_where=text("date_fin IS NULL"), sqlite_where=text("date_fin IS NULL")),
    )
