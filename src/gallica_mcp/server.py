"""Gallica MCP Server - FastMCP tools for searching and retrieving documents."""

import argparse
import sys
from pathlib import Path

from mcp import Resource
from mcp.server.fastmcp import FastMCP

# Handle both direct execution and package import
try:
    from .client import GallicaClient
except ImportError:
    from gallica_mcp.client import GallicaClient

# Parse command-line arguments
parser = argparse.ArgumentParser(description='Gallica MCP Server')
parser.add_argument('--enable-advanced-search', action='store_true',
                    help='Enable the advanced_search_gallica tool with filter parameters')
# Parse known args to allow FastMCP to handle its own args
args, unknown = parser.parse_known_args()
# Put unknown args back for FastMCP
sys.argv = [sys.argv[0]] + unknown

# Initialize FastMCP server
mcp = FastMCP("Gallica")

# Store the advanced search flag
ENABLE_ADVANCED_SEARCH = args.enable_advanced_search

# Global client singleton
_client: GallicaClient | None = None


def get_client() -> GallicaClient:
    """Get or create the global Gallica client."""
    global _client
    if _client is None:
        cache_dir = Path("cache/gallica")
        _client = GallicaClient(cache_dir=cache_dir)
    return _client


@mcp.tool()
async def search_gallica(query: str, page: int = 1) -> dict:
    """Search Gallica for documents matching a text query.

    Searches across OCR content with support for boolean operators and exact phrases.
    Returns paginated results with metadata and text snippets.

    Args:
        query: Text to search in OCR content. Supports CQL query syntax:
            - Simple text: "Houdini" or "magic tricks" (all words must appear, any order)
            - Exact phrases: '"Harry Houdini"' (use double quotes for exact phrase)
            - AND operator: "magic AND illusion" (both terms must appear - MUST BE UPPERCASE)
            - OR operator: "Houdini OR Houdin" (either term can appear - MUST BE UPPERCASE)
            - NOT operator: "magic NOT card" (first term yes, second term no - MUST BE UPPERCASE)
            - Parentheses: "(Houdini OR Houdin) AND escape" (group operations for precedence)
            - Combine all: '"Harry Houdini" AND (escape OR illusion) NOT death'

            IMPORTANT: Boolean operators (AND, OR, NOT) MUST be in UPPERCASE.
            The query is converted to CQL format automatically and searches OCR text content.

        page: Page number for pagination, 1-indexed (default: 1)

    Returns:
        Dictionary containing:
            - page: Current page number
            - total_results: Total number of matching documents
            - documents: List of documents with:
                - identifier: ARK identifier (use with download_text)
                - title: Document title
                - url: URL to view document on gallica.bnf.fr
                - creators: List of authors/creators
                - date: Publication date (if available)
                - type: Document type (e.g., monographie, périodique)
                - language: Language code (if available)
                - snippets: List of text excerpts showing search terms in context (up to 5 per document)

    Examples:
        # Simple search
        search_gallica(query="Houdini")

        # Exact phrase
        search_gallica(query='"Harry Houdini"')

        # Boolean operators
        search_gallica(query="magic AND illusion")
        search_gallica(query="Houdini OR Houdin")
        search_gallica(query="magic NOT card")

        # Complex query
        search_gallica(query='("Harry Houdini" OR "Jean Houdin") AND (escape OR illusion)')
    """
    client = get_client()
    return await client.search(query=query, page=page, records_per_page=50)


