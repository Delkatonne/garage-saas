"""Validation et stockage des logos (Cloudinary en production, disque local en développement)."""
import io
import os
import secrets

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_DIMENSION = 4000


class LogoError(ValueError):
    pass


def validate_logo(file_storage) -> bytes:
    """Contrôle le fichier puis le RÉ-ENCODE en PNG 512 px max (supprime métadonnées et contenus piégés)."""
    name = (file_storage.filename or "").lower()
    if "." not in name or name.rsplit(".", 1)[1] not in ALLOWED_EXT:
        raise LogoError("Le logo doit être au format PNG, JPG ou WEBP.")
    limit = current_app.config["MAX_LOGO_BYTES"]
    raw = file_storage.read(limit + 1)
    if not raw:
        raise LogoError("Le fichier du logo est vide.")
    if len(raw) > limit:
        raise LogoError("Le logo dépasse 2 Mo.")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise LogoError("Le logo doit être au format PNG, JPG ou WEBP.")
        if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
            raise LogoError(f"Le logo est trop grand ({MAX_DIMENSION} px maximum).")
        img.load()
    except LogoError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise LogoError("Le fichier n'est pas une image valide.")
    img = ImageOps.exif_transpose(img)
    img.thumbnail((512, 512))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _use_cloudinary() -> bool:
    return bool(current_app.config.get("CLOUDINARY_URL"))


def save_logo(garage_id, png_bytes: bytes) -> tuple[str, str]:
    """Retourne (url, public_id)."""
    if _use_cloudinary():
        import cloudinary.uploader

        res = cloudinary.uploader.upload(
            png_bytes,
            folder=f"garages/{garage_id}",
            public_id=f"logo-{secrets.token_hex(4)}",
            resource_type="image",
            overwrite=False,
        )
        return res["secure_url"], res["public_id"]
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "logos")
    os.makedirs(folder, exist_ok=True)
    filename = f"{garage_id}-{secrets.token_hex(4)}.png"
    with open(os.path.join(folder, filename), "wb") as fh:
        fh.write(png_bytes)
    return f"/uploads/logos/{filename}", f"local:{filename}"


def delete_logo(public_id: str | None) -> None:
    if not public_id:
        return
    try:
        if public_id.startswith("local:"):
            path = os.path.join(current_app.config["UPLOAD_FOLDER"], "logos", os.path.basename(public_id[6:]))
            if os.path.exists(path):
                os.remove(path)
        elif _use_cloudinary():
            import cloudinary.uploader

            cloudinary.uploader.destroy(public_id)
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Suppression du logo impossible (%s)", public_id)
