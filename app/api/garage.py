from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import current_user

from app import validators as v
from app.errors import ApiError, validation_error
from app.extensions import db
from app.models import Garage
from app.permissions import garage_user_required, require_permission
from app.serializers import garage_dict
from app.services import storage
from app.services.audit import audit
from app.tenancy import unscoped

bp = Blueprint("garage", __name__, url_prefix="/api/garage")


def _garage() -> Garage:
    # Le garage est celui de l'utilisateur authentifié : jamais un identifiant venant du client.
    with unscoped():
        return db.session.get(Garage, current_user.garage_id)


@bp.get("/profile")
@garage_user_required
def get_profile():
    return jsonify({"garage": garage_dict(_garage())})


@bp.patch("/profile")
@require_permission("garage.update")
def update_profile():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Corps JSON attendu.", 400, "requete_invalide")
    errors, changes = {}, {}
    # Seuls ces champs sont modifiables. email, statut_abonnement, actif... sont ignorés.
    if "nom_garage" in data:
        changes["nom_garage"] = v.text(data, "nom_garage", errors, label="Le nom du garage")
    if "nom_chef_garage" in data:
        changes["nom_chef_garage"] = v.text(data, "nom_chef_garage", errors, label="Le nom du chef de garage")
    for field, label, size in (("adresse", "L'adresse", 255), ("ville", "La ville", 100)):
        if field in data:
            changes[field] = v.text(data, field, errors, max_len=size, required=False, label=label)
    if "telephone" in data:
        changes["telephone"] = v.phone(data, "telephone", errors)
    for field, label in (("ifu", "L'IFU"), ("rccm", "Le RCCM")):
        if field in data:
            changes[field] = v.admin_id(data, field, errors, label)
    if "devise" in data:
        devise = str(data["devise"]).upper()
        if devise not in current_app.config["ALLOWED_CURRENCIES"]:
            errors["devise"] = "Devise non prise en charge."
        else:
            changes["devise"] = devise
    if "devise_decimales" in data:
        d = data["devise_decimales"]
        if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 3:
            errors["devise_decimales"] = "Entier entre 0 et 3 attendu."
        else:
            changes["devise_decimales"] = d
    if "tva_active" in data:
        if not isinstance(data["tva_active"], bool):
            errors["tva_active"] = "Booléen attendu."
        else:
            changes["tva_active"] = data["tva_active"]
    if "tva_taux" in data:
        try:
            taux = Decimal(str(data["tva_taux"]))
            if not (Decimal(0) <= taux <= Decimal(100)):
                raise InvalidOperation
            changes["tva_taux"] = taux.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            errors["tva_taux"] = "Le taux de TVA doit être compris entre 0 et 100."
    if errors:
        raise validation_error(errors)
    garage = _garage()
    for field, value in changes.items():
        setattr(garage, field, value)
    audit("garage.profil_modifie", garage_id=garage.id, user_id=current_user.id, entity_type="garage",
          entity_id=garage.id, details={"champs": sorted(changes)})
    db.session.commit()
    return jsonify({"garage": garage_dict(garage)})


@bp.post("/logo")
@require_permission("garage.update")
def upload_logo():
    file = request.files.get("logo")
    if not file or not file.filename:
        raise validation_error({"logo": "Aucun fichier reçu."})
    try:
        png = storage.validate_logo(file)
    except storage.LogoError as exc:
        raise validation_error({"logo": str(exc)})
    garage = _garage()
    old = garage.logo_public_id
    garage.logo_url, garage.logo_public_id = storage.save_logo(garage.id, png)
    audit("garage.logo_modifie", garage_id=garage.id, user_id=current_user.id, entity_type="garage", entity_id=garage.id)
    db.session.commit()
    storage.delete_logo(old)
    return jsonify({"garage": garage_dict(garage)})


@bp.delete("/logo")
@require_permission("garage.update")
def delete_logo():
    garage = _garage()
    old = garage.logo_public_id
    garage.logo_url = garage.logo_public_id = None
    audit("garage.logo_supprime", garage_id=garage.id, user_id=current_user.id, entity_type="garage", entity_id=garage.id)
    db.session.commit()
    storage.delete_logo(old)
    return jsonify({"garage": garage_dict(garage)})