# Conditionally define advanced_search_gallica based on flag
if ENABLE_ADVANCED_SEARCH:
    @mcp.tool()
    async def advanced_search_gallica(
        query: str = "",
        page: int = 1,
        creators: list[str] | None = None,
        doc_types: list[str] | None = None,
        date_start: int | None = None,
        date_end: int | None = None,
        language: str | None = None,
        title: str | None = None
    ) -> dict:
        """Search Gallica with advanced filtering options.

        Returns paginated results (up to 50 documents per page) with metadata and text snippets.
        All parameters are converted to CQL (Contextual Query Language) and combined with AND logic.

        Args:
            query: Text to search in OCR content. Same boolean operator support as search_gallica:
                AND, OR, NOT (UPPERCASE), exact phrases with quotes, parentheses for grouping.
                Use empty string "" to search by filters only. (default: "")
            page: Page number for pagination, 1-indexed (default: 1)
            creators: List of creator/author names to filter by (uses OR logic between names, AND with other filters).
                Examples: ["Victor Hugo"], ["Houdin", "Houdini"] (optional)
            doc_types: List of document types to filter by (uses OR logic between types, AND with other filters).
                Options: "monographie" (books), "périodique" (periodicals), "manuscrit" (manuscripts),
                "image" (images), "carte" (maps), "partition" (musical scores) (optional)
            date_start: Earliest publication year (inclusive). Example: 1800 (optional)
            date_end: Latest publication year (inclusive). Example: 1900 (optional)
            language: Language code (ISO 639-2, 3 letters). Examples: "fre" (French), "eng" (English), "lat" (Latin) (optional)
            title: Text to search in document titles. Simple text, not boolean operators. (optional)

        Filter Logic:
            - Multiple creators use OR: (creator1 OR creator2)
            - Multiple doc_types use OR: (type1 OR type2)
            - All filters combine with AND: query AND creators AND types AND dates AND language AND title

        Returns:
            Dictionary containing:
                - page: Current page number
                - total_results: Total number of matching documents
                - documents: List of documents with:
                    - identifier: ARK identifier (use with download_text)
                    - title: Document title
                    - url: URL to view document on gallica.bnf.fr
                    - creators: List of authors/creators
                    - date: Publication date (if available)
                    - type: Document type (e.g., monographie, périodique)
                    - language: Language code (if available)
                    - snippets: List of text excerpts showing search terms in context (up to 5 per document)

        Examples:
            # Search with author filter
            advanced_search_gallica(query="magic", creators=["Houdin", "Robert-Houdin"])

            # Books only from 19th century
            advanced_search_gallica(query="Paris", doc_types=["monographie"], date_start=1800, date_end=1899)

            # Search by author and type without text query
            advanced_search_gallica(creators=["Victor Hugo"], doc_types=["monographie"])

            # French manuscripts containing "alchimie"
            advanced_search_gallica(query="alchimie", doc_types=["manuscrit"], language="fre")

            # Multiple document types with date range
            advanced_search_gallica(query="Napoleon", doc_types=["monographie", "périodique"], date_start=1800, date_end=1850)
        """
        client = get_client()
        return await client.search(
            query=query,
            page=page,
            records_per_page=50,
            creators=creators,
            doc_types=doc_types,
            date_start=date_start,
            date_end=date_end,
            language=language,
            title=title
        )


@mcp.tool()
async def download_text(identifier: str) -> str:
    """Download OCR text from a Gallica document and save to cache.

    Downloads the full OCR-extracted text from a document and saves it to the local
    cache directory. The text is retrieved in plain text format.

    Args:
        identifier: Gallica ARK identifier (e.g., 'ark:/12148/bpt6k5619759j')

    Returns:
        Path to the cached text file (as string)

    IMPORTANT:
        The downloaded files are VERY LARGE (typically 100KB-1MB+ of text).
        DO NOT attempt to read the entire file into context.
        Use read tools with offset/limit parameters to read specific portions.
        Reading the full file will waste tokens and may cause performance issues.

    Example:
        path = download_text("ark:/12148/bpt6k5619759j")
    """
    client = get_client()
    return await client.download_text(identifier=identifier)


@mcp.resource("gallica://info")
async def server_info() -> Resource:
    """Provide information about the Gallica MCP server."""
    return Resource(
        uri="gallica://info",
        name="Gallica MCP Server Info",
        mimeType="text/plain",
        text="""Gallica MCP Server

Provides access to Gallica, the digital library of the Bibliothèque nationale de France (BnF).

Features:
- Fulltext search across millions of digitized documents
- OCR text retrieval with local caching
- Support for books, periodicals, manuscripts, images, maps, and more

Search Query Syntax (CQL):
- text all "term" - search in full OCR text
- dc.title all "title" - search in titles
- dc.creator all "author" - search by creator
- Combine with: and, or, not
- Operators: all (AND), any (OR), adj (exact phrase)

Document Types:
- monographie (books)
- périodique (periodicals)
- manuscrit (manuscripts)
- image (images)
- carte (maps)

Use search_gallica() to find documents and download_text() to retrieve OCR content.
"""
    )


def main():
    """Run the Gallica MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
