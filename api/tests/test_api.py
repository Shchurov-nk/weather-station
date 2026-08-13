from unittest import mock

import pytest

import app as app_module

AUTH = {"Authorization": "Bearer test-token"}
VALID = {"temp": 21.5, "hum": 40.2, "pres": 992.1}


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture()
def fake_db():
    with mock.patch.object(app_module, "get_conn") as gc:
        yield gc


def test_sensor_without_token_is_401(client):
    assert client.post("/sensor", json=VALID).status_code == 401


def test_sensor_with_wrong_token_is_401(client):
    r = client.post("/sensor", json=VALID, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_sensor_garbage_type_is_422_and_skips_db(client, fake_db):
    r = client.post("/sensor", json={**VALID, "temp": "banana"}, headers=AUTH)
    assert r.status_code == 422
    fake_db.assert_not_called()


def test_sensor_out_of_range_is_422(client, fake_db):
    r = client.post("/sensor", json={**VALID, "hum": 150}, headers=AUTH)
    assert r.status_code == 422
    fake_db.assert_not_called()


def test_sensor_invalid_json_is_422(client, fake_db):
    r = client.post("/sensor", data="not json",
                    headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_sensor_valid_is_201(client, fake_db):
    r = client.post("/sensor", json=VALID, headers=AUTH)
    assert r.status_code == 201
    conn = fake_db.return_value.__enter__.return_value
    assert conn.execute.called


def test_db_error_does_not_leak_details(client, fake_db):
    fake_db.side_effect = RuntimeError("secret internal detail")
    r = client.post("/sensor", json=VALID, headers=AUTH)
    assert r.status_code == 500
    assert b"secret internal detail" not in r.data
