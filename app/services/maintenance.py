"""Tâches de maintenance (commande CLI et Cron Vercel)."""
import sqlalchemy as sa

from app.extensions import db
from app.models import AuthToken, RevokedToken, utcnow
from app.tenancy import unscoped


def purge_expired_tokens() -> tuple[int, int]:
    """Supprime les jetons expirés. Retourne (jetons révoqués, jetons à usage unique) supprimés."""
    now = utcnow()
    with unscoped():  # tâche globale, sans garage courant
        revoked = db.session.execute(sa.delete(RevokedToken).where(RevokedToken.expires_at < now)).rowcount
        one_time = db.session.execute(sa.delete(AuthToken).where(AuthToken.expires_at < now)).rowcount
        db.session.commit()
    return revoked, one_time
