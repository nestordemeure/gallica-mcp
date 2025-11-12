"""Gallica API client with search and OCR text download capabilities."""

import asyncio
import re
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from .query_parser import build_text_query_clause


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

    def __init__(
        self,
        cache_dir: Path | None = None,
        max_concurrent_requests: int = 1,
        min_request_interval: float = 1.0
    ):
        """Initialize Gallica client.

        Args:
            cache_dir: Directory for caching downloaded text files
            max_concurrent_requests: Maximum number of concurrent API requests
            min_request_interval: Minimum delay (seconds) between requests
        """
        self.cache_dir = cache_dir or Path("cache/gallica")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._rate_limit_lock = asyncio.Lock()
        self._min_request_interval = max(min_request_interval, 0.0)
        self._last_request_time = 0.0

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
        title: str | None = None,
        public_domain_only: bool = True,
        exact_search: bool = True
    ) -> dict[str, Any]:
        """Search Gallica using the SRU protocol.

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
            public_domain_only: Restrict to public domain documents with freely downloadable OCR (default True)
            exact_search: Use exact matching (default True). When True, disables fuzzy matching.

        Returns:
            Dictionary containing:
                - page: Current page number
                - total_results: Total number of matching documents
                - documents: List of document metadata
        """
        # Build CQL query from parameters
        cql_query = self._build_cql_query(
            query=query,
            creators=creators,
            doc_types=doc_types,
            date_start=date_start,
            date_end=date_end,
            language=language,
            title=title,
            public_domain_only=public_domain_only
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
            'maximumRecords': str(records_per_page),
            'collapsing': 'false',  # Return all individual issues, not collapsed by periodical
            'exactSearch': 'true' if exact_search else 'false'  # Control fuzzy matching
        }

        response = await self._rate_limited_get(self.SRU_BASE_URL, params=params)
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

        Note:
            With collapsing=false, periodical issues are returned as individual
            records with dc:identifier pointing directly to the issue ARK.
            The extraRecordData/uri field provides a fallback identifier.
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
        clean_id = identifier.replace('ark:/', '').replace('/', '_')

        cache_file = self.cache_dir / f"{clean_id}.txt"
        if cache_file.exists():
            return str(cache_file.resolve())

        ark_identifier = self._normalize_identifier(identifier)
        html_text = await self._retrieve_texte_brut(ark_identifier)
        plain_text = self._html_to_plain_text(html_text)

        cache_file.write_text(plain_text, encoding='utf-8')
        return str(cache_file.resolve())

    async def get_snippets(self, identifier: str, query: str) -> list[dict[str, Any]]:
        """Fetch text snippets for a specific document using the ContentSearch API.

        Args:
            identifier: Document ARK identifier (e.g., 'ark:/12148/bpt6k5619759j')
            query: Search terms to find in the document

        Returns:
            List of dictionaries containing:
                - text: Text snippet showing search terms in context
                - page: Page identifier (e.g., "PAG_200" for page 200)

        Example:
            snippets = await client.get_snippets("ark:/12148/bpt6k5619759j", "Houdini")
        """
        # Extract just the document ID (remove ark:/ prefix)
        ark = self._normalize_identifier(identifier)
        doc_id = ark.replace('ark:/', '').split('/')[-1]

        try:
            params = {
                'ark': doc_id,
                'query': query.strip()
            }

            response = await self._rate_limited_get(
                self.CONTENT_SEARCH_URL,
                params=params
            )
            response.raise_for_status()

            # Parse ContentSearch response
            return self._parse_content_search_response(response.text)

        except Exception as e:
            raise RuntimeError(f"Failed to fetch snippets for {identifier}: {e}")

    def _parse_content_search_response(self, xml_text: str) -> list[dict[str, Any]]:
        """Parse ContentSearch XML response to extract text snippets with page numbers.

        Args:
            xml_text: XML response from ContentSearch API

        Returns:
            List of dictionaries containing:
                - text: Text snippet with search terms in context
                - page: Page identifier (e.g., "PAG_200" for page 200)
        """
        snippets = []

        try:
            root = ET.fromstring(xml_text)

            # Find all content items
            for item in root.findall('.//item'):
                content_elem = item.find('content')
                page_elem = item.find('p_id')

                if content_elem is not None and content_elem.text:
                    # Strip HTML tags but keep the text
                    text = re.sub(r'<[^>]+>', '', content_elem.text)
                    # Clean up whitespace
                    text = ' '.join(text.split())

                    # Extract page identifier
                    page_id = page_elem.text if page_elem is not None and page_elem.text else None

                    if text:
                        snippets.append({
                            'text': text,
                            'page': page_id
                        })

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
        title: str | None = None,
        public_domain_only: bool = True
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
            public_domain_only: Restrict to public domain documents

        Returns:
            CQL query string
        """
        parts = []

        # Text search in OCR content
        if query and query.strip():
            parts.append(self._build_text_clause(query.strip()))

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

        # Access rights (public domain)
        if public_domain_only:
            parts.append('dc.rights any "domaine public"')

        # If no search criteria, search everything
        if not parts:
            cql = 'gallica any ""'
        else:
            # Join all parts with AND
            cql = ' and '.join(parts)

        return f'{cql} sortby dc.date/sort.ascending'

    def _build_text_clause(self, query: str) -> str:
        """Normalize a user text query into a valid CQL clause."""
        return build_text_query_clause(query)

    async def _rate_limited_get(self, url: str, **kwargs) -> httpx.Response:
        """Issue a GET request honoring concurrency and rate limits."""
        async with self._request_semaphore:
            await self._wait_for_request_slot()
            response = await self.client.get(url, **kwargs)
            return response

    async def _wait_for_request_slot(self) -> None:
        """Ensure minimum spacing between outbound requests."""
        if self._min_request_interval <= 0:
            return

        async with self._rate_limit_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_time = self._min_request_interval - (now - self._last_request_time)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                now = loop.time()
            self._last_request_time = now

    def _normalize_identifier(self, identifier: str) -> str:
        """Ensure identifier is an ark:/... string recognized by Gallica."""
        ident = identifier.strip()
        if ident.startswith('ark:/'):
            return ident
        if ident.startswith('ark:'):
            ident = ident[len('ark:'):]
        ident = ident.lstrip('/')
        return f"ark:/{ident}"

    async def _retrieve_texte_brut(self, ark_identifier: str) -> str:
        """Try multiple texteBrut URL permutations until one returns content."""
        urls = self._build_texte_brut_urls(ark_identifier)
        errors: list[str] = []

        for url in urls:
            try:
                response = await self._rate_limited_get(url)
            except httpx.HTTPError as exc:
                errors.append(f"{url} -> {exc}")
                continue

            if response.status_code == 200 and response.text.strip():
                return response.text

            errors.append(f"{url} -> HTTP {response.status_code}")

        error_message = (
            "Unable to download texteBrut for "
            f"{ark_identifier} (tried: {'; '.join(errors)})"
        )
        raise RuntimeError(error_message)

    def _build_texte_brut_urls(self, ark_identifier: str) -> list[str]:
        """Generate the common texteBrut URL variants Gallica supports."""
        base = f"{self.TEXT_BASE_URL}/{ark_identifier.strip('/')}"
        return [
            f"{base}.texteBrut",
            f"{base}/texteBrut",
        ]

    def _html_to_plain_text(self, html_text: str) -> str:
        """Convert Gallica's texteBrut HTML page into normalized plain text."""
        text = html_text

        # Preserve logical breaks before dropping remaining tags.
        text = re.sub(r'(?i)<\s*br\s*/?>', '\n', text)
        text = re.sub(r'(?i)<\s*hr\b[^>]*>', '\n___GALLICA_HR___\n', text)
        text = re.sub(
            r'(?i)</?\s*(p|div|section|article|li|h[1-6]|tr|td|table)\b[^>]*>',
            '\n',
            text,
        )

        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('___GALLICA_HR___', '<hr>')
        text = unescape(text)
        text = text.replace('\r', '')

        # Collapse excessive whitespace while keeping intentional blank lines.
        text = re.sub(r'[\t\x0b\f]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +\n', '\n', text)
        text = re.sub(r'\n +', '\n', text)
        text = re.sub(r' {2,}', ' ', text)

        return text.strip()
