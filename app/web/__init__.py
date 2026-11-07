"""Pages HTML (Jinja) + PWA. La logique passe par l'API JSON (fetch)."""
import os

from flask import Blueprint, current_app, jsonify, render_template, send_from_directory
import sqlalchemy as sa

from app.extensions import db

PUBLIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "public")

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
    "/clients": ("clients.html", "clients"),
    "/vehicules": ("vehicules.html", "vehicules"),
    "/devis": ("devis.html", "devis"),
    "/devis/nouveau": ("devis_editeur.html", "devis-editeur"),
    "/or": ("or.html", "or"),
    "/or/nouveau": ("or_nouveau.html", "or-nouveau"),
    "/factures": ("factures.html", "factures"),
    "/factures/nouveau": ("facture_editeur.html", "facture-editeur"),
}


def _make(template, page):
    def view():
        return render_template(template, page=page)

    view.__name__ = f"page_{page.replace('-', '_')}"
    return view


for _path, (_tpl, _page) in PAGES.items():
    bp.add_url_rule(_path, view_func=_make(_tpl, _page))


def _detail(rule, endpoint, template, page):
    def view(**_ids):  # l'identifiant est relu par le JavaScript depuis l'adresse
        return render_template(template, page=page)

    bp.add_url_rule(rule, endpoint=endpoint, view_func=view)


_detail("/clients/<uuid:client_id>", "page_client", "client.html", "client")
_detail("/vehicules/<uuid:vehicule_id>", "page_vehicule", "vehicule.html", "vehicule")
_detail("/devis/<uuid:devis_id>", "page_devis_fiche", "devis_fiche.html", "devis-fiche")
_detail("/devis/<uuid:devis_id>/modifier", "page_devis_modifier", "devis_editeur.html", "devis-editeur")
_detail("/or/<uuid:or_id>", "page_or_fiche", "or_fiche.html", "or-fiche")
_detail("/factures/<uuid:facture_id>", "page_facture_fiche", "facture_fiche.html", "facture-fiche")
_detail("/factures/<uuid:facture_id>/modifier", "page_facture_modifier", "facture_editeur.html", "facture-editeur")
_detail("/d/<token>", "page_devis_public", "devis_public.html", "devis-public")  # lien envoyé au client


@bp.get("/sw.js")
def service_worker():
    resp = send_from_directory(PUBLIC_DIR, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(PUBLIC_DIR, "manifest.webmanifest", mimetype="application/manifest+json")


@bp.get("/uploads/logos/<path:filename>")
def local_logo(filename):
    """Logos stockés sur disque (développement uniquement ; en production : Cloudinary)."""
    return send_from_directory(os.path.join(current_app.config["UPLOAD_FOLDER"], "logos"), filename)


@bp.get("/healthz")
def healthz():
    db.session.execute(sa.text("SELECT 1"))
    return jsonify({"statut": "ok"})
