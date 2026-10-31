"""Commandes CLI : flask create-admin | flask purge-tokens"""
import click
import sqlalchemy as sa

from .extensions import db
from .models import PlatformAdmin
from .security import hash_password, password_problems
from .services.maintenance import purge_expired_tokens


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
        """Supprime les jetons expirés (le Cron Vercel appelle /api/cron/purge-tokens chaque jour)."""
        a, b = purge_expired_tokens()
        click.echo(f"{a} jetons révoqués et {b} jetons à usage unique supprimés.")
