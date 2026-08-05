"""Guards on the two settings that are auth bypasses if they reach production:
the placeholder JWT secret (this repo is public) and the password-less dev
sign-in. Both are gated on NDB_DEV_MODE, which defaults off."""

import pytest

from app.config import DEV_JWT_SECRET, Settings, settings


def _settings(**over) -> Settings:
    """Build Settings from explicit values only, so the developer's own .env /
    environment can't decide the outcome of these tests."""
    base = {"jwt_secret": "a-real-secret", "dev_mode": False, "dev_login": False}
    return Settings(_env_file=None, **{**base, **over})


def test_placeholder_secret_refuses_to_boot():
    with pytest.raises(RuntimeError, match="NDB_JWT_SECRET"):
        _settings(jwt_secret=DEV_JWT_SECRET)


def test_placeholder_secret_allowed_only_in_dev_mode():
    assert _settings(jwt_secret=DEV_JWT_SECRET, dev_mode=True).jwt_secret == DEV_JWT_SECRET


def test_real_secret_needs_no_dev_mode():
    assert _settings().jwt_secret == "a-real-secret"


@pytest.mark.parametrize(
    "dev_login,dev_mode,expected",
    [(False, False, False), (True, False, False), (False, True, False), (True, True, True)],
)
def test_dev_login_needs_both_flags(dev_login, dev_mode, expected):
    assert _settings(dev_login=dev_login, dev_mode=dev_mode).dev_login_enabled is expected


def test_dev_login_endpoints_closed_without_dev_mode(client, monkeypatch):
    """NDB_DEV_LOGIN alone (the misconfiguration that would matter on a deployed
    box) must not expose the demo users or mint a token for the demo admin."""
    monkeypatch.setattr(settings, "dev_login", True)
    monkeypatch.setattr(settings, "dev_mode", False)

    cfg = client.get("/api/auth/dev-login/config")
    assert cfg.status_code == 200
    assert cfg.json() == {"enabled": False, "users": []}

    resp = client.post("/api/auth/dev-login", json={"email": "admin@tbia.test"})
    assert resp.status_code == 404


def test_dev_login_works_when_fully_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_login", True)
    monkeypatch.setattr(settings, "dev_mode", True)

    assert client.get("/api/auth/dev-login/config").json()["enabled"] is True
    resp = client.post("/api/auth/dev-login", json={"email": "admin@tbia.test"})
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
