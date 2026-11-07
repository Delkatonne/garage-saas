import os

from flask import Flask

from .config import TestConfig, get_config  # noqa: F401
from .extensions import cors, db, jwt, limiter, mail, migrate

PUBLIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")


def create_app(config_object=None):
    # Les fichiers statiques vivent dans public/ : Vercel les sert directement (CDN) et ignore static_folder ;
    # en développement, Flask les sert depuis le même dossier.
    app = Flask(__name__, instance_relative_config=True,
                static_folder=os.path.join(PUBLIC_DIR, "static"), static_url_path="/static")
    app.config.from_object(config_object or get_config())
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:  # système de fichiers en lecture seule (Vercel) : inutile en production
        pass
    if not app.config.get("UPLOAD_FOLDER"):
        app.config["UPLOAD_FOLDER"] = os.path.join(app.instance_path, "uploads")

    # SQLite de dev : fichier dans instance/
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///") and not uri.startswith("sqlite:////") and uri != "sqlite://":
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, uri[len("sqlite:///"):])

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)
    if app.config.get("CORS_ORIGINS"):
        cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}}, supports_credentials=True)

    from . import models, tenancy  # noqa: F401  (enregistre les modèles et les filtres tenant)
    from . import auth_hooks  # noqa: F401
    from .api import admin, auth, clients, cron, devis, factures, garage, ordres, paiements, public, vehicules
    from .cli import register_cli
    from .errors import register_error_handlers
    from .web import bp as web_bp

    for module in (auth, garage, admin, cron, clients, vehicules, devis, ordres, factures, paiements, public):
        app.register_blueprint(module.bp)
    app.register_blueprint(web_bp)
    register_error_handlers(app)
    register_cli(app)

    if app.config["IS_PRODUCTION"] and app.config["RATELIMIT_STORAGE_URI"].startswith("memory://"):
        app.logger.warning("RATELIMIT_STORAGE_URI=memory:// : la limitation des tentatives est par instance "
                           "(inefficace en serverless). Configurez Redis (Upstash).")

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https://res.cloudinary.com; "
            "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if app.config["IS_PRODUCTION"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if resp.mimetype == "application/json" or resp.headers.get("Content-Type", "").startswith("application/json"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    return app
