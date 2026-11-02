from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import (
    create_access_token, create_refresh_token, current_user, decode_token, get_jwt,
    jwt_required, set_access_cookies, set_refresh_cookies, unset_jwt_cookies,
)

from app import validators as v
from app.errors import ApiError, validation_error
from app.extensions import db, limiter
from app.models import Garage, RevokedToken
from app.permissions import garage_user_required
from app.serializers import garage_dict, user_dict
from app.services import auth_service as svc
from app.services import storage
from app.tenancy import unscoped

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _payload():
    if request.mimetype in ("multipart/form-data", "application/x-www-form-urlencoded"):
        return request.form.to_dict()
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def issue_session(resp, user):
    claims = {"garage_id": str(user.garage_id), "role": user.role, "scope": "garage"}
    ident = f"u:{user.id}"
    set_access_cookies(resp, create_access_token(ident, additional_claims=claims))
    set_refresh_cookies(resp, create_refresh_token(ident, additional_claims=claims))


def _revoke(payload):
    with unscoped():
        if not db.session.query(RevokedToken.id).filter_by(jti=payload["jti"]).first():
            db.session.add(RevokedToken(
                jti=payload["jti"], token_type=payload["type"],
                expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc)))
            db.session.commit()


@bp.post("/register")
@limiter.limit("5 per hour")
def register():
    data, errors = _payload(), {}
    nom_garage = v.text(data, "nom_garage", errors, label="Le nom du garage")
    nom_chef = v.text(data, "nom_chef_garage", errors, label="Le nom du chef de garage")
    email = v.email(data, "email", errors)
    pwd = v.password(data, "mot_de_passe", errors, email or "")
    if pwd and data.get("confirmation_mot_de_passe") != pwd:
        errors["confirmation_mot_de_passe"] = "La confirmation ne correspond pas au mot de passe."
    logo_png = None
    logo = request.files.get("logo")
    if logo and logo.filename:
        try:
            logo_png = storage.validate_logo(logo)
        except storage.LogoError as exc:
            errors["logo"] = str(exc)
    if errors:
        raise validation_error(errors)
    svc.register_garage(nom_garage=nom_garage, nom_chef_garage=nom_chef, email=email,
                        password=pwd, logo_png=logo_png)
    if current_app.config["REQUIRE_EMAIL_VERIFICATION"]:
        return jsonify({"message": "Compte créé. Un email de confirmation vous a été envoyé : "
                                   "cliquez sur le lien pour activer votre compte."}), 201
    return jsonify({"message": "Compte créé. Vous pouvez vous connecter.", "redirect": "/connexion"}), 201


@bp.post("/verify-email")
@limiter.limit("20 per hour")
def verify_email():
    svc.verify_email(_payload().get("token"))
    return jsonify({"message": "Email confirmé. Vous pouvez vous connecter."})


@bp.post("/resend-verification")
@limiter.limit("5 per hour")
def resend_verification():
    errors = {}
    email = v.email(_payload(), "email", errors)
    if email:
        svc.resend_verification(email)
    return jsonify({"message": "Si un compte non confirmé existe pour cet email, un nouveau lien vient d'être envoyé."})


@bp.post("/login")
@limiter.limit("10 per minute")
def login():
    data = _payload()
    email, pwd = data.get("email"), data.get("mot_de_passe")
    if not isinstance(email, str) or not isinstance(pwd, str) or not email or not pwd:
        raise ApiError(svc.GENERIC_LOGIN_ERROR, 401, "identifiants_invalides")
    user, garage = svc.authenticate(email.strip().lower(), pwd)
    resp = jsonify({"utilisateur": user_dict(user), "garage": garage_dict(garage)})
    issue_session(resp, user)
    return resp


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    _revoke(get_jwt())  # rotation : un refresh token ne sert qu'une fois
    resp = jsonify({"message": "Session renouvelée."})
    issue_session(resp, current_user)
    return resp


@bp.post("/logout")
def logout():
    for cookie in ("access_token_cookie", "refresh_token_cookie"):
        raw = request.cookies.get(cookie)
        if raw:
            try:
                _revoke(decode_token(raw, allow_expired=True))
            except Exception:  # noqa: BLE001 - jeton déjà invalide : rien à révoquer
                pass
    resp = jsonify({"message": "Déconnecté."})
    unset_jwt_cookies(resp)
    return resp


@bp.post("/forgot-password")
@limiter.limit("5 per hour")
def forgot_password():
    errors = {}
    email = v.email(_payload(), "email", errors)
    if email:
        svc.request_password_reset(email)
    return jsonify({"message": "Si un compte correspond à cet email, un lien de réinitialisation "
                               "(valable 30 minutes) vient d'être envoyé."})


@bp.post("/reset-password")
@limiter.limit("10 per hour")
def reset_password():
    data, errors = _payload(), {}
    pwd = v.password(data, "mot_de_passe", errors)
    if pwd and data.get("confirmation_mot_de_passe") != pwd:
        errors["confirmation_mot_de_passe"] = "La confirmation ne correspond pas au mot de passe."
    if errors:
        raise validation_error(errors)
    svc.reset_password(data.get("token"), pwd)
    return jsonify({"message": "Mot de passe modifié. Vous pouvez vous connecter."})


@bp.post("/change-password")
@garage_user_required
def change_password():
    data, errors = _payload(), {}
    if not isinstance(data.get("ancien_mot_de_passe"), str) or not data["ancien_mot_de_passe"]:
        errors["ancien_mot_de_passe"] = "L'ancien mot de passe est obligatoire."
    pwd = v.password(data, "mot_de_passe", errors, current_user.email)
    if pwd and data.get("confirmation_mot_de_passe") != pwd:
        errors["confirmation_mot_de_passe"] = "La confirmation ne correspond pas au mot de passe."
    if pwd and pwd == data.get("ancien_mot_de_passe"):
        errors["mot_de_passe"] = "Le nouveau mot de passe doit être différent de l'ancien."
    if errors:
        raise validation_error(errors)
    svc.change_password(current_user, data["ancien_mot_de_passe"], pwd)
    resp = jsonify({"message": "Mot de passe modifié."})
    issue_session(resp, current_user)  # les anciens jetons sont invalidés, on rouvre la session
    return resp


@bp.get("/me")
@garage_user_required
def me():
    with unscoped():
        garage = db.session.get(Garage, current_user.garage_id)
    return jsonify({"utilisateur": user_dict(current_user), "garage": garage_dict(garage)})
