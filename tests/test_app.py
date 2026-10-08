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
