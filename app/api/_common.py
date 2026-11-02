"""Petits utilitaires partagés par les routes API métier."""
from flask import request

from app.errors import ApiError


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Corps JSON attendu.", 400, "requete_invalide")
    return data


def pagination(default=20, maximum=100):
    def _int(name, fallback):
        try:
            return int(request.args.get(name, fallback))
        except (TypeError, ValueError):
            return fallback

    page = max(1, _int("page", 1))
    par_page = min(maximum, max(1, _int("par_page", default)))
    return page, par_page
