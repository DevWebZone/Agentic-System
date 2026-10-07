from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.shortener.models import ClickEvent, Link


def clear_shortener_data() -> None:
    with SessionLocal() as session:
        session.execute(delete(ClickEvent))
        session.execute(delete(Link))
        session.commit()


def test_create_and_inspect_custom_link(client: TestClient) -> None:
    clear_shortener_data()
    response = client.post(
        "/api/v1/links",
        json={
            "original_url": "https://example.com/a/long/path#fragment",
            "custom_alias": "demo-link",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["short_code"] == "demo-link"
    assert body["original_url"] == "https://example.com/a/long/path"
    assert body["short_url"].endswith("/demo-link")

    inspected = client.get("/api/v1/links/demo-link")
    assert inspected.status_code == 200
    assert inspected.json()["is_enabled"] is True


def test_redirect_records_analytics(client: TestClient) -> None:
    clear_shortener_data()
    client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com", "custom_alias": "redirect-link"},
    )

    redirect = client.get(
        "/redirect-link", follow_redirects=False, headers={"Referer": "https://ref.example"}
    )
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com"

    analytics = client.get("/api/v1/links/redirect-link/analytics")
    assert analytics.status_code == 200
    assert analytics.json()["total_clicks"] == 1
    assert len(analytics.json()["clicks_by_day"]) == 1


def test_duplicate_alias_and_reserved_alias_are_rejected(client: TestClient) -> None:
    clear_shortener_data()
    payload = {"original_url": "https://example.com", "custom_alias": "duplicate-link"}
    assert client.post("/api/v1/links", json=payload).status_code == 201
    assert client.post("/api/v1/links", json=payload).status_code == 409

    reserved = client.post(
        "/api/v1/links", json={"original_url": "https://example.com", "custom_alias": "health"}
    )
    assert reserved.status_code == 422


def test_expired_and_disabled_links_do_not_redirect(client: TestClient) -> None:
    clear_shortener_data()
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    create = client.post(
        "/api/v1/links",
        json={
            "original_url": "https://example.com",
            "custom_alias": "disable-link",
            "expires_at": future,
        },
    )
    assert create.status_code == 201

    assert client.delete("/api/v1/links/disable-link").status_code == 204
    disabled = client.get("/disable-link", follow_redirects=False)
    assert disabled.status_code == 410

    expired = client.post(
        "/api/v1/links",
        json={"original_url": "https://example.org", "custom_alias": "expired-link"},
    )
    assert expired.status_code == 201
    with SessionLocal() as session:
        link = session.query(Link).filter_by(short_code="expired-link").one()
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    response = client.get("/expired-link", follow_redirects=False)
    assert response.status_code == 410


def test_invalid_destination_and_past_expiration_are_rejected(client: TestClient) -> None:
    clear_shortener_data()
    invalid = client.post("/api/v1/links", json={"original_url": "javascript:alert(1)"})
    assert invalid.status_code == 422

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    response = client.post(
        "/api/v1/links", json={"original_url": "https://example.com", "expires_at": past}
    )
    assert response.status_code == 422
