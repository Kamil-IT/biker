"""Unit tests for the contact form endpoint POST /v1/contact (app/contact_routes.py),
on a fresh temp SQLite database — no server, no network, no AI call.
Run: cd backend && pytest   (collected via pytest.ini)"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import contact_routes, main, models  # noqa: E402
from app.models import ContactMessage  # noqa: E402
from app.schemas import CONTACT_MESSAGE_MAX_LEN, CONTACT_NAME_MAX_LEN, CONTACT_TOPICS  # noqa: E402

VALID = {"name": "Ola", "email": "ola@example.pl", "topic": "missing_bike", "message": "Brakuje Kross Esker 4.0."}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient on a fresh SQLite database with every table; the ORM points back at its default afterwards."""
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "contact.db")
    models.init_db()
    yield TestClient(main.app)  # no `with`: the lifespan (init against the real DB) is not run
    models.dispose_engine()
    models._db_url = None


def _rows() -> list[ContactMessage]:
    with models.get_session() as s:
        return s.query(ContactMessage).order_by(ContactMessage.id).all()


def test_stores_message_trimmed(client):
    resp = client.post("/v1/contact", json={
        "name": "  Ola ", "email": " ola@example.pl ", "topic": "wrong_data", "message": "\n Dane się nie zgadzają.  ",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
    [row] = _rows()
    assert (row.name, row.email, row.topic, row.message) == ("Ola", "ola@example.pl", "wrong_data", "Dane się nie zgadzają.")
    assert row.created_at is not None


def test_name_is_optional(client):
    body = {k: v for k, v in VALID.items() if k != "name"}
    assert client.post("/v1/contact", json=body).status_code == 200
    assert _rows()[0].name == ""


@pytest.mark.parametrize("topic", CONTACT_TOPICS)
def test_every_topic_is_accepted(client, topic):
    assert client.post("/v1/contact", json={**VALID, "topic": topic}).status_code == 200
    assert _rows()[0].topic == topic


def test_honeypot_answers_ok_but_stores_nothing(client):
    resp = client.post("/v1/contact", json={**VALID, "website": "http://spam.example"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert _rows() == []


@pytest.mark.parametrize("change", [
    {"email": "not-an-address"},
    {"email": "a@b"},
    {"email": "ola @example.pl"},
    {"email": ""},
    {"email": "x" * 250 + "@example.pl"},
    {"topic": "Brakuje roweru w bazie"},  # the Polish label, not the slug
    {"topic": ""},
    {"message": ""},
    {"message": "   \n "},
    {"message": "x" * (CONTACT_MESSAGE_MAX_LEN + 1)},
    {"name": "x" * (CONTACT_NAME_MAX_LEN + 1)},
])
def test_bad_field_is_422_and_stores_nothing(client, change):
    resp = client.post("/v1/contact", json={**VALID, **change})
    assert resp.status_code == 422, resp.text
    assert _rows() == []


@pytest.mark.parametrize("missing", ["email", "topic", "message"])
def test_required_field_missing_is_422(client, missing):
    body = {k: v for k, v in VALID.items() if k != missing}
    assert client.post("/v1/contact", json=body).status_code == 422


def test_message_at_max_length_is_stored(client):
    assert client.post("/v1/contact", json={**VALID, "message": "x" * CONTACT_MESSAGE_MAX_LEN}).status_code == 200
    assert len(_rows()[0].message) == CONTACT_MESSAGE_MAX_LEN


def test_nul_bytes_are_dropped(client):
    assert client.post("/v1/contact", json={**VALID, "message": "Ala\x00 ma rower"}).status_code == 200
    assert _rows()[0].message == "Ala ma rower"


def test_failed_write_is_503(client):
    with models.get_engine().begin() as conn:
        ContactMessage.__table__.drop(conn)
    resp = client.post("/v1/contact", json=VALID)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Could not save the message — try again later"}


def test_save_returns_new_id(client):
    from app.schemas import ContactMessageRequest
    first = contact_routes.save_contact_message(ContactMessageRequest(**VALID))
    second = contact_routes.save_contact_message(ContactMessageRequest(**VALID))
    assert isinstance(first, int) and second == first + 1
