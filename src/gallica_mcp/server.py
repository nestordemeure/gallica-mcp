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
    Returns paginated results with metadata. Uses exact matching by default.

    Note: To get text snippets showing where your search terms appear within documents,
    use the get_snippets tool with the document identifier and query.

    Args:
        query: Text to search in OCR content. Supports CQL query syntax:
            - Simple text: "Houdini" or "magic tricks" (all words must appear, any order)
            - Exact phrases: '"Harry Houdini"' (use double quotes for exact phrase)
            - AND operator: "magic AND illusion" (both terms must appear - MUST BE UPPERCASE)
            - OR operator: "Houdini OR Houdin" (either term can appear - MUST BE UPPERCASE)
            - NOT operator: "magic NOT card" (first term yes, second term no - MUST BE UPPERCASE)
            - Parentheses: "(Houdini OR Houdin) AND escape" (group operations for precedence)
            - Combine all: '"Harry Houdini" AND (escape OR illusion) NOT death'

            Boolean operators (AND, OR, NOT) MUST be UPPERCASE.
            The query is converted to CQL format automatically and searches OCR text content.

        page: Page number for pagination, 1-indexed (default: 1)

    Returns:
        Dictionary containing:
            - page: Current page number
            - total_results: Total number of matching documents
            - total_pages: Total number of pages available
            - documents: List of documents with:
                - identifier: ARK identifier (use with download_text or get_snippets)
                - title: Document title
                - url: URL to view document on gallica.bnf.fr
                - creators: List of authors/creators
                - date: Publication date (if available)
                - type: Document type (e.g., monographie, périodique)
                - language: Language code (if available)

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
        title: str | None = None,
        public_domain_only: bool = True,
        exact_search: bool = True
    ) -> dict:
        """Search Gallica with advanced filtering options.

        Returns paginated results (up to 50 documents per page) with metadata.
        All parameters are converted to CQL (Contextual Query Language) and combined with AND logic.

        Note: To get text snippets showing where your search terms appear within documents,
        use the get_snippets tool with the document identifier and query.

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
            public_domain_only: Restrict to public domain documents with freely downloadable OCR (default: True).
                Set to False to include all documents regardless of access restrictions. (optional)
            exact_search: Enable exact matching (default: True). When True, disables fuzzy matching for more precise results.
                When False, enables fuzzy matching which may find variants and OCR errors (e.g., "hanussen" matches "haussen").
                Note: Using quotes in the query (e.g., '"exact phrase"') always forces exact matching regardless of this setting. (optional)

        Filter Logic:
            - Multiple creators use OR: (creator1 OR creator2)
            - Multiple doc_types use OR: (type1 OR type2)
            - All filters combine with AND: query AND creators AND types AND dates AND language AND title

        Returns:
            Dictionary containing:
                - page: Current page number
                - total_results: Total number of matching documents
                - total_pages: Total number of pages available
                - documents: List of documents with:
                    - identifier: ARK identifier (use with download_text or get_snippets)
                    - title: Document title
                    - url: URL to view document on gallica.bnf.fr
                    - creators: List of authors/creators
                    - date: Publication date (if available)
                    - type: Document type (e.g., monographie, périodique)
                    - language: Language code (if available)

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

            # Include all documents (not just public domain)
            advanced_search_gallica(query="prestidigitation", public_domain_only=False)

            # Fuzzy matching for finding OCR variants
            advanced_search_gallica(query="Hanussen", exact_search=False)
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
            title=title,
            public_domain_only=public_domain_only,
            exact_search=exact_search
        )


@mcp.tool()
async def download_text(identifier: str) -> str:
    """Download OCR text from a Gallica document and save to cache in plain text format.

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


@mcp.tool()
async def get_snippets(identifier: str, query: str) -> dict:
    """Fetch text snippets showing where search terms appear in a Gallica document.

    Uses the ContentSearch API to find and return text excerpts with page numbers.
    This is useful for locating specific content within a document after searching.

    Args:
        identifier: Gallica ARK identifier (e.g., 'ark:/12148/bpt6k5619759j')
        query: Search terms to find in the document. Supports the same syntax as search_gallica:
            - Simple text: "Houdini" or "magic tricks"
            - Exact phrases: '"Harry Houdini"'
            - Boolean operators: "magic AND illusion", "Houdini OR Houdin"
            - Complex queries: '("Harry Houdini" OR "Jean Houdin") AND escape'

    Returns:
        Dictionary containing:
            - identifier: The document ARK identifier
            - query: The search query used
            - snippets: List of text excerpts with:
                - text: Snippet text showing search terms in context
                - page: Page identifier (e.g., "PAG_200" for page 200)

    Examples:
        # Get snippets for a specific document
        get_snippets("ark:/12148/bpt6k5619759j", "Houdini")

        # Find exact phrase occurrences
        get_snippets("ark:/12148/bpt6k5619759j", '"Harry Houdini"')

        # Complex query
        get_snippets("ark:/12148/bpt6k5619759j", "magic AND (illusion OR escape)")
    """
    client = get_client()
    snippets = await client.get_snippets(identifier=identifier, query=query)
    return {
        'identifier': identifier,
        'query': query,
        'snippets': snippets
    }


@mcp.resource("gallica://info")
async def server_info() -> Resource:
    """Provide information about the Gallica MCP server."""
    return Resource(
        uri="gallica://info",
        name="Gallica MCP Server Info",
        mimeType="text/plain",
        text="""Gallica MCP Server

Provides access to Gallica, the digital library of the Bibliothèque nationale de France (BnF).

Available Tools:
- search_gallica(query, page): Search OCR text with boolean operators (AND, OR, NOT)
- get_snippets(identifier, query): Get text excerpts with page numbers for a specific document
- download_text(identifier): Download full OCR text and cache locally
- advanced_search_gallica(...): Search with filters (authors, dates, types, language)

Query Syntax:
- Boolean operators: AND, OR, NOT (must be UPPERCASE)
- Exact phrases: Use double quotes '"Harry Houdini"'
- Grouping: Use parentheses (A OR B) AND C

By default, searches return only public domain documents with downloadable OCR.
Uses exact matching by default for precise results.
"""
    )


def main():
    """Run the Gallica MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
