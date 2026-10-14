from __future__ import annotations

import json
from pathlib import Path

from keyway.export_v1 import export_keyway_v1
from keyway.llm_store import LLMStore


def test_export_v1_is_secret_free_and_maps_routes_usage_and_quotas(tmp_path: Path) -> None:
    store = LLMStore(tmp_path / "keyway.db")
    try:
        provider = store.create_provider(
            "ark", "Ark", "https://ark.example.test/v1", "secret-canary"
        )
        route = store.create_route("chat", provider["provider_id"], "glm-5.2")
        key = store.create_key(
            "hashed-client-secret", "db_sk_te", "test", max_requests=10, max_tokens=1000
        )
        store.log_request(
            api_key_id=key["key_id"],
            route_alias="chat",
            provider_id="ark",
            upstream_model="glm-5.2",
            status_code=200,
            request_tokens=4,
            response_tokens=2,
            latency_ms=20,
        )
        snapshot, warnings = export_keyway_v1(store)
    finally:
        store.close()
    assert warnings == []
    assert snapshot["version"] == 1
    assert snapshot["targets"][0]["providerId"] == "ark"
    assert snapshot["routes"][0]["alias"] == "chat"
    assert snapshot["usageEvents"][0]["usage"]["totalTokens"] == 6
    assert snapshot["issuedKeys"][0]["quota"]["maxRequests"] == 10
    encoded = json.dumps(snapshot)
    assert "secret-canary" not in encoded
    assert "hashed-client-secret" not in encoded
    assert "apiKey" not in encoded
    assert "secretRef" not in encoded
    assert "statusCode" not in snapshot["usageEvents"][0]
