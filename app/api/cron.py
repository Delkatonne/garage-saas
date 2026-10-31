"""Routes appelées par les Cron Jobs Vercel (protégées par CRON_SECRET)."""
import hmac

from flask import Blueprint, current_app, jsonify, request

from app.errors import ApiError
from app.services.maintenance import purge_expired_tokens

bp = Blueprint("cron", __name__, url_prefix="/api/cron")


def _check_secret():
    secret = current_app.config.get("CRON_SECRET")
    if not secret:  # non configuré : la route n'existe pas
        raise ApiError("Introuvable.", 404, "introuvable")
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Bearer {secret}".encode()):
        raise ApiError("Accès refusé.", 401, "non_authentifie")


@bp.get("/purge-tokens")
def purge_tokens():
    _check_secret()
    revoked, one_time = purge_expired_tokens()
    return jsonify({"jetons_revoques": revoked, "jetons_usage_unique": one_time})
