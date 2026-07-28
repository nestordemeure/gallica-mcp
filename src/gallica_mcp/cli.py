"""Command-line interface for Gallica search.

A thin wrapper over :class:`GallicaClient` that formats results for reading in a
terminal or by an agent driving the command through a shell. Output is compact
and greppable by default; ``--json`` emits the raw client structures.

Unlike the MCP server, which hides filtering behind an install-time flag, every
filter is available here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from .client import DEFAULT_SORT, SORT_ORDERS, GallicaClient
from .paths import cache_dir

RESULTS_PER_PAGE = 50
DOCUMENT_TYPES = ("monographie", "périodique", "fascicule", "manuscrit", "image", "carte", "partition")
PROGRAM_NAME = "gallica"


class PageRange:
    """A 1-indexed, inclusive range of result pages. ``last is None`` means all."""

    def __init__(self, first: int, last: int | None) -> None:
        self.first = first
        self.last = last

    def contains(self, page: int) -> bool:
        return page >= self.first and (self.last is None or page <= self.last)

    def __str__(self) -> str:
        if self.last is None:
            return f"{self.first}-all"
        if self.last == self.first:
            return str(self.first)
        return f"{self.first}-{self.last}"


def parse_page_range(value: str) -> PageRange:
    """Parse a ``--pages`` value: ``3``, ``2-5`` or ``all``."""
    text = value.strip().lower()

    if text == "all":
        return PageRange(1, None)

    try:
        if "-" in text:
            first_text, _, last_text = text.partition("-")
            first, last = int(first_text), int(last_text)
        else:
            first = last = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a page number, a range like 2-5, or 'all'; got {value!r}"
        ) from None

    if first < 1:
        raise argparse.ArgumentTypeError(f"page numbers start at 1; got {value!r}")
    if last < first:
        raise argparse.ArgumentTypeError(f"page range runs backwards: {value!r}")

    return PageRange(first, last)


def format_document(position: int, document: dict[str, Any]) -> str:
    """Render one search result. Gallica search returns no snippets - use
    ``gallica snippets <ark> <query>`` to locate terms inside a document."""
    lines = []

    lines.append(f"[{position}] {document['identifier']}  ({document.get('date') or 'n.d.'})")

    title = document.get("title") or "Untitled"
    if creators := document.get("creators"):
        title += f" — {', '.join(creators)}"
    lines.append(f"    {title}")

    descriptors = [value for value in (document.get("type"), document.get("language")) if value]
    if descriptors:
        lines.append(f"    {' · '.join(descriptors)}")

    lines.append(f"    {document['url']}")
    return "\n".join(lines)


async def run_search(args: argparse.Namespace) -> int:
    """Fetch the requested pages, streaming results as each page arrives."""
    client = GallicaClient(cache_dir=cache_dir(args.cache_dir))
    collected: list[dict[str, Any]] = []
    total_results = 0
    total_pages = 1

    try:
        page = args.pages.first
        while args.pages.contains(page):
            result = await client.search(
                query=args.query,
                page=page,
                records_per_page=RESULTS_PER_PAGE,
                creators=args.creator,
                doc_types=args.type,
                date_start=args.from_year,
                date_end=args.to_year,
                language=args.language,
                title=args.title,
                public_domain_only=not args.include_restricted,
                exact_search=not args.fuzzy,
                sort=args.sort,
            )

            total_results = result["total_results"]
            total_pages = result["total_pages"]
            documents = result["documents"]

            if page > total_pages:
                break

            if args.json:
                collected.extend(documents)
            else:
                label = args.query or "(filters only)"
                print(f"# {label} — {total_results} results, page {page} of {total_pages}")
                if not documents:
                    print("  (no documents on this page)")
                for offset, document in enumerate(documents):
                    print(format_document((page - 1) * RESULTS_PER_PAGE + offset + 1, document))
                print()

            if page >= total_pages:
                break
            page += 1
    finally:
        await client.close()

    if args.json:
        json.dump(
            {
                "query": args.query,
                "total_results": total_results,
                "total_pages": total_pages,
                "pages_fetched": str(args.pages),
                "documents": collected,
            },
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        print()

    return 0


async def run_snippets(args: argparse.Namespace) -> int:
    """Show where a query appears inside one document."""
    client = GallicaClient(cache_dir=cache_dir(args.cache_dir))

    try:
        snippets = await client.get_snippets(identifier=args.identifier, query=args.query)
    except RuntimeError as error:
        print(f"{PROGRAM_NAME}: {error}", file=sys.stderr)
        return 1
    finally:
        await client.close()

    if args.json:
        json.dump(
            {"identifier": args.identifier, "query": args.query, "snippets": snippets},
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        print()
        return 0

    if not snippets:
        print(f"# {args.identifier} — no occurrences of {args.query}")
        return 0

    print(f"# {args.identifier} — {len(snippets)} occurrence(s) of {args.query}")
    for snippet in snippets:
        print(f"    {snippet.get('page') or 'p.?'}  · {snippet.get('text', '')}")

    return 0


async def run_get(args: argparse.Namespace) -> int:
    """Download a document's OCR text and print the path to the cached file."""
    client = GallicaClient(cache_dir=cache_dir(args.cache_dir))

    try:
        path = await client.download_text(identifier=args.identifier, refresh=args.refresh)
    except RuntimeError as error:
        print(f"{PROGRAM_NAME}: {error}", file=sys.stderr)
        return 1
    finally:
        await client.close()

    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Search Gallica, the digital library of the Bibliothèque nationale de France.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="override the download cache location (default: $XDG_CACHE_HOME/gallica-mcp)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser(
        "search",
        help="search full text, with optional filters",
        description=(
            "Search Gallica's OCR text. Boolean operators AND, OR and NOT must be "
            "UPPERCASE; \"quoted phrases\" match exactly and parentheses group. Results "
            "carry no snippets - follow up with 'gallica snippets' to locate terms "
            "inside a document. The collection is French-dominant, so prefer French "
            "keywords or OR them with other languages."
        ),
    )
    search.add_argument("query", nargs="?", default="", help="search query (optional if filtering)")
    search.add_argument(
        "--pages",
        type=parse_page_range,
        default=PageRange(1, 1),
        metavar="SPEC",
        help="which result pages to fetch: N, N-M, or 'all' (default: 1)",
    )
    search.add_argument(
        "--creator",
        action="append",
        metavar="NAME",
        help="filter by author; repeat for alternatives (OR)",
    )
    search.add_argument(
        "--type",
        action="append",
        choices=DOCUMENT_TYPES,
        help="filter by document type; repeat for alternatives (OR)",
    )
    search.add_argument("--from-year", type=int, metavar="YEAR", help="earliest publication year")
    search.add_argument("--to-year", type=int, metavar="YEAR", help="latest publication year")
    search.add_argument("--language", metavar="CODE", help="ISO 639-2 code, e.g. fre, eng, ger")
    search.add_argument("--title", metavar="TEXT", help="filter on document title")
    search.add_argument(
        "--include-restricted",
        action="store_true",
        help="include documents whose OCR is not freely downloadable",
    )
    search.add_argument(
        "--fuzzy",
        action="store_true",
        help="match variants and OCR errors; much noisier, but finds mis-scanned names",
    )
    search.add_argument(
        "--sort",
        choices=SORT_ORDERS,
        default=DEFAULT_SORT,
        help=(
            "result ordering (default: relevance). Gallica matches loosely and reports "
            "huge totals, so relevance is what surfaces the material worth reading; "
            "use date_asc only on a query you have narrowed enough to sweep whole"
        ),
    )
    search.add_argument("--json", action="store_true", help="emit JSON instead of text")
    search.set_defaults(handler=run_search)

    snippets = subparsers.add_parser(
        "snippets",
        help="locate a query inside one document",
        description=(
            "Show the passages of one document where a query appears, with page numbers. "
            "This is the cheap way to judge whether a search result is worth downloading."
        ),
    )
    snippets.add_argument("identifier", help="ARK identifier, e.g. ark:/12148/bpt6k5619759j")
    snippets.add_argument("query", help="terms to locate within the document")
    snippets.add_argument("--json", action="store_true", help="emit JSON instead of text")
    snippets.set_defaults(handler=run_snippets)

    get = subparsers.add_parser(
        "get",
        help="download a document's OCR text, printing the cache path",
        description=(
            "Download the full OCR text of a document and print the path to the cached "
            "file. Files are large (100KB-1MB+); read slices of them rather than loading "
            "them whole."
        ),
    )
    get.add_argument("identifier", help="ARK identifier, e.g. ark:/12148/bpt6k5619759j")
    get.add_argument(
        "--refresh",
        action="store_true",
        help="re-download even if a cached copy exists",
    )
    get.set_defaults(handler=run_get)

    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        exit_code = asyncio.run(args.handler(args))
    except KeyboardInterrupt:
        exit_code = 130
    except RuntimeError as error:
        print(f"{PROGRAM_NAME}: {error}", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
