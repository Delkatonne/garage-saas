"""Changements de statut d'un ordre de réparation : règles de transition et historique."""
import sqlalchemy as sa

from app.errors import ApiError
from app.extensions import db
from app.models import OR_TRANSITIONS, OrdreReparation, OrStatutHistorique, utcnow


def log_status(ordre, old, new, user_id=None, comment=None):
    db.session.add(OrStatutHistorique(garage_id=ordre.garage_id, or_id=ordre.id, ancien_statut=old, nouveau_statut=new, user_id=user_id,
                                      commentaire=(comment or None) and comment[:255]))


def change_status(ordre, new, user_id=None, comment=None, auto=False) -> bool:
    """Applique la transition. Manuelle : refusée avec une erreur claire si elle n'est pas permise.
    Automatique (devis envoyé/accepté) : ignorée silencieusement si elle n'est pas permise depuis le statut courant."""
    old = ordre.statut
    if new == old:
        return False
    if new not in OR_TRANSITIONS.get(old, set()):
        if auto:
            return False
        raise ApiError(f"Passage impossible de « {old} » à « {new} ».", 409, "transition_invalide")
    ordre.statut = new
    if new == "livre":
        ordre.date_livraison = utcnow()
    log_status(ordre, old, new, user_id, comment)
    return True


def auto_status_for_devis(devis, new_status, comment, user_id=None):
    """Un devis lié à un ordre de réparation fait avancer l'ordre (envoyé -> devis_envoye, accepté -> devis_accepte)."""
    if not devis.or_id:
        return
    ordre = db.session.scalar(sa.select(OrdreReparation).where(OrdreReparation.id == devis.or_id,
                                                               OrdreReparation.garage_id == devis.garage_id))
    if ordre is not None:
        change_status(ordre, new_status, user_id, comment, auto=True)
