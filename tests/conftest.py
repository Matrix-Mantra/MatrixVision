import os

# Tests never touch real services: dev auth, in-memory counters, no Meta key.
os.environ.update({"AUTH_MODE": "dev", "STORE": "memory", "META_API_KEY": "", "DAILY_VISION_LIMIT": "3"})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


AUTH = {"Authorization": "Bearer dev:tester"}
