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
