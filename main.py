import argparse

from sanction_agents import run_sanction_lookup
from services import build_sanction_result_from_local_payload, lookup_local_query
from services import format_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Investigate blockchain sanctions exposure.")
    parser.add_argument("query", help="Blockchain address or sanctioned entity name to investigate.")
    parser.add_argument("--local", action="store_true", help="Use deterministic local lookup without the LLM.")
    parser.add_argument("--neighbors", action="store_true", help="Include one-hop chain-neighbor checks when a provider is configured.")
    parser.add_argument("--json", action="store_true", help="Print structured JSON output.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.local:
        payload = lookup_local_query(args.query, include_neighbors=args.neighbors)
        result = build_sanction_result_from_local_payload(payload)
        if args.json:
            print(result.model_dump_json(indent=2))
            return
        print(format_result(result))
        return

    result = run_sanction_lookup(args.query)

    if args.json:
        print(result.model_dump_json(indent=2))
        return

    print(format_result(result))


if __name__ == "__main__":
    main()
