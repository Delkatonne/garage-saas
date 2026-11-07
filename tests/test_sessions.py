"""La session doit survivre à la fermeture du navigateur : cookies persistants, rafraîchissement du jeton."""
from conftest import PASSWORD


def cookies_of(response):
    return {c.split("=", 1)[0]: c for c in response.headers.getlist("Set-Cookie")}


def value_of(cookie_header):
    return cookie_header.split("=", 1)[1].split(";", 1)[0]


def login(new_api):
    api = new_api()
    r = api.post("/api/auth/login", json={"email": "alpha@example.com", "mot_de_passe": PASSWORD})
    assert r.status_code == 200
    return api, r


def test_login_cookies_are_persistent_not_session_cookies(make_garage, new_api):
    make_garage("Garage Alpha", "alpha@example.com")
    _, r = login(new_api)
    cookies = cookies_of(r)
    for name in ("access_token_cookie", "refresh_token_cookie", "csrf_access_token", "csrf_refresh_token"):
        assert "Max-Age=" in cookies[name] or "Expires=" in cookies[name], name  # sinon : effacé à la fermeture
    assert "HttpOnly" in cookies["access_token_cookie"] and "HttpOnly" in cookies["refresh_token_cookie"]


def test_refresh_renews_the_session_and_rotates_the_refresh_token(make_garage, new_api):
    make_garage("Garage Alpha", "alpha@example.com")
    api, r = login(new_api)
    cookies = cookies_of(r)
    old_refresh, old_csrf = value_of(cookies["refresh_token_cookie"]), value_of(cookies["csrf_refresh_token"])
    r = api.post("/api/auth/refresh", headers={"X-CSRF-TOKEN": old_csrf})
    assert r.status_code == 200
    assert "access_token_cookie" in cookies_of(r) and "refresh_token_cookie" in cookies_of(r)
    assert api.get("/api/auth/me").status_code == 200  # la session continue
    # l'ancien jeton de rafraîchissement est à usage unique : le rejouer échoue
    replay = new_api()
    replay.c.set_cookie("refresh_token_cookie", old_refresh, path="/api/auth/")
    assert replay.post("/api/auth/refresh", headers={"X-CSRF-TOKEN": old_csrf}).status_code == 401


def test_me_needs_a_session(new_api):
    assert new_api().get("/api/auth/me").status_code == 401
