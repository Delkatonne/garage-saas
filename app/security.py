"""Hachage des mots de passe (Argon2id), politique de mot de passe, jetons à usage unique."""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()
# Hash factice : égalise le temps de réponse quand l'email n'existe pas.
DUMMY_HASH = _ph.hash("mot-de-passe-factice-pour-egaliser-le-temps")

_COMMON = {
    "password", "motdepasse", "azerty123", "qwerty123", "12345678", "123456789",
    "1234567890", "password1", "password123", "azertyuiop", "11111111", "00000000",
    "admin123", "garage123", "motdepasse1", "iloveyou1",
}


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def password_problems(password: str, email: str = "") -> list[str]:
    """Retourne la liste des règles non respectées (liste vide = mot de passe accepté)."""
    problems = []
    if len(password) < 8:
        problems.append("au moins 8 caractères")
    if len(password) > 128:
        problems.append("128 caractères maximum")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("au moins une lettre et un chiffre")
    if password.lower() in _COMMON or (email and password.lower() == email.lower()):
        problems.append("ne doit pas être un mot de passe courant ni votre email")
    return problems


def new_token() -> tuple[str, str]:
    """(jeton brut à envoyer par email, hash SHA-256 à stocker)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
