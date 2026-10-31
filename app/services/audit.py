from flask import has_request_context, request

from app.extensions import db
from app.models import AuditLog


def audit(action, *, garage_id, user_id=None, entity_type=None, entity_id=None, details=None):
    """Ajoute une ligne au journal d'audit (le commit est fait par l'appelant)."""
    ip = ua = None
    if has_request_context():
        ip = (request.remote_addr or "")[:45]
        ua = (request.headers.get("User-Agent") or "")[:255]
    db.session.add(
        AuditLog(
            garage_id=garage_id, user_id=user_id, action=action, entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None, details=details, ip=ip, user_agent=ua,
        )
    )
