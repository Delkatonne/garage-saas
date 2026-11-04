"""Validation des entrées (aucune donnée client n'est de confiance)."""
import re

from email_validator import EmailNotValidError, validate_email

from .security import password_problems

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_PHONE = re.compile(r"^\+?[0-9 .\-()]{6,20}$")
_ADMIN_ID = re.compile(r"^[A-Za-z0-9 .\-/]{3,50}$")


def text(data, field, errors, *, max_len=120, required=True, label=None):
    label = label or field
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[field] = f"{label} est obligatoire."
        return None
    if not isinstance(value, str):
        errors[field] = f"{label} est invalide."
        return None
    value = " ".join(value.split())
    if _CTRL.search(value):
        errors[field] = f"{label} contient des caractères interdits."
    elif len(value) > max_len:
        errors[field] = f"{label} est trop long ({max_len} caractères maximum)."
    else:
        return value
    return None


def email(data, field, errors, label="L'email"):
    raw = data.get(field)
    if not isinstance(raw, str) or not raw.strip():
        errors[field] = f"{label} est obligatoire."
        return None
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        errors[field] = f"{label} n'a pas un format valide."
        return None


def password(data, field, errors, email_value=""):
    value = data.get(field)
    if not isinstance(value, str) or not value:
        errors[field] = "Le mot de passe est obligatoire."
        return None
    problems = password_problems(value, email_value or "")
    if problems:
        errors[field] = "Mot de passe trop faible : " + ", ".join(problems) + "."
        return None
    return value


def phone(data, field, errors):
    value = data.get(field)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _PHONE.match(value.strip()):
        errors[field] = "Numéro de téléphone invalide."
        return None
    return value.strip()


def admin_id(data, field, errors, label):
    value = data.get(field)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _ADMIN_ID.match(value.strip()):
        errors[field] = f"{label} invalide."
        return None
    return value.strip()


# ----------------------------------------------------------------- helpers métier (clients, véhicules...)
_VIN = re.compile(r"^[A-Z0-9\-]{5,30}$")


def choice(data, field, errors, allowed, *, label, required=False):
    value = data.get(field)
    if value in (None, ""):
        if required:
            errors[field] = f"{label} est obligatoire."
        return None
    if not isinstance(value, str) or value.strip().lower() not in allowed:
        errors[field] = f"{label} : valeur non autorisée."
        return None
    return value.strip().lower()


def integer(data, field, errors, *, label, minimum, maximum):
    value = data.get(field)
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        errors[field] = f"{label} est invalide."
        return None
    try:
        number = int(str(value).strip()) if isinstance(value, str) else int(value)
    except ValueError:
        errors[field] = f"{label} doit être un nombre entier."
        return None
    if isinstance(value, float) and value != number:
        errors[field] = f"{label} doit être un nombre entier."
        return None
    if not minimum <= number <= maximum:
        errors[field] = f"{label} doit être compris entre {minimum} et {maximum}."
        return None
    return number


def optional_email(data, field, errors, label="L'email"):
    raw = data.get(field)
    if raw in (None, "") or (isinstance(raw, str) and not raw.strip()):
        return None
    return email(data, field, errors, label)


def plate(data, field, errors):
    """Retourne (immatriculation affichée, clé d'unicité) ou (None, None)."""
    value = data.get(field)
    if value in (None, "") or (isinstance(value, str) and not value.strip()):
        return None, None
    if not isinstance(value, str) or _CTRL.search(value):
        errors[field] = "Immatriculation invalide."
        return None, None
    shown = " ".join(value.upper().split())
    key = re.sub(r"[^A-Z0-9]", "", shown)
    if len(shown) > 20 or not 2 <= len(key) <= 20:
        errors[field] = "Immatriculation invalide (2 à 20 lettres/chiffres)."
        return None, None
    return shown, key


def vin(data, field, errors):
    value = data.get(field)
    if value in (None, "") or (isinstance(value, str) and not value.strip()):
        return None
    cleaned = value.strip().upper().replace(" ", "") if isinstance(value, str) else ""
    if not _VIN.match(cleaned):
        errors[field] = "Numéro de châssis (VIN) invalide : 5 à 30 lettres/chiffres."
        return None
    return cleaned


def like_pattern(q: str) -> str:
    """Motif LIKE sûr : les caractères % _ \\ saisis par l'utilisateur sont échappés (échappement = \\)."""
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def long_text(data, field, errors, *, max_len=2000, label=None):
    """Texte libre multi-lignes (notes) : les retours à la ligne sont conservés."""
    label = label or field
    value = data.get(field)
    if value in (None, "") or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        errors[field] = f"{label} est invalide."
        return None
    value = value.replace("\r\n", "\n").strip()
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        errors[field] = f"{label} contient des caractères interdits."
    elif len(value) > max_len:
        errors[field] = f"{label} est trop long ({max_len} caractères maximum)."
    else:
        return value
    return None


def decimal_value(value, *, label, minimum, maximum, places):
    """Convertit une saisie (nombre ou texte) en Decimal borné, ou lève ValueError avec un message lisible."""
    from decimal import Decimal, InvalidOperation

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{label} est invalide.")
    try:
        number = Decimal(str(value).strip().replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise ValueError(f"{label} doit être un nombre.")
    if not number.is_finite():
        raise ValueError(f"{label} doit être un nombre.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise ValueError(f"{label} : {places} décimale(s) maximum.")
    if not Decimal(str(minimum)) <= number <= Decimal(str(maximum)):
        raise ValueError(f"{label} doit être compris entre {minimum} et {maximum}.")
    return number
