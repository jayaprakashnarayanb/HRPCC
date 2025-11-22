import argparse
import json
import os
import sys

# Reuse the app's LangChain/LangGraph-based extractor
from app.ai import extract_rules_with_langgraph


def read_policy_text(path: str | None) -> str:
    if path and path != "-":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    # Read from stdin
    data = sys.stdin.read()
    if not data:
        raise SystemExit("No input received on stdin. Pass a file path or pipe text.")
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Use an LLM to translate policy text into JSON rules."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Path to policy text file, or '-' for stdin (default)",
    )
    parser.add_argument(
        "--scope",
        choices=["leave", "benefit", "both"],
        default="both",
        help="Limit extracted rules to a scope (default: both)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )

    args = parser.parse_args()

    # Basic sanity checks for LLM credentials; the underlying client will also validate
    if not os.getenv("GOOGLE_API_KEY"):
        print(
            "Warning: GOOGLE_API_KEY not set. Extraction will fail unless the environment provides valid credentials.",
            file=sys.stderr,
        )

    policy_text = read_policy_text(args.input)

    try:
        rules = extract_rules_with_langgraph(policy_text, scope=args.scope)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if args.pretty:
        print(json.dumps(rules, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(rules, ensure_ascii=False))


if __name__ == "__main__":
    main()

