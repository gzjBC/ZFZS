import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.crawlers.xifan_playwright import XifanCrawlerOptions, XifanPlaywrightCrawler


def main() -> None:
    parser = argparse.ArgumentParser(description="Use Playwright to search xifan.moe / xifanacg.")
    parser.add_argument("keyword", nargs="?", help="Anime keyword")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--headed", action="store_true", help="Show browser flow")
    parser.add_argument("--slow-mo", type=int, default=450)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use the built-in Unicode smoke-test keyword and require at least one result",
    )
    parser.add_argument(
        "--require-results",
        action="store_true",
        help="Exit with a failure code when the search returns no results",
    )
    args = parser.parse_args()

    keyword = "\u65e0\u804c\u8f6c\u751f" if args.smoke else args.keyword
    if not keyword:
        parser.error("keyword is required unless --smoke is used")

    crawler = XifanPlaywrightCrawler(
        XifanCrawlerOptions(headed=args.headed, slow_mo_ms=args.slow_mo)
    )
    results = crawler.search(keyword, limit=args.limit)
    payload = {
        "keyword": keyword,
        "results": [item.model_dump() for item in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if (args.require_results or args.smoke) and not results:
        raise SystemExit("Live smoke test returned no results.")


if __name__ == "__main__":
    main()
