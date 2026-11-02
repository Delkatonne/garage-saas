"""Logique d'authentification : inscription, connexion, vérification d'email, mot de passe."""
from datetime import timedelta

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.errors import ApiError
from app.extensions import db
from app.models import AuthToken, Garage, PlatformAdmin, User, as_utc, utcnow
from app.security import (
    DUMMY_HASH, hash_password, hash_token, needs_rehash, new_token, verify_password,
)
from app.tenancy import unscoped
from . import mailer, storage
from .audit import audit

GENERIC_LOGIN_ERROR = "Email ou mot de passe incorrect."


def _generic():
    return ApiError(GENERIC_LOGIN_ERROR, 401, "identifiants_invalides")


# ----------------------------------------------------------------- jetons à usage unique
def issue_token(user, purpose: str, ttl: timedelta) -> str:
    """Crée un jeton (invalide les précédents du même type) et retourne la valeur brute à envoyer."""
    db.session.execute(
        sa.update(AuthToken)
        .where(AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    raw, hashed = new_token()
    db.session.add(
        AuthToken(garage_id=user.garage_id, user_id=user.id, purpose=purpose,
                  token_hash=hashed, expires_at=utcnow() + ttl)
    )
    return raw


def consume_token(raw, purpose: str):
    """Valide et consomme un jeton de façon atomique (usage unique). Retourne l'utilisateur ou None."""
    if not isinstance(raw, str) or not raw or len(raw) > 200:
        return None
    with unscoped():
        tok = db.session.scalar(
            sa.select(AuthToken).where(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose)
        )
        if tok is None or tok.used_at is not None or as_utc(tok.expires_at) <= utcnow():
            return None
        claimed = db.session.execute(
            sa.update(AuthToken).where(AuthToken.id == tok.id, AuthToken.used_at.is_(None)).values(used_at=utcnow())
        )
        if claimed.rowcount != 1:  # consommé entre-temps par une autre requête
            db.session.rollback()
            return None
        return db.session.get(User, tok.user_id)


# ----------------------------------------------------------------- inscription
def register_garage(*, nom_garage, nom_chef_garage, email, password, logo_png=None):
    cfg = current_app.config
    with unscoped():
        taken = db.session.scalar(sa.select(Garage.id).where(Garage.email == email)) or db.session.scalar(
            sa.select(User.id).where(User.email == email)
        )
        if taken:
            raise ApiError("Cet email est déjà utilisé.", 409, "email_deja_utilise",
                           {"email": "Cet email est déjà utilisé."})
        garage = Garage(
            nom_garage=nom_garage, nom_chef_garage=nom_chef_garage, email=email,
            pays=cfg["DEFAULT_COUNTRY"], devise=cfg["DEFAULT_CURRENCY"],
            devise_decimales=cfg["DEFAULT_CURRENCY_DECIMALS"],
            statut_abonnement="essai", essai_fin=utcnow() + timedelta(days=cfg["TRIAL_DAYS"]),
        )
        db.session.add(garage)
        db.session.flush()
        user = User(garage_id=garage.id, email=email, nom_complet=nom_chef_garage, role="owner",
                    password_hash=hash_password(password), password_changed_at=utcnow())
        db.session.add(user)
        db.session.flush()
        raw = None
        if cfg["REQUIRE_EMAIL_VERIFICATION"]:
            raw = issue_token(user, "verify_email", cfg["EMAIL_VERIFY_TTL"])
        else:  # confirmation désactivée : le compte est utilisable tout de suite
            garage.email_verifie = True
            user.email_verifie = True
        audit("garage.inscription", garage_id=garage.id, user_id=user.id, entity_type="garage", entity_id=garage.id)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ApiError("Cet email est déjà utilisé.", 409, "email_deja_utilise",
                           {"email": "Cet email est déjà utilisé."})
        if logo_png:  # après le commit : un échec Cloudinary ne bloque pas l'inscription
            try:
                garage.logo_url, garage.logo_public_id = storage.save_logo(garage.id, logo_png)
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                current_app.logger.exception("Logo non enregistré à l'inscription")
        if raw:
            mailer.send_verification_email(user, garage, raw)
        return garage, user


def verify_email(raw_token):
    user = consume_token(raw_token, "verify_email")
    if user is None:
        raise ApiError("Ce lien de confirmation est invalide ou expiré.", 400, "lien_invalide")
    with unscoped():
        user.email_verifie = True
        garage = db.session.get(Garage, user.garage_id)
        if user.role == "owner" and garage.email == user.email:
            garage.email_verifie = True
        audit("auth.email_verifie", garage_id=user.garage_id, user_id=user.id)
        db.session.commit()
    return user


def resend_verification(email: str):
    with unscoped():
        user = db.session.scalar(sa.select(User).where(User.email == email))
        if user and user.actif and not user.email_verifie:
            raw = issue_token(user, "verify_email", current_app.config["EMAIL_VERIFY_TTL"])
            db.session.commit()
            mailer.send_verification_email(user, db.session.get(Garage, user.garage_id), raw)


# ----------------------------------------------------------------- connexion
def _check_lock_and_password(account, password):
    """Logique commune utilisateurs/admins. Retourne True si le mot de passe est accepté."""
    cfg = current_app.config
    now = utcnow()
    if account.locked_until and as_utc(account.locked_until) > now:
        verify_password(account.password_hash, password)  # égalise le temps de réponse
        return False
    if verify_password(account.password_hash, password):
        account.failed_attempts = 0
        account.locked_until = None
        return True
    account.failed_attempts += 1
    if account.failed_attempts >= cfg["MAX_FAILED_LOGINS"]:
        account.locked_until = now + cfg["LOCKOUT_DURATION"]
        account.failed_attempts = 0
    return False


def authenticate(email: str, password: str):
    with unscoped():
        user = db.session.scalar(sa.select(User).where(User.email == email))
        if user is None:
            verify_password(DUMMY_HASH, password)
            raise _generic()
        if not _check_lock_and_password(user, password):
            audit("auth.connexion_echec", garage_id=user.garage_id, user_id=user.id)
            db.session.commit()
            raise _generic()
        # Mot de passe correct : on peut donner des raisons précises.
        db.session.commit()
        if not user.actif:
            raise ApiError("Ce compte est désactivé.", 403, "compte_desactive")
        garage = db.session.get(Garage, user.garage_id)
        if not user.email_verifie:
            if current_app.config["REQUIRE_EMAIL_VERIFICATION"]:
                raise ApiError("Veuillez confirmer votre email avant de vous connecter.", 403, "email_non_verifie")
            # confirmation désactivée : on régularise les comptes créés avant ce changement
            user.email_verifie = True
            if user.role == "owner" and garage.email == user.email:
                garage.email_verifie = True
            db.session.commit()
        if (reason := garage.motif_blocage):
            raise ApiError(reason, 403, "garage_inactif")
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = utcnow()
        audit("auth.connexion", garage_id=user.garage_id, user_id=user.id)
        db.session.commit()
        return user, garage


def authenticate_admin(email: str, password: str):
    with unscoped():
        admin = db.session.scalar(sa.select(PlatformAdmin).where(PlatformAdmin.email == email))
        if admin is None:
            verify_password(DUMMY_HASH, password)
            raise _generic()
        ok = _check_lock_and_password(admin, password)
        db.session.commit()
        if not ok or not admin.actif:
            raise _generic()
        return admin


# ----------------------------------------------------------------- mots de passe
def request_password_reset(email: str):
    with unscoped():
        user = db.session.scalar(sa.select(User).where(User.email == email))
        if user and user.actif and (user.email_verifie or not current_app.config["REQUIRE_EMAIL_VERIFICATION"]):
            raw = issue_token(user, "reset_password", current_app.config["PASSWORD_RESET_TTL"])
            audit("auth.reinitialisation_demandee", garage_id=user.garage_id, user_id=user.id)
            db.session.commit()
            mailer.send_reset_email(user, raw)


def _set_password(user, new_password):
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()  # invalide tous les JWT émis avant
    user.failed_attempts = 0
    user.locked_until = None


def reset_password(raw_token, new_password):
    user = consume_token(raw_token, "reset_password")
    if user is None:
        raise ApiError("Ce lien est invalide, expiré ou déjà utilisé.", 400, "lien_invalide")
    with unscoped():
        _set_password(user, new_password)
        audit("auth.mot_de_passe_reinitialise", garage_id=user.garage_id, user_id=user.id)
        db.session.commit()
    return user


def change_password(user, old_password, new_password):
    if not verify_password(user.password_hash, old_password):
        raise ApiError("L'ancien mot de passe est incorrect.", 400, "ancien_mot_de_passe_incorrect",
                       {"ancien_mot_de_passe": "L'ancien mot de passe est incorrect."})
    _set_password(user, new_password)
    audit("auth.mot_de_passe_change", garage_id=user.garage_id, user_id=user.id)
    db.session.commit()
