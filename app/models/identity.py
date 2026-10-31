"""Identité : garages, utilisateurs, administrateurs de la plateforme, jetons."""
from sqlalchemy import DateTime, Index, Uuid

from app.extensions import db
from .base import Timestamps, TenantMixin, UUIDPk, as_utc, utcnow

ROLES = ("owner", "receptionniste", "mecanicien", "magasinier", "comptable")
SUBSCRIPTION_STATUSES = ("essai", "actif", "suspendu", "expire")


class Garage(UUIDPk, Timestamps, db.Model):
    """Un garage = un tenant. (`created_at` = `date_creation` du cahier des charges.)"""

    __tablename__ = "garages"

    nom_garage = db.Column(db.String(120), nullable=False)
    nom_chef_garage = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    telephone = db.Column(db.String(30))
    adresse = db.Column(db.String(255))
    ville = db.Column(db.String(100))
    pays = db.Column(db.String(2), nullable=False, default="BJ")
    logo_url = db.Column(db.String(500))
    logo_public_id = db.Column(db.String(255))

    # Paramètres monétaires et fiscaux (configurables par garage)
    devise = db.Column(db.String(3), nullable=False, default="XOF")
    devise_decimales = db.Column(db.Integer, nullable=False, default=0)
    tva_active = db.Column(db.Boolean, nullable=False, default=False)
    tva_taux = db.Column(db.Numeric(5, 2), nullable=False, default=18)
    ifu = db.Column(db.String(50))
    rccm = db.Column(db.String(50))

    email_verifie = db.Column(db.Boolean, nullable=False, default=False)
    actif = db.Column(db.Boolean, nullable=False, default=True)
    statut_abonnement = db.Column(db.String(20), nullable=False, default="essai")
    essai_fin = db.Column(DateTime(timezone=True))
    abonnement_fin = db.Column(DateTime(timezone=True))

    @property
    def initiales(self) -> str:
        mots = [m for m in (self.nom_garage or "").split() if m]
        if not mots:
            return "G"
        if len(mots) == 1:
            return mots[0][:2].upper()
        return (mots[0][0] + mots[1][0]).upper()

    @property
    def motif_blocage(self):
        """None si l'accès est autorisé, sinon le message à afficher."""
        if not self.actif or self.statut_abonnement == "suspendu":
            return "Ce garage est suspendu. Contactez l'éditeur du logiciel."
        now = utcnow()
        if self.statut_abonnement == "expire":
            return "L'abonnement de ce garage a expiré. Contactez l'éditeur du logiciel."
        if self.statut_abonnement == "essai" and self.essai_fin and as_utc(self.essai_fin) <= now:
            return "La période d'essai est terminée. Contactez l'éditeur du logiciel."
        if self.statut_abonnement == "actif" and self.abonnement_fin and as_utc(self.abonnement_fin) <= now:
            return "L'abonnement de ce garage a expiré. Contactez l'éditeur du logiciel."
        return None

    @property
    def acces_autorise(self) -> bool:
        return self.motif_blocage is None


class User(UUIDPk, TenantMixin, Timestamps, db.Model):
    """Utilisateur d'un garage. Le compte créé à l'inscription a le rôle `owner`.

    L'email est unique sur toute la plateforme (connexion sans choix du garage).
    """

    __tablename__ = "users"

    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    nom_complet = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="owner")
    password_hash = db.Column(db.String(255), nullable=False)
    email_verifie = db.Column(db.Boolean, nullable=False, default=False)
    actif = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(DateTime(timezone=True))
    last_login_at = db.Column(DateTime(timezone=True))
    password_changed_at = db.Column(DateTime(timezone=True))


class PlatformAdmin(UUIDPk, Timestamps, db.Model):
    """Super-admin de la plateforme (back-office). Table globale, sans garage_id."""

    __tablename__ = "platform_admins"

    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    nom = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    actif = db.Column(db.Boolean, nullable=False, default=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(DateTime(timezone=True))
    password_changed_at = db.Column(DateTime(timezone=True))


class AuthToken(UUIDPk, TenantMixin, db.Model):
    """Jetons à usage unique (vérification d'email, réinitialisation). Seul le hash est stocké."""

    __tablename__ = "auth_tokens"

    user_id = db.Column(Uuid, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = db.Column(db.String(30), nullable=False)  # verify_email | reset_password
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(DateTime(timezone=True), nullable=False)
    used_at = db.Column(DateTime(timezone=True))
    created_at = db.Column(DateTime(timezone=True), default=utcnow, nullable=False)


class RevokedToken(UUIDPk, db.Model):
    """Liste de révocation des JWT (déconnexion, rotation des refresh tokens). Table technique globale."""

    __tablename__ = "revoked_tokens"

    jti = db.Column(db.String(64), nullable=False, unique=True, index=True)
    token_type = db.Column(db.String(10), nullable=False)
    expires_at = db.Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = db.Column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(UUIDPk, TenantMixin, db.Model):
    """Journal d'audit : qui a fait quoi, quand. Jamais modifié ni supprimé par l'application."""

    __tablename__ = "audit_logs"

    user_id = db.Column(Uuid, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(60))
    entity_id = db.Column(db.String(64))
    details = db.Column(db.JSON)
    ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    __table_args__ = (Index("ix_audit_garage_created", "garage_id", "created_at"),)
