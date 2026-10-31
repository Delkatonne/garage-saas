import io

from conftest import make_staff, png_bytes, PASSWORD


def test_get_and_update_profile(make_garage):
    api = make_garage()
    p = api.get("/api/garage/profile").json["garage"]
    assert p["initiales"] == "GA" and p["logo_url"] is None and p["devise"] == "XOF"
    r = api.patch("/api/garage/profile", json={
        "nom_garage": "Garage Alpha Plus", "telephone": "+229 01 97 00 00 00", "ville": "Cotonou",
        "ifu": "3201234567890", "rccm": "RB/COT/21 B 1234", "devise": "xof", "devise_decimales": 0,
        "tva_active": True, "tva_taux": 18})
    assert r.status_code == 200
    g = r.json["garage"]
    assert g["nom_garage"] == "Garage Alpha Plus" and g["tva_active"] and g["tva_taux"] == 18.0 and g["ifu"] == "3201234567890"


def test_profile_validation(make_garage):
    api = make_garage()
    r = api.patch("/api/garage/profile", json={"nom_garage": " ", "telephone": "abc", "devise": "ZZZ",
                                              "tva_taux": 150, "tva_active": "oui", "devise_decimales": 9, "ifu": "<script>"})
    assert r.status_code == 422
    assert {"nom_garage", "telephone", "devise", "tva_taux", "tva_active", "devise_decimales", "ifu"} <= set(r.json["details"])


def test_only_owner_can_edit_profile(app, make_garage, new_api):
    make_garage()
    make_staff(app, "alpha@example.com", "meca@example.com", role="mecanicien")
    api = new_api()
    api.post("/api/auth/login", json={"email": "meca@example.com", "mot_de_passe": PASSWORD})
    assert api.get("/api/garage/profile").status_code == 200
    assert api.patch("/api/garage/profile", json={"ville": "X"}).status_code == 403
    assert api.post("/api/garage/logo", data={"logo": (io.BytesIO(png_bytes()), "l.png")}, content_type="multipart/form-data").status_code == 403


def test_logo_upload_replace_delete(make_garage):
    api = make_garage()
    r = api.post("/api/garage/logo", data={"logo": (io.BytesIO(png_bytes((900, 600), "PNG")), "logo.png")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.json["garage"]["logo_url"].startswith("/uploads/logos/")
    url = r.json["garage"]["logo_url"]
    assert api.get(url).status_code == 200
    r = api.post("/api/garage/logo", data={"logo": (io.BytesIO(png_bytes((50, 50), "JPEG")), "logo.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.json["garage"]["logo_url"] != url
    assert api.get(url).status_code == 404  # ancien fichier supprimé
    assert api.delete("/api/garage/logo").json["garage"]["logo_url"] is None


def test_logo_rejections(make_garage):
    api = make_garage()
    def up(blob, name):
        return api.post("/api/garage/logo", data={"logo": (io.BytesIO(blob), name)}, content_type="multipart/form-data")
    assert up(b"<?php echo 1;", "logo.png").status_code == 422          # faux PNG
    assert up(b"GIF89a....", "logo.gif").status_code == 422             # extension interdite
    assert up(png_bytes(), "logo.exe").status_code == 422
    assert up(b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 1), "logo.png").status_code == 422  # > 2 Mo
    assert api.post("/api/garage/logo", data={}, content_type="multipart/form-data").status_code == 422
