"""Commandes CLI : flask create-admin | flask purge-tokens"""
from datetime import datetime, timezone

import click
import sqlalchemy as sa
from flask import current_app

from .extensions import db
from .models import AuthToken, PlatformAdmin, RevokedToken
from .security import hash_password, password_problems


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--nom", prompt=True)
    @click.password_option()
    def create_admin(email, nom, password):
        """Crée un super-admin de la plateforme."""
        problems = password_problems(password, email)
        if problems:
            raise click.ClickException("Mot de passe trop faible : " + ", ".join(problems))
        email = email.strip().lower()
        if db.session.scalar(sa.select(PlatformAdmin.id).where(PlatformAdmin.email == email)):
            raise click.ClickException("Cet admin existe déjà.")
        db.session.add(PlatformAdmin(email=email, nom=nom, password_hash=hash_password(password)))
        db.session.commit()
        click.echo(f"Super-admin créé : {email}")

    @app.cli.command("purge-tokens")
    def purge_tokens():
        """Supprime les jetons expirés (à planifier chaque jour via un cron Render)."""
        now = datetime.now(timezone.utc)
        a = db.session.execute(sa.delete(RevokedToken).where(RevokedToken.expires_at < now)).rowcount
        b = db.session.execute(sa.delete(AuthToken).where(AuthToken.expires_at < now)).rowcount
        db.session.commit()
        click.echo(f"{a} jetons révoqués et {b} jetons à usage unique supprimés.")
