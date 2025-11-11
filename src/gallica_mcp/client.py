"""Gallica API client with search and OCR text download capabilities."""

import asyncio
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


class GallicaClient:
    """Client for interacting with Gallica API."""

    SRU_BASE_URL = "https://gallica.bnf.fr/SRU"
    TEXT_BASE_URL = "https://gallica.bnf.fr"
    CONTENT_SEARCH_URL = "https://gallica.bnf.fr/services/ContentSearch"

    # XML namespaces for parsing SRU responses
    NAMESPACES = {
        'srw': 'http://www.loc.gov/zing/srw/',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'oai_dc': 'http://www.openarchives.org/OAI/2.0/oai_dc/'
    }

    def __init__(self, cache_dir: Path | None = None, max_concurrent_requests: int = 5):
        """Initialize Gallica client.

        Args:
            cache_dir: Directory for caching downloaded text files
            max_concurrent_requests: Maximum number of concurrent API requests
        """
        self.cache_dir = cache_dir or Path("cache/gallica")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def search(
        self,
        query: str,
        page: int = 1,
        records_per_page: int = 50,
        creators: list[str] | None = None,
        doc_types: list[str] | None = None,
        date_start: int | None = None,
        date_end: int | None = None,
        language: str | None = None,
        title: str | None = None
    ) -> dict[str, Any]:
        """Search Gallica using SRU protocol and fetch snippets for results.

        Args:
            query: Text to search in OCR content (simple text, not CQL)
            page: Page number (1-indexed)
            records_per_page: Number of results per page (max 50)
            creators: List of creator names (OR logic)
            doc_types: List of document types (OR logic)
            date_start: Earliest publication year (inclusive)
            date_end: Latest publication year (inclusive)
            language: Language code (ISO 639-2)
            title: Text to search in titles

        Returns:
            Dictionary containing:
                - page: Current page number
                - total_results: Total number of matching documents
                - documents: List of document metadata with snippets
        """
        # Build CQL query from parameters
        cql_query = self._build_cql_query(
            query=query,
            creators=creators,
            doc_types=doc_types,
            date_start=date_start,
            date_end=date_end,
            language=language,
            title=title
        )

        # Calculate startRecord (SRU uses 1-based indexing)
        start_record = (page - 1) * records_per_page + 1

        # Ensure records_per_page doesn't exceed API limit
        records_per_page = min(records_per_page, 50)

        # Build SRU request URL
        params = {
            'version': '1.2',
            'operation': 'searchRetrieve',
            'query': cql_query,
            'startRecord': str(start_record),
            'maximumRecords': str(records_per_page)
        }

        response = await self.client.get(self.SRU_BASE_URL, params=params)
        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.text)

        # Extract total number of results
        total_elem = root.find('.//srw:numberOfRecords', self.NAMESPACES)
        total_results = int(total_elem.text) if total_elem is not None else 0

        # Parse individual records
        documents = []
        records = root.findall('.//srw:record', self.NAMESPACES)

        for record in records:
            doc = self._parse_record(record)
            if doc:
                documents.append(doc)

        # Use the original query text for snippet fetching
        search_terms = query.strip() if query else ""

        # Fetch snippets concurrently for all documents
        if documents and search_terms:
            await self._fetch_snippets_for_documents(documents, search_terms)

        return {
            'page': page,
            'total_results': total_results,
            'documents': documents
        }

    def _parse_record(self, record: ET.Element) -> dict[str, Any] | None:
        """Parse a single SRU record into document metadata.

        Args:
            record: XML element representing a record

        Returns:
            Dictionary with document metadata or None if parsing fails
        """
        try:
            # Get Dublin Core metadata
            dc_elem = record.find('.//oai_dc:dc', self.NAMESPACES)
            if dc_elem is None:
                return None

            # Extract identifier (ARK)
            identifier_elem = dc_elem.find('dc:identifier', self.NAMESPACES)
            identifier = identifier_elem.text if identifier_elem is not None else None

            # Extract ARK from full URL (e.g., https://gallica.bnf.fr/ark:/12148/...)
            ark = None
            if identifier and 'ark:/' in identifier:
                ark = identifier.split('gallica.bnf.fr/')[-1]

            # Extract title
            title_elem = dc_elem.find('dc:title', self.NAMESPACES)
            title = title_elem.text if title_elem is not None else "Untitled"

            # Extract creators
            creators = [
                elem.text for elem in dc_elem.findall('dc:creator', self.NAMESPACES)
                if elem.text
            ]

            # Extract publication date
            date_elem = dc_elem.find('dc:date', self.NAMESPACES)
            date = date_elem.text if date_elem is not None else None

            # Extract type
            type_elem = dc_elem.find('dc:type', self.NAMESPACES)
            doc_type = type_elem.text if type_elem is not None else None

            # Extract language
            lang_elem = dc_elem.find('dc:language', self.NAMESPACES)
            language = lang_elem.text if lang_elem is not None else None

            return {
                'identifier': ark,
                'title': title,
                'url': identifier if identifier else None,
                'creators': creators,
                'date': date,
                'type': doc_type,
                'language': language
            }
        except Exception:
            return None

    async def download_text(self, identifier: str) -> str:
        """Download OCR text for a Gallica document.

        Args:
            identifier: Document ARK identifier (e.g., 'ark:/12148/bpt6k5619759j')

        Returns:
            Path to the cached text file
        """
        # Clean identifier (remove ark:/ prefix if present)
        clean_id = identifier.replace('ark:/', '').replace('/', '_')

        # Check cache first
        cache_file = self.cache_dir / f"{clean_id}.txt"
        if cache_file.exists():
            return str(cache_file)

        # Build download URL for plain text
        # Handle both formats: 'ark:/12148/...' and just '12148/...'
        if identifier.startswith('ark:/'):
            text_url = f"{self.TEXT_BASE_URL}/{identifier}.texteBrut"
        else:
            text_url = f"{self.TEXT_BASE_URL}/ark:/{identifier}.texteBrut"

        response = await self.client.get(text_url)
        response.raise_for_status()

        # Save to cache
        cache_file.write_text(response.text, encoding='utf-8')

        return str(cache_file)

    async def _fetch_snippets_for_documents(
        self,
        documents: list[dict[str, Any]],
        search_terms: str
    ) -> None:
        """Fetch snippets concurrently for all documents.

        Args:
            documents: List of document dictionaries to add snippets to
            search_terms: Search terms to use for ContentSearch
        """
        # Create tasks for fetching snippets concurrently
        tasks = [
            self._fetch_snippets_for_document(doc, search_terms)
            for doc in documents
        ]

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_snippets_for_document(
        self,
        document: dict[str, Any],
        search_terms: str
    ) -> None:
        """Fetch snippets for a single document.

        Args:
            document: Document dictionary to add snippets to
            search_terms: Search terms to use for ContentSearch
        """
        # Initialize snippets list
        document['snippets'] = []

        ark = document.get('identifier')
        if not ark:
            return

        # Extract just the document ID (remove ark:/ prefix)
        doc_id = ark.replace('ark:/', '').split('/')[-1]

        try:
            async with self._semaphore:
                params = {
                    'ark': doc_id,
                    'query': search_terms
                }

                response = await self.client.get(
                    self.CONTENT_SEARCH_URL,
                    params=params
                )
                response.raise_for_status()

                # Parse ContentSearch response
                snippets = self._parse_content_search_response(response.text)
                document['snippets'] = snippets[:5]  # Limit to 5 snippets per document

        except Exception:
            # If snippet fetching fails, continue without snippets
            pass

    def _parse_content_search_response(self, xml_text: str) -> list[str]:
        """Parse ContentSearch XML response to extract text snippets.

        Args:
            xml_text: XML response from ContentSearch API

        Returns:
            List of text snippets with search terms in context
        """
        snippets = []

        try:
            root = ET.fromstring(xml_text)

            # Find all content items
            for item in root.findall('.//item'):
                content_elem = item.find('content')
                if content_elem is not None and content_elem.text:
                    # Strip HTML tags but keep the text
                    text = re.sub(r'<[^>]+>', '', content_elem.text)
                    # Clean up whitespace
                    text = ' '.join(text.split())
                    if text:
                        snippets.append(text)

        except Exception:
            pass

        return snippets

    def _build_cql_query(
        self,
        query: str,
        creators: list[str] | None = None,
        doc_types: list[str] | None = None,
        date_start: int | None = None,
        date_end: int | None = None,
        language: str | None = None,
        title: str | None = None
    ) -> str:
        """Build a CQL query from search parameters.

        Args:
            query: Text to search in OCR content
            creators: List of creator names (OR logic)
            doc_types: List of document types (OR logic)
            date_start: Earliest publication year
            date_end: Latest publication year
            language: Language code
            title: Text to search in titles

        Returns:
            CQL query string
        """
        parts = []

        # Text search in OCR content
        if query and query.strip():
            # Check if query contains CQL operators (AND, OR, NOT, parentheses, quotes)
            # If so, use it as-is; otherwise wrap in quotes with 'text all'
            query_stripped = query.strip()
            has_operators = any(op in query_stripped.upper() for op in [' AND ', ' OR ', ' NOT '])
            has_quotes = '"' in query_stripped
            has_parens = '(' in query_stripped or ')' in query_stripped

            if has_operators or has_quotes or has_parens:
                # Query uses CQL syntax, wrap in 'text all (...)' to scope it
                parts.append(f'text all ({query_stripped})')
            else:
                # Simple text query, wrap in quotes
                parts.append(f'text all "{query_stripped}"')

        # Title search
        if title and title.strip():
            parts.append(f'dc.title all "{title.strip()}"')

        # Creators (OR logic)
        if creators:
            creator_parts = [f'dc.creator all "{creator}"' for creator in creators]
            if len(creator_parts) == 1:
                parts.append(creator_parts[0])
            else:
                parts.append(f'({" or ".join(creator_parts)})')

        # Document types (OR logic)
        if doc_types:
            type_parts = [f'dc.type adj "{doc_type}"' for doc_type in doc_types]
            if len(type_parts) == 1:
                parts.append(type_parts[0])
            else:
                parts.append(f'({" or ".join(type_parts)})')

        # Date range
        if date_start is not None:
            parts.append(f'dc.date >= {date_start}')
        if date_end is not None:
            parts.append(f'dc.date <= {date_end}')

        # Language
        if language:
            parts.append(f'dc.language adj "{language}"')

        # If no search criteria, search everything
        if not parts:
            return 'gallica any ""'

        # Join all parts with AND
        return ' and '.join(parts)
