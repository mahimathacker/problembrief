"""CLI entrypoint: run the radar once and print the brief."""
from __future__ import annotations

import os
import sys

from datetime import date

import config
from src import deliver
from src.graph import build_graph


def _provider_model(provider: str) -> str:
    if provider == "openai":
        return config.OPENAI_MODEL
    if provider == "gemini":
        return config.GEMINI_MODEL
    if provider == "github_models":
        return config.GITHUB_MODELS_MODEL
    if provider == "anthropic":
        return config.MODEL
    return "unknown"


def _provider_ready(provider: str) -> tuple[bool, str]:
    if provider == "openai":
        return bool(config.OPENAI_API_KEY), "OPENAI_API_KEY"
    if provider == "gemini":
        return bool(config.GEMINI_API_KEY), "GEMINI_API_KEY"
    if provider == "github_models":
        return bool(config.GITHUB_MODELS_TOKEN), "GITHUB_TOKEN or GITHUB_MODELS_TOKEN"
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip()), "ANTHROPIC_API_KEY"
    return False, "unknown provider"


def main() -> int:
    allowed = {"anthropic", "openai", "gemini", "github_models"}
    chain = []
    for provider in [config.PROVIDER, *config.FALLBACK_PROVIDERS]:
        if provider and provider not in chain:
            chain.append(provider)

    unknown = [p for p in chain if p not in allowed]
    if unknown:
        print(
            "ERROR: RADAR_PROVIDER/RADAR_FALLBACK_PROVIDERS must use one of: "
            f"{', '.join(sorted(allowed))}. Got {unknown!r}."
        )
        return 1

    ready = []
    missing = []
    for provider in chain:
        ok, required = _provider_ready(provider)
        if ok:
            ready.append(provider)
        else:
            missing.append(f"{provider} needs {required}")
    if not ready:
        print("ERROR: no configured LLM provider has credentials.")
        for line in missing:
            print(f"  - {line}")
        return 1
    for line in missing:
        print(f"WARNING: skipping unavailable provider: {line}")

    active = " -> ".join(f"{p}:{_provider_model(p)}" for p in ready)
    print(f"Problembrief — providers={active}\n")
    graph = build_graph()
    final = graph.invoke({})

    if not final.get("raw_items"):
        print("\nNo posts fetched — both sources failed. Check your network.")
        return 1

    path = final.get("brief_path")
    brief = final.get("brief_markdown", "")
    print(f"\n✅ Brief saved to {path}")

    deliver.send_email(f"Problembrief — {date.today().isoformat()}", brief)

    print("=" * 60)
    print(brief)
    return 0


if __name__ == "__main__":
    sys.exit(main())
