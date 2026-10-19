#!/usr/bin/env python3
"""Check AI provider access and model availability without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

DEFAULT_PROVIDERS = ["openrouter", "openai", "anthropic", "google"]
ALL_PROVIDERS = DEFAULT_PROVIDERS + ["deepseek", "qwen"]


@dataclass(frozen=True)
class Provider:
    name: str
    env_vars: tuple[str, ...]
    models_url: str
    parser: str
    auth_style: str
    requires_key: bool = True
    endpoint_may_be_unsupported: bool = False
    probe_url: str | None = None


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider(
        name="openrouter",
        env_vars=("OPENROUTER_API_KEY",),
        models_url="https://openrouter.ai/api/v1/models",
        parser="data_id",
        auth_style="bearer",
        requires_key=False,
    ),
    "openai": Provider(
        name="openai",
        env_vars=("OPENAI_API_KEY",),
        models_url="https://api.openai.com/v1/models",
        parser="data_id",
        auth_style="bearer",
    ),
    "anthropic": Provider(
        name="anthropic",
        env_vars=("ANTHROPIC_API_KEY",),
        models_url="https://api.anthropic.com/v1/models?limit=1000",
        parser="data_id",
        auth_style="anthropic",
    ),
    "google": Provider(
        name="google",
        env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        models_url="https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
        parser="google_models",
        auth_style="google",
    ),
    "deepseek": Provider(
        name="deepseek",
        env_vars=("DEEPSEEK_API_KEY",),
        models_url="https://api.deepseek.com/models",
        parser="data_id",
        auth_style="bearer",
    ),
    "qwen": Provider(
        name="qwen",
        env_vars=("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        models_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
        parser="data_id",
        auth_style="bearer",
        endpoint_may_be_unsupported=True,
        probe_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    ),
}


class RequestError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 15,
) -> Any:
    data = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = safe_error_detail(error)
        if error.code in {401, 403}:
            raise RequestError("auth_error", detail, error.code) from error
        if error.code == 404:
            raise RequestError("not_found", detail, error.code) from error
        if 500 <= error.code <= 599:
            raise RequestError("provider_error", detail, error.code) from error
        raise RequestError("http_error", detail, error.code) from error
    except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError) as error:
        raise RequestError("network_error", str(error)) from error

    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise RequestError(
            "parse_error", "Provider returned non-JSON output"
        ) from error


def safe_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    if not body:
        return f"HTTP {error.code}"
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return f"HTTP {error.code}: {body[:500]}"
    message = parsed.get("error", parsed)
    if isinstance(message, dict):
        message = message.get("message") or message.get("type") or message
    return f"HTTP {error.code}: {str(message)[:500]}"


def credential(provider: Provider) -> tuple[str | None, str | None]:
    for name in provider.env_vars:
        value = os.environ.get(name)
        if value:
            return name, value
    return None, None


def auth_headers(provider: Provider, key: str | None) -> dict[str, str]:
    if not key:
        return {}
    if provider.auth_style == "bearer":
        return {"Authorization": f"Bearer {key}"}
    if provider.auth_style == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if provider.auth_style == "google":
        return {"x-goog-api-key": key}
    raise ValueError(f"Unknown auth style: {provider.auth_style}")


def parse_models(provider: Provider, payload: Any) -> list[str]:
    if provider.parser == "data_id":
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        return sorted(
            {row["id"] for row in rows if isinstance(row, dict) and row.get("id")}
        )
    if provider.parser == "google_models":
        rows = payload.get("models", []) if isinstance(payload, dict) else []
        names: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not name:
                continue
            names.add(name)
            if name.startswith("models/"):
                names.add(name.split("/", 1)[1])
        return sorted(names)
    raise ValueError(f"Unknown parser: {provider.parser}")


def normalized(value: str) -> str:
    value = value.lower().strip()
    if value.startswith("models/"):
        value = value.split("/", 1)[1]
    return value.replace("_", "-").replace(".", "-")


def suffix(value: str) -> str:
    value = value.split("/", 1)[-1]
    if value.startswith("models/"):
        value = value.split("/", 1)[1]
    return value


def evaluate_model(requested: str | None, models: list[str]) -> dict[str, Any]:
    if not requested:
        return {"model_status": "no_model_requested", "suggestions": []}

    if requested in models:
        return {
            "model_status": "model_available",
            "exact_match": True,
            "matched_model": requested,
            "suggestions": [],
        }

    requested_lower = requested.lower()
    lower_matches = [model for model in models if model.lower() == requested_lower]
    if lower_matches:
        return {
            "model_status": "available_with_case_mismatch",
            "exact_match": False,
            "matched_model": lower_matches[0],
            "suggestions": lower_matches[:5],
        }

    requested_suffix = suffix(requested)
    suffix_matches = [model for model in models if suffix(model) == requested_suffix]
    if suffix_matches:
        return {
            "model_status": "available_with_different_id",
            "exact_match": False,
            "matched_model": suffix_matches[0],
            "suggestions": suffix_matches[:5],
        }

    requested_normalized = normalized(requested)
    normalized_matches = [
        model for model in models if normalized(model) == requested_normalized
    ]
    if normalized_matches:
        return {
            "model_status": "available_with_spelling_variant",
            "exact_match": False,
            "matched_model": normalized_matches[0],
            "suggestions": normalized_matches[:5],
        }

    candidates = list(models)
    normalized_index = {normalized(model): model for model in models}
    close = [
        normalized_index[item]
        for item in get_close_matches(
            requested_normalized, normalized_index, n=5, cutoff=0.58
        )
    ]
    if not close:
        close = get_close_matches(requested, candidates, n=5, cutoff=0.45)
    return {
        "model_status": "model_not_found",
        "exact_match": False,
        "matched_model": None,
        "suggestions": close,
    }


def check_provider(
    provider: Provider,
    *,
    model: str | None,
    timeout: float,
    allow_paid_probe: bool,
) -> dict[str, Any]:
    key_env, key = credential(provider)
    result: dict[str, Any] = {
        "provider": provider.name,
        "checked_env_vars": list(provider.env_vars),
        "key_env": key_env,
        "key_status": "present" if key else "missing_key",
        "network_status": "not_checked",
        "provider_status": "not_checked",
        "model_status": "unverified",
        "suggestions": [],
        "models_checked": 0,
    }

    if provider.requires_key and not key:
        result["provider_status"] = "missing_key"
        result["note"] = (
            "Configure the provider key securely; do not paste it into chat."
        )
        return result

    try:
        payload = request_json(
            provider.models_url,
            headers=auth_headers(provider, key),
            timeout=timeout,
        )
        result["network_status"] = "reachable"
        result["provider_status"] = "available"
        if key:
            result["key_status"] = "accepted"
        models = parse_models(provider, payload)
        result["models_checked"] = len(models)
        result.update(evaluate_model(model, models))
        return result
    except RequestError as error:
        result["error"] = error.message
        result["http_status"] = error.status
        if error.kind == "network_error":
            result["network_status"] = "network_error"
            result["provider_status"] = "unverified"
            return result
        result["network_status"] = "reachable"
        if error.kind == "auth_error":
            result["key_status"] = "auth_error"
            result["provider_status"] = "auth_error"
            return result
        if error.kind == "not_found" and provider.endpoint_may_be_unsupported:
            result["provider_status"] = "endpoint_unsupported"
            result["note"] = (
                "Model-list endpoint is unsupported for this provider; model validity is not disproven."
            )
            if allow_paid_probe and model and key and provider.probe_url:
                return paid_probe(provider, result, model, key, timeout)
            if provider.probe_url and not allow_paid_probe:
                result["probe_status"] = "skipped_requires_explicit_approval"
            return result
        result["provider_status"] = error.kind
        return result


def paid_probe(
    provider: Provider,
    result: dict[str, Any],
    model: str,
    key: str,
    timeout: float,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        request_json(
            provider.probe_url or "",
            method="POST",
            headers=auth_headers(provider, key),
            body=body,
            timeout=timeout,
        )
    except RequestError as error:
        result["probe_status"] = error.kind
        result["probe_error"] = error.message
        if error.kind == "auth_error":
            result["key_status"] = "auth_error"
        elif error.kind in {"not_found", "http_error"}:
            result["model_status"] = "model_not_confirmed_by_probe"
        return result

    result["provider_status"] = "available_by_probe"
    result["key_status"] = "accepted"
    result["model_status"] = "model_available_by_probe"
    result["matched_model"] = model
    result["probe_status"] = "succeeded"
    return result


def parse_providers(raw: str) -> list[str]:
    if raw == "default":
        return DEFAULT_PROVIDERS
    if raw == "all":
        return ALL_PROVIDERS
    selected = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = [item for item in selected if item not in PROVIDERS]
    if unknown:
        raise SystemExit(f"Unknown provider(s): {', '.join(unknown)}")
    return selected


def print_human(results: list[dict[str, Any]]) -> None:
    for result in results:
        print(f"[{result['provider']}]")
        print(
            f"  key: {result['key_status']} ({result.get('key_env') or 'no env var present'})"
        )
        print(f"  network: {result['network_status']}")
        print(f"  provider: {result['provider_status']}")
        print(f"  model: {result['model_status']}")
        if result.get("matched_model"):
            print(f"  matched_model: {result['matched_model']}")
        if result.get("suggestions"):
            print(f"  suggestions: {', '.join(result['suggestions'])}")
        if result.get("note"):
            print(f"  note: {result['note']}")
        if result.get("error") and result["provider_status"] not in {
            "auth_error",
            "missing_key",
        }:
            print(f"  error: {result['error']}")


def strict_exit_code(results: list[dict[str, Any]], model: str | None) -> int:
    if not model:
        return 0
    if any(
        result["model_status"] in {"model_available", "model_available_by_probe"}
        for result in results
    ):
        return 0
    if any(result["model_status"].startswith("available_with_") for result in results):
        return 1
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify AI provider access and model availability without printing API keys.",
    )
    parser.add_argument("--model", help="Model ID to check.")
    parser.add_argument(
        "--providers",
        default="default",
        help="default, all, or comma-separated providers: openrouter,openai,anthropic,google,deepseek,qwen.",
    )
    parser.add_argument(
        "--timeout", type=float, default=15, help="HTTP timeout in seconds."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero unless the model is exactly confirmed available.",
    )
    parser.add_argument(
        "--allow-paid-probe",
        action="store_true",
        help="Allow minimal generation probe for providers without model-list support.",
    )
    args = parser.parse_args(argv)

    selected = parse_providers(args.providers)
    results = [
        check_provider(
            PROVIDERS[name],
            model=args.model,
            timeout=args.timeout,
            allow_paid_probe=args.allow_paid_probe,
        )
        for name in selected
    ]

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print_human(results)

    if args.strict:
        return strict_exit_code(results, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
