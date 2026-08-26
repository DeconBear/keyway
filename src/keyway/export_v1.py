"""Export legacy Python Keyway state to the secret-free KeywayExportV1 contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm_store import LLMStore


def export_keyway_v1(store: LLMStore) -> tuple[dict[str, Any], list[str]]:
    """Return a portable snapshot and semantic-loss warnings.

    Provider/API/client secrets and encrypted secret material are never read or
    emitted. Imported credential metadata therefore requires write-only
    rebinding, and imported client keys require rotation.
    """
    warnings: list[str] = []
    providers = store.list_providers()
    targets = [
        {
            "kind": "managed-api",
            "id": f"target.python.{provider['provider_id']}",
            "providerId": str(provider["provider_id"]),
            "protocol": "anthropic" if provider.get("protocol") == "anthropic" else "openai",
            "baseUrl": str(provider["base_url"]),
            "enabled": bool(provider.get("enabled", True)),
        }
        for provider in providers
    ]
    credential_metadata = []
    for provider in providers:
        if not provider.get("api_key_set"):
            continue
        provider_id = str(provider["provider_id"])
        credential_metadata.append({
            "id": f"credential.python.{provider_id}",
            "providerId": provider_id,
            "label": f"{provider.get('name', provider_id)} (rebind required)",
            "priority": 0,
            "weight": 1,
            "enabled": False,
            "createdAt": str(provider.get("created_at") or _now()),
            "updatedAt": str(provider.get("updated_at") or _now()),
        })

    routes = []
    route_ids_by_alias: dict[str, str] = {}
    for route in store.list_routes():
        mode = str(route.get("mode", "direct"))
        if mode in {"adapter", "fusion", "auto-select"}:
            warnings.append(
                f"route {route['alias']!r} mode {mode!r} exported as direct/priority-failover"
            )
        associations = store.list_route_providers(str(route["route_id"]))
        candidates = [
            {
                "id": f"candidate.python.{association['rp_id']}",
                "targetId": f"target.python.{association['provider_id']}",
                "upstreamModel": str(association["upstream_model"]),
                "priority": int(association.get("priority", index)),
                "weight": 1,
                "enabled": bool(association.get("enabled", True)),
            }
            for index, association in enumerate(associations)
        ]
        if not candidates:
            candidates = [{
                "id": f"candidate.python.{route['route_id']}.primary",
                "targetId": f"target.python.{route['provider_id']}",
                "upstreamModel": str(route["upstream_model"]),
                "priority": 0,
                "weight": 1,
                "enabled": bool(route.get("enabled", True)),
            }]
        exported_route_id = f"route.python.{route['route_id']}"
        route_ids_by_alias[str(route["alias"])] = exported_route_id
        routes.append({
            "id": exported_route_id,
            "alias": str(route["alias"]),
            "mode": "priority-failover" if len(candidates) > 1 else "direct",
            "candidates": candidates,
            "enabled": bool(route.get("enabled", True)),
            "createdAt": str(route.get("created_at") or _now()),
            "updatedAt": str(route.get("updated_at") or _now()),
        })

    issued_keys = [{
        "id": str(key["key_id"]),
        "groupId": str(key["group_id"]),
        "prefix": str(key.get("key_prefix") or ""),
        "name": str(key.get("name") or key["key_id"]),
        "enabled": bool(key.get("enabled", False)),
        "quota": {
            **({"expiresAt": key["expires_at"]} if key.get("expires_at") else {}),
            **({"maxRequests": int(key["max_requests"])} if key.get("max_requests") is not None else {}),
            "usedRequests": int(key.get("used_requests") or 0),
            **({"maxTokens": int(key["max_tokens"])} if key.get("max_tokens") is not None else {}),
            "usedTokens": int(key.get("used_tokens") or 0),
            **({"concurrencyLimit": int(key["concurrency_limit"])} if key.get("concurrency_limit") is not None else {}),
            **({"rpmLimit": int(key["rpm_limit"])} if key.get("rpm_limit") is not None else {}),
        },
    } for key in store.list_keys()]

    usage_events = [
        _usage_event(row, route_ids_by_alias.get(str(row.get("route_alias") or "")))
        for row in store.list_logs(limit=10_000)
    ]
    return {
        "version": 1,
        "exportedAt": _now(),
        "groups": [{
            "id": str(group["group_id"]),
            "name": str(group["name"]),
            "enabled": bool(group.get("enabled", True)),
        } for group in store.list_groups()],
        "targets": targets,
        "credentialMetadata": credential_metadata,
        "routes": routes,
        "budgetPolicies": [],
        "issuedKeys": issued_keys,
        "usageEvents": usage_events,
    }, warnings


def _usage_event(row: dict[str, Any], route_id: str | None) -> dict[str, Any]:
    input_tokens = max(0, int(row.get("request_tokens") or 0))
    output_tokens = max(0, int(row.get("response_tokens") or 0))
    status_code = row.get("status_code")
    succeeded = isinstance(status_code, int) and 200 <= status_code < 400
    return {
        "version": 2,
        "eventId": f"python.{row['log_id']}",
        "requestId": f"python.{row['log_id']}",
        "correlationId": f"python.{row['log_id']}",
        "timestamp": str(row["created_at"]),
        "source": "import",
        **({"providerId": str(row["provider_id"])} if row.get("provider_id") else {}),
        **({"routeId": route_id} if route_id else {}),
        "requestedModel": str(row.get("route_alias") or row.get("upstream_model") or "unknown"),
        "resolvedModel": str(row.get("upstream_model") or "unknown"),
        "operation": "generate",
        "status": "succeeded" if succeeded else "failed",
        "usage": {
            "requests": 1,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
            "reasoningTokens": 0,
            "audioInputTokens": 0,
            "audioOutputTokens": 0,
            "accuracy": "estimated",
        },
        "attempts": [],
        "durationMs": max(0, int(row.get("latency_ms") or 0)),
        "streaming": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export secret-free KeywayExportV1 JSON")
    parser.add_argument("--db", type=Path, required=True, help="Path to legacy Python Keyway SQLite database")
    parser.add_argument("--output", type=Path, required=True, help="Destination JSON file (must not exist)")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite existing output")
    store = LLMStore(args.db)
    try:
        snapshot, warnings = export_keyway_v1(store)
    finally:
        store.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for warning in warnings:
        print(f"warning: {warning}")
    print(f"wrote secret-free KeywayExportV1: {args.output}")


if __name__ == "__main__":
    main()
