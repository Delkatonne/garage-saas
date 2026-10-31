"""Pages HTML (Jinja) + PWA. La logique passe par l'API JSON (fetch)."""
import os

from flask import Blueprint, current_app, jsonify, render_template, send_from_directory
import sqlalchemy as sa

from app.extensions import db

bp = Blueprint("web", __name__)

PAGES = {
    "/": ("index.html", "accueil"),
    "/inscription": ("inscription.html", "inscription"),
    "/connexion": ("connexion.html", "connexion"),
    "/mot-de-passe-oublie": ("mot_de_passe_oublie.html", "mot-de-passe-oublie"),
    "/reinitialiser-mot-de-passe": ("reinitialiser.html", "reinitialiser"),
    "/verifier-email": ("verifier_email.html", "verifier-email"),
    "/tableau-de-bord": ("tableau_bord.html", "tableau-de-bord"),
    "/profil": ("profil.html", "profil"),
}


def _make(template, page):
    def view():
        return render_template(template, page=page)

    view.__name__ = f"page_{page.replace('-', '_')}"
    return view


for _path, (_tpl, _page) in PAGES.items():
    bp.add_url_rule(_path, view_func=_make(_tpl, _page))


@bp.get("/sw.js")
def service_worker():
    resp = send_from_directory(os.path.join(current_app.root_path, "static"), "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(os.path.join(current_app.root_path, "static"), "manifest.webmanifest",
                               mimetype="application/manifest+json")


@bp.get("/uploads/logos/<path:filename>")
def local_logo(filename):
    """Logos stockés sur disque (développement uniquement ; en production : Cloudinary)."""
    return send_from_directory(os.path.join(current_app.config["UPLOAD_FOLDER"], "logos"), filename)


@bp.get("/healthz")
def healthz():
    db.session.execute(sa.text("SELECT 1"))
    return jsonify({"statut": "ok"})
