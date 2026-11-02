"""Rôles et permissions. `owner` a tous les droits ; les autres rôles seront étendus module par module."""
from functools import wraps

from flask_jwt_extended import current_user, jwt_required

from .errors import ApiError
from .models import PlatformAdmin, User

# Permissions nommées "module.action". Complétées à chaque nouveau module.
ROLE_PERMISSIONS = {
    "owner": {"*"},
    "receptionniste": {"clients.*", "vehicules.*", "or.*", "devis.*", "planning.*"},
    "mecanicien": {"or.read", "or.update_status", "taches.*", "pointage.*", "vehicules.read"},
    "magasinier": {"stock.*", "fournisseurs.*"},
    "comptable": {"factures.*", "paiements.*", "depenses.*", "rapports.*", "caisse.*", "clients.read", "vehicules.read"},
}


def has_permission(user, permission: str) -> bool:
    granted = ROLE_PERMISSIONS.get(user.role, set())
    if "*" in granted or permission in granted:
        return True
    return permission.split(".")[0] + ".*" in granted


def require_permission(permission: str):
    """Exige un utilisateur de garage authentifié disposant de la permission."""

    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            if not isinstance(current_user, User):
                raise ApiError("Accès refusé.", 403, "acces_refuse")
            if not has_permission(current_user, permission):
                raise ApiError("Vous n'avez pas la permission d'effectuer cette action.", 403, "permission_refusee")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def garage_user_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if not isinstance(current_user, User):
            raise ApiError("Accès refusé.", 403, "acces_refuse")
        return fn(*args, **kwargs)

    return wrapper


def platform_admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if not isinstance(current_user, PlatformAdmin):
            raise ApiError("Accès réservé à l'administration de la plateforme.", 403, "acces_refuse")
        from .tenancy import unscoped

        with unscoped():
            return fn(*args, **kwargs)

    return wrapper
