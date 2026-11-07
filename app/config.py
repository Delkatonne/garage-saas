"""Configuration de l'application (variables d'environnement)."""
import os
from datetime import timedelta

from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

load_dotenv()


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _default_base_url():
    """Adresse publique du site : APP_BASE_URL, sinon le domaine de production fourni par Vercel."""
    explicit = os.environ.get("APP_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    vercel_host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
    if vercel_host:
        return "https://" + vercel_host.rstrip("/")
    return "http://localhost:5000"


def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///garage_dev.db")
    # Certains hébergeurs fournissent parfois "postgres://", non supporté par SQLAlchemy 2.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    ENV_NAME = os.environ.get("APP_ENV", "development")
    IS_PRODUCTION = ENV_NAME == "production"

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    ON_VERCEL = bool(os.environ.get("VERCEL"))
    DEVIS_VALIDITE_JOURS = int(os.environ.get("DEVIS_VALIDITE_JOURS", "30"))
    FACTURE_ECHEANCE_JOURS = int(os.environ.get("FACTURE_ECHEANCE_JOURS", "30"))
    # Confirmation de l'email à l'inscription : désactivée par défaut (REQUIRE_EMAIL_VERIFICATION=true pour l'exiger).
    REQUIRE_EMAIL_VERIFICATION = os.environ.get("REQUIRE_EMAIL_VERIFICATION", "false").strip().lower() in ("1", "true", "yes", "oui")
    APP_BASE_URL = _default_base_url()

    SQLALCHEMY_DATABASE_URI = _database_url()
    # Serverless : pas de pool de connexions persistant (on s'appuie sur le pooler de Neon).
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, **({"poolclass": NullPool} if ON_VERCEL else {})}

    # --- JWT : cookies httpOnly + protection CSRF (double submit) ---
    JWT_TOKEN_LOCATION = ["cookies", "headers"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_COOKIE_SECURE = IS_PRODUCTION
    JWT_SESSION_COOKIE = False  # cookies persistants : la session survit à la fermeture du navigateur / de l'application
    JWT_COOKIE_SAMESITE = "Lax"
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_REFRESH_COOKIE_PATH = "/api/auth/"

    # --- Emails : API HTTPS Brevo (recommandé en production) ou SMTP ---
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "Garage SaaS <no-reply@localhost>")

    # --- Logos ---
    CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")
    UPLOAD_FOLDER = None  # défini dans create_app (instance/uploads)
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # plafond de requête (logo limité à 2 Mo)
    MAX_LOGO_BYTES = 2 * 1024 * 1024

    # --- Valeurs par défaut des nouveaux garages ---
    DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "XOF")
    DEFAULT_CURRENCY_DECIMALS = int(os.environ.get("DEFAULT_CURRENCY_DECIMALS", 0))
    DEFAULT_COUNTRY = "BJ"
    TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", 30))
    ALLOWED_CURRENCIES = {"XOF", "XAF", "EUR", "USD", "MAD", "GNF", "NGN", "GHS"}

    # --- Authentification ---
    EMAIL_VERIFY_TTL = timedelta(hours=24)
    PASSWORD_RESET_TTL = timedelta(minutes=30)
    MAX_FAILED_LOGINS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)

    # --- Sécurité ---
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = True
    CRON_SECRET = os.environ.get("CRON_SECRET", "")  # Vercel l'envoie en "Authorization: Bearer ..." aux crons


class TestConfig(Config):
    TESTING = True
    IS_PRODUCTION = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": __import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    }
    SECRET_KEY = "test-secret-key-test-secret-key-0123"
    JWT_SECRET_KEY = "test-jwt-secret-key-test-jwt-secret-0123"
    RATELIMIT_ENABLED = False
    MAIL_SUPPRESS_SEND = True
    CLOUDINARY_URL = ""
    BREVO_API_KEY = ""   # les tests ne doivent jamais appeler Brevo, même si un .env local en définit une
    CRON_SECRET = ""
    REQUIRE_EMAIL_VERIFICATION = True   # les tests existants couvrent le parcours avec confirmation
    JWT_COOKIE_SECURE = False


def get_config():
    cfg = Config
    if cfg.IS_PRODUCTION:
        if cfg.SECRET_KEY == "dev-secret-change-me":
            raise RuntimeError("SECRET_KEY doit être défini en production.")
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL doit être défini en production.")
        if not cfg.CLOUDINARY_URL:
            raise RuntimeError("CLOUDINARY_URL doit être défini en production (stockage des logos).")
        if not (cfg.BREVO_API_KEY or cfg.MAIL_SERVER):
            raise RuntimeError("BREVO_API_KEY (ou MAIL_SERVER) doit être défini en production : sans email, "
                               "personne ne peut réinitialiser son mot de passe.")
        if cfg.APP_BASE_URL.startswith("http://localhost"):
            raise RuntimeError("APP_BASE_URL doit être défini en production (liens des emails).")
    return cfg
