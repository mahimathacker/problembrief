"""CLI entrypoint: run the radar once and print the brief."""
from __future__ import annotations

import os
import sys

import config
from src.graph import build_graph


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: set ANTHROPIC_API_KEY (copy .env.example to .env).")
        return 1

    print(f"Problembrief — model={config.MODEL}\n")
    graph = build_graph()
    final = graph.invoke({})

    if not final.get("raw_items"):
        print("\nNo posts fetched — both sources failed. Check your network.")
        return 1

    path = final.get("brief_path")
    print(f"\n✅ Brief saved to {path}\n")
    print("=" * 60)
    print(final.get("brief_markdown", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
