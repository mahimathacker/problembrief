"""CLI entrypoint: run the radar once and print the brief."""
from __future__ import annotations

import os
import sys

from datetime import date

import config
from src import deliver
from src.graph import build_graph


def main() -> int:
    if config.PROVIDER == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            print("ERROR: set OPENAI_API_KEY (or use RADAR_PROVIDER=anthropic/gemini).")
            return 1
        active_model = config.OPENAI_MODEL
    elif config.PROVIDER == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            print("ERROR: set GEMINI_API_KEY (or use RADAR_PROVIDER=anthropic/openai).")
            return 1
        active_model = config.GEMINI_MODEL
    else:
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("ERROR: set ANTHROPIC_API_KEY (copy .env.example to .env).")
            return 1
        active_model = config.MODEL

    print(f"Problembrief — provider={config.PROVIDER} model={active_model}\n")
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
