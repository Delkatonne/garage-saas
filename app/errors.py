"""Erreurs API uniformes (JSON) et pages d'erreur HTML."""
from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, message, status=400, code="erreur", details=None):
        super().__init__(message)
        self.message, self.status, self.code, self.details = message, status, code, details


def validation_error(errors: dict) -> ApiError:
    return ApiError("Certaines informations sont invalides.", 422, "validation_echouee", errors)


def _json(message, status, code, details=None):
    body = {"erreur": message, "code": code}
    if details:
        body["details"] = details
    return jsonify(body), status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(e):
        return _json(e.message, e.status, e.code, e.details)

    @app.errorhandler(HTTPException)
    def _http_error(e):
        if request.path.startswith("/api/"):
            messages = {
                404: "Ressource introuvable.",
                405: "Méthode non autorisée.",
                413: "Fichier ou requête trop volumineux.",
                429: "Trop de requêtes, réessayez plus tard.",
            }
            return _json(messages.get(e.code, e.description), e.code, f"http_{e.code}")
        return render_template("erreur.html", code=e.code, message=e.name), e.code

    @app.errorhandler(Exception)
    def _unhandled(e):
        app.logger.exception("Erreur non gérée")
        if request.path.startswith("/api/"):
            return _json("Erreur interne du serveur.", 500, "erreur_interne")
        return render_template("erreur.html", code=500, message="Erreur interne"), 500
