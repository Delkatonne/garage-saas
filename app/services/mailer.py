"""Envoi d'emails (asynchrone en production, synchrone en test)."""
import threading

from flask import current_app
from flask_mail import Message

from app.extensions import mail


def _deliver(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception:  # noqa: BLE001 - un email raté ne doit jamais casser la requête
            app.logger.exception("Échec d'envoi d'email à %s", msg.recipients)


def send_mail(to: str, subject: str, text: str, html: str | None = None) -> None:
    app = current_app._get_current_object()
    msg = Message(subject=subject, recipients=[to], body=text, html=html)
    if app.testing:
        mail.send(msg)  # capturé par mail.record_messages()
        return
    if not app.config.get("MAIL_SERVER"):
        app.logger.warning("MAIL_SERVER non configuré. Email '%s' pour %s :\n%s", subject, to, text)
        return
    threading.Thread(target=_deliver, args=(app, msg), daemon=True).start()


def _link(path: str, token: str) -> str:
    return f"{current_app.config['APP_BASE_URL']}{path}?token={token}"


def send_verification_email(user, garage, raw_token: str) -> None:
    link = _link("/verifier-email", raw_token)
    text = (
        f"Bonjour {user.nom_complet},\n\n"
        f"Bienvenue ! Confirmez l'email du garage « {garage.nom_garage} » pour activer votre compte :\n{link}\n\n"
        "Ce lien est valable 24 heures. Si vous n'êtes pas à l'origine de cette inscription, ignorez ce message."
    )
    html = (
        f"<p>Bonjour {_esc(user.nom_complet)},</p>"
        f"<p>Bienvenue ! Confirmez l'email du garage « {_esc(garage.nom_garage)} » pour activer votre compte :</p>"
        f'<p><a href="{link}">Confirmer mon email</a></p>'
        "<p>Ce lien est valable 24 heures. Si vous n'êtes pas à l'origine de cette inscription, ignorez ce message.</p>"
    )
    send_mail(user.email, "Confirmez votre email", text, html)


def send_reset_email(user, raw_token: str) -> None:
    link = _link("/reinitialiser-mot-de-passe", raw_token)
    text = (
        f"Bonjour {user.nom_complet},\n\n"
        f"Pour choisir un nouveau mot de passe, ouvrez ce lien (valable 30 minutes, usage unique) :\n{link}\n\n"
        "Si vous n'avez rien demandé, ignorez ce message : votre mot de passe reste inchangé."
    )
    html = (
        f"<p>Bonjour {_esc(user.nom_complet)},</p>"
        f'<p>Pour choisir un nouveau mot de passe : <a href="{link}">réinitialiser mon mot de passe</a> '
        "(valable 30 minutes, usage unique).</p>"
        "<p>Si vous n'avez rien demandé, ignorez ce message : votre mot de passe reste inchangé.</p>"
    )
    send_mail(user.email, "Réinitialisation de votre mot de passe", text, html)


def _esc(value: str) -> str:
    from markupsafe import escape

    return str(escape(value))
