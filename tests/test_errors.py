from fastapi.testclient import TestClient


def test_missing_route_uses_standard_error_response(client: TestClient) -> None:
    response = client.get("/does/not/exist", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 404
    assert response.json() == {
        "error": "http_error",
        "detail": "Not Found",
        "request_id": "test-request-id",
    }
