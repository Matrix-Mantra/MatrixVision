import httpx
import openai
import pytest

from app import meta_client


def _err(status: int, retry_after: str | None = None) -> openai.APIStatusError:
    headers = {"retry-after": retry_after} if retry_after else {}
    resp = httpx.Response(status, headers=headers, request=httpx.Request("POST", "https://api.meta.ai/v1/responses"))
    return openai.APIStatusError("err", response=resp, body=None)


def test_falls_back_to_next_model_after_retries():
    calls = []

    def fn(model):
        calls.append(model)
        if model == "muse-spark-1.3":
            raise _err(503)
        return "ok"

    result, used = meta_client.call_with_fallback(["muse-spark-1.3", "muse-spark-1.2"], fn,
                                                  max_retries=2, sleep=lambda s: None)
    assert (result, used) == ("ok", "muse-spark-1.2")
    assert calls == ["muse-spark-1.3"] * 3 + ["muse-spark-1.2"]


def test_bad_request_is_not_retried_or_fallen_back():
    calls = []

    def fn(model):
        calls.append(model)
        raise _err(400)

    with pytest.raises(openai.APIStatusError):
        meta_client.call_with_fallback(["a", "b"], fn, max_retries=2, sleep=lambda s: None)
    assert calls == ["a"]


def test_long_retry_after_skips_to_next_model():
    slept = []

    def fn(model):
        if model == "a":
            raise _err(503, retry_after="60")
        return "ok"

    _, used = meta_client.call_with_fallback(["a", "b"], fn, max_retries=2, sleep=slept.append)
    assert used == "b" and slept == []


def test_invalid_json_from_model_falls_back():
    def fn(model):
        if model == "a":
            raise ValueError("not json")
        return "ok"

    assert meta_client.call_with_fallback(["a", "b"], fn, sleep=lambda s: None)[1] == "b"


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["meta_configured"] is False
