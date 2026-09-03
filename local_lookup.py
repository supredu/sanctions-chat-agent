import argparse
import json

from tools.local_sanctions import lookup_local_sanctions, search_local_entities


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query local sanctions source files.")
    parser.add_argument("query", help="Blockchain address or entity name to query.")
    parser.add_argument("--entity", action="store_true", help="Search entity names instead of addresses.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum entity results.")
    parser.add_argument("--pretty", action="store_true", help="Print a compact human-readable summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    hits = search_local_entities(args.query, limit=args.limit) if args.entity else lookup_local_sanctions(args.query)

    if not args.pretty:
        print(json.dumps({"query": args.query, "hit_count": len(hits), "hits": hits}, indent=2))
        return

    print(f"Query: {args.query}")
    print(f"Hits: {len(hits)}")
    for index, hit in enumerate(hits, start=1):
        if args.entity:
            print(f"\n[{index}] {hit.get('name')} ({hit.get('source')})")
            print(f"Score: {hit.get('score')}")
            print(f"Authority: {hit.get('authority') or 'unknown'}")
            print(f"Authority ID: {hit.get('authority_id') or 'unknown'}")
            print(f"Sanction dates: {', '.join(hit.get('sanction_dates') or []) or 'not available from this source'}")
            print(f"Publication date: {hit.get('publication_date') or 'not available from this source'}")
            print(f"Program: {', '.join(hit.get('programs') or []) or 'unknown'}")
            print(f"Reason: {', '.join(hit.get('reasons') or []) or 'unknown'}")
            addresses = hit.get("addresses") or []
            print(f"Addresses: {len(addresses)}")
            for address in addresses[:5]:
                print(f"  - {address.get('address')} ({address.get('currency') or 'unknown'})")
            continue

        print(f"\n[{index}] {hit.get('source')}")
        print(f"Entity: {hit.get('entity_name') or 'unknown'}")
        print(f"Authority: {hit.get('authority') or 'unknown'}")
        print(f"Authority ID: {hit.get('authority_id') or 'unknown'}")
        print(f"Currency: {hit.get('currency') or 'unknown'}")
        print(f"Sanction dates: {', '.join(hit.get('sanction_dates') or []) or 'not available from this source'}")
        print(f"Publication date: {hit.get('publication_date') or 'not available from this source'}")
        print(f"Program: {', '.join(hit.get('program') or []) or 'unknown'}")
        print(f"Reason: {', '.join(hit.get('reason') or []) or 'unknown'}")
        urls = hit.get("source_urls") or []
        print(f"Source URL: {urls[0] if urls else 'unknown'}")


if __name__ == "__main__":
    main()
