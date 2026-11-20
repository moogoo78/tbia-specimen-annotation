"""The identifier flag: a per-user permission beside the role, granted by an
admin, that alone lets someone record a determination."""

from tests.conftest import auth_header
from tests.test_identifications import ADMIN, BODY, CURATOR, OCC, REVIEWER, made  # noqa: F401


def _user_id(client, email):
    return client.get("/api/auth/me", headers=auth_header(client, email)).json()["id"]


def _post(client, email):
    return client.post(f"/api/occurrences/{OCC}/identifications",
                       headers=auth_header(client, email), json=BODY)


def test_me_reports_the_flag(client):
    assert client.get("/api/auth/me", headers=auth_header(client, CURATOR)).json()["is_identifier"] is True
    assert client.get("/api/auth/me", headers=auth_header(client, REVIEWER)).json()["is_identifier"] is False


def test_without_the_flag_no_determination(client, made):
    # The reviewer role does not imply it.
    res = _post(client, REVIEWER)
    assert res.status_code == 403
    assert "Identifier" in res.json()["detail"]


def test_admin_may_always_identify(client, made):
    res = _post(client, ADMIN)
    assert res.status_code == 200, res.text
    made.append(res.json()["id"])


def test_admin_grants_and_withdraws(client, made):
    adm = auth_header(client, ADMIN)
    rid = _user_id(client, REVIEWER)
    try:
        res = client.patch(f"/api/admin/users/{rid}", headers=adm, json={"is_identifier": True})
        assert res.status_code == 200 and res.json()["is_identifier"] is True
        # Reviewer and identifier at once: the flag sits beside the role.
        assert res.json()["role"] == "reviewer"
        ok = _post(client, REVIEWER)
        assert ok.status_code == 200, ok.text
        made.append(ok.json()["id"])

        client.patch(f"/api/admin/users/{rid}", headers=adm, json={"is_identifier": False})
        assert _post(client, REVIEWER).status_code == 403
        # What they already identified is untouched by the withdrawal.
        mine = client.get("/api/identifications?mine=true", headers=auth_header(client, REVIEWER)).json()
        assert any(i["id"] == ok.json()["id"] for i in mine["items"])
    finally:
        client.patch(f"/api/admin/users/{rid}", headers=adm, json={"is_identifier": False})


def test_user_admin_is_admin_only(client):
    for who in (CURATOR, REVIEWER):
        h = auth_header(client, who)
        assert client.get("/api/admin/users", headers=h).status_code == 403
        assert client.patch(f"/api/admin/users/{_user_id(client, who)}", headers=h,
                            json={"is_identifier": True}).status_code == 403
    assert client.get("/api/admin/users").status_code == 401


def test_list_filters(client):
    adm = auth_header(client, ADMIN)
    rows = client.get("/api/admin/users?identifiers=true", headers=adm).json()["items"]
    assert [u["email"] for u in rows] == [CURATOR]
    rows = client.get("/api/admin/users?q=Rex", headers=adm).json()["items"]
    assert [u["email"] for u in rows] == [REVIEWER]
    assert client.patch("/api/admin/users/999999", headers=adm,
                        json={"is_identifier": True}).status_code == 404


def test_me_patch_cannot_set_the_flag(client):
    h = auth_header(client, REVIEWER)
    client.patch("/api/auth/me", headers=h, json={"is_identifier": True})
    assert client.get("/api/auth/me", headers=h).json()["is_identifier"] is False
