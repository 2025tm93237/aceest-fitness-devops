import os
import tempfile

import pytest

from app import bmi_category, calculate_bmi, calculate_daily_calories, create_app


@pytest.fixture
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(path)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    os.unlink(path)


def create_client(c, name="Ravi", **kwargs):
    payload = {"name": name, "age": 28, "gender": "male", "height_cm": 175, "weight_kg": 78, "goal": "Muscle Gain"}
    payload.update(kwargs)
    return c.post("/clients", json=payload)

def test_health():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        app = create_app(f.name)
        app.config["TESTING"] = True
        assert app.test_client().get("/health").status_code == 200

def test_home_version(client):
    body = client.get("/").get_json()
    assert body["service"] == "ACEest Fitness & Gym API"
    assert body["version"] == "1.0"

def test_login_success(client):
    response = client.post("/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    assert response.get_json()["role"] == "admin"
    assert client.post("/logout").status_code == 200

def test_login_bad_password(client):
    assert client.post("/login", json={"username": "admin", "password": "wrong"}).status_code == 401

def test_login_missing_fields(client):
    assert client.post("/login", json={}).status_code == 400

def test_client_create(client):
    assert create_client(client).status_code == 201

def test_client_list_and_get(client):
    create_client(client)
    assert len(client.get("/clients").get_json()) == 1
    assert client.get("/clients/Ravi").get_json()["name"] == "Ravi"

def test_duplicate_client(client):
    create_client(client)
    assert create_client(client).status_code == 409

def test_client_not_found(client):
    assert client.get("/clients/Nobody").status_code == 404

def test_protected_delete_requires_role(client):
    create_client(client)
    assert client.delete("/clients/Ravi").status_code == 403

def test_client_delete(client):
    create_client(client)
    client.post("/login", json={"username": "admin", "password": "admin123"})
    assert client.delete("/clients/Ravi").status_code == 200
    assert client.get("/clients/Ravi").status_code == 404
