"""Gallica API client with search and OCR text download capabilities."""

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from .alto import alto_to_text
from .paths import cache_dir as default_cache_dir
from .query_parser import build_text_query_clause, escape_cql_literal
from .ratelimit import (
    CrossProcessRateLimiter,
    CrossProcessTokenBucket,
    configured_interval,
    configured_ocr_burst,
    configured_ocr_refill,
)

USER_AGENT = "gallica-mcp/0.1.0 (historical research tool)"

# Result ordering. The names match the other archive clients; the values are the
# CQL suffix each one appends. Relevance is Gallica's own default, expressed by
# omitting `sortby` entirely rather than by naming a relevance key.
SORT_CLAUSES = {
    "relevance": "",
    "date_asc": " sortby dc.date/sort.ascending",
    "date_desc": " sortby dc.date/sort.descending",
}
SORT_ORDERS = tuple(SORT_CLAUSES)
DEFAULT_SORT = "relevance"

# `ocrquality` is scored out of 100 and compared as a string of the form
# "xx.xx", so a threshold has to be formatted rather than interpolated raw.
OCR_QUALITY_MIN = 0.0
OCR_QUALITY_MAX = 100.0


class GallicaClient:
    """Client for interacting with Gallica API."""

    SRU_BASE_URL = "https://gallica.bnf.fr/SRU"
    CONTENT_SEARCH_URL = "https://gallica.bnf.fr/services/ContentSearch"
    # OCR comes from RequestDigitalElement, one ALTO page per request, with
    # Pagination supplying the page count. The `.texteBrut` qualifier would
    # return a whole document in one call and is what this client used to use,
    # but it now sits behind the anti-bot challenge unconditionally - see the
    # "Text retrieval" note in CLAUDE.md.
    ALTO_URL = "https://gallica.bnf.fr/RequestDigitalElement"
    PAGINATION_URL = "https://gallica.bnf.fr/services/Pagination"

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
        min_request_interval: float | None = None
    ):
        """Initialize Gallica client.

        Args:
            cache_dir: Directory for caching downloaded text files
            max_concurrent_requests: Maximum number of concurrent API requests
            min_request_interval: Minimum delay (seconds) between requests;
                defaults to the configured interval
        """
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # Gallica rejects httpx's default "python-httpx/..." agent with 403, so
        # identify ourselves explicitly.
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={'User-Agent': USER_AGENT},
        )
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)
        # Spacing is shared with every other process using this cache: an
        # instance attribute paces nothing once each CLI call is its own process.
        self._rate_limiter = CrossProcessRateLimiter(
            state_file=self.cache_dir / ".rate-limit",
            min_interval=(
                min_request_interval
                if min_request_interval is not None
                else configured_interval()
            ),
        )
        # The OCR endpoint meters separately and far more tightly than search,
        # so it draws on a second budget on top of the shared pacing.
        self._ocr_budget = CrossProcessTokenBucket(
            state_file=self.cache_dir / ".ocr-budget",
            capacity=configured_ocr_burst(),
            refill_seconds=configured_ocr_refill(),
        )

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
        subject: str | None = None,
        publisher: str | None = None,
        library: str | None = None,
        min_ocr_quality: float | None = None,
        public_domain_only: bool = True,
        exact_search: bool = True,
        sort: str = DEFAULT_SORT
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
            subject: BnF subject heading; catalogued items only, so this returns
                no periodical issues
            publisher: Publisher name as printed on the item
            library: Holding institution, matched against the record's source field
            min_ocr_quality: Lowest acceptable OCR quality score, 0-100; any
                value above 0 excludes material with no usable OCR
            public_domain_only: Restrict to public domain documents with freely downloadable OCR (default True)
            exact_search: Use exact matching (default True). When True, disables fuzzy matching.
            sort: Result ordering, one of SORT_ORDERS (default relevance)

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
            subject=subject,
            publisher=publisher,
            library=library,
            min_ocr_quality=min_ocr_quality,
            public_domain_only=public_domain_only,
            sort=sort
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

        # A rejected query comes back as a diagnostic, not an HTTP error. Left
        # unchecked it reads as "0 results", so a malformed filter looks exactly
        # like a search that genuinely found nothing.
        self._raise_for_diagnostics(root, cql_query)

        # Extract total number of results
        total_elem = root.find('.//srw:numberOfRecords', self.NAMESPACES)
        if total_elem is None or total_elem.text is None:
            raise RuntimeError(
                f"SRU response carried no record count for query: {cql_query}"
            )
        total_results = int(total_elem.text)

        # Parse individual records
        documents = []
        records = root.findall('.//srw:record', self.NAMESPACES)

        for record in records:
            doc = self._parse_record(record)
            if doc:
                documents.append(doc)

        # An empty result set is one empty page, not zero pages, so that callers
        # looping over pages behave the same here as for any other source.
        total_pages = max(1, (total_results + records_per_page - 1) // records_per_page)

        return {
            'page': page,
            'total_results': total_results,
            'total_pages': total_pages,
            'documents': documents
        }

    def _raise_for_diagnostics(self, root: ET.Element, cql_query: str) -> None:
        """Surface an SRU diagnostic as an exception.

        Gallica answers a query it dislikes with HTTP 200 and a diagnostic
        element rather than an error status, so nothing else would notice.
        """
        namespaces = {**self.NAMESPACES, 'diag': 'http://www.loc.gov/zing/srw/diagnostic/'}
        diagnostics = root.findall('.//diag:diagnostic', namespaces)

        if not diagnostics:
            return

        details = []
        for diagnostic in diagnostics:
            message = diagnostic.find('diag:message', namespaces)
            detail = diagnostic.find('diag:details', namespaces)
            parts = [element.text for element in (message, detail) if element is not None]
            details.append(": ".join(part for part in parts if part))

        raise RuntimeError(
            f"Gallica rejected the query: {'; '.join(details) or 'unspecified diagnostic'}"
            f"\nCQL: {cql_query}"
        )

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
                raise RuntimeError(
                    "SRU record carried no oai_dc metadata; the response format "
                    "may have changed"
                )

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
        except (AttributeError, KeyError, TypeError) as error:
            # Returning None here would drop the record from the result set while
            # the reported total still counted it, silently under-reporting a
            # search. For a tool whose value rests on exhaustivity, a loud
            # failure beats a quiet omission.
            raise RuntimeError(
                f"Could not parse a search result record: {error}"
            ) from error

    async def document_structure(self, identifier: str) -> dict[str, Any]:
        """How many pages a document has, and whether any of them carry OCR.

        One cheap request that makes the cost of a download knowable before it
        is spent, which on this source is the difference between a considered
        retrieval and a ban.
        """
        doc_id = self._document_id(identifier)

        # A document's page count never changes, and `get` needs it on every
        # call - including calls that are otherwise served entirely from cache.
        # Re-asking would spend a request against a budget of four to learn
        # something already known.
        structure_file = self.cache_dir / 'pages' / doc_id / 'structure.json'
        if structure_file.exists():
            try:
                return json.loads(structure_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                pass  # A damaged note is worth one request to replace.

        response = await self._rate_limited_get(
            self.PAGINATION_URL, params={'ark': doc_id}
        )
        self._raise_for_refusal(response, f"pagination for {doc_id}")

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            raise RuntimeError(
                f"Could not read Gallica's pagination for {doc_id}: {error}"
            ) from error

        pages_element = root.find('.//nbVueImages')
        if pages_element is None or not (pages_element.text or '').strip():
            raise RuntimeError(
                f"Gallica reported no page count for {doc_id}, so there is nothing "
                "to download. The identifier may not be a digitised document."
            )

        content_element = root.find('.//hasContent')
        has_content = (content_element.text or '').strip().lower() == 'true' \
            if content_element is not None else True

        structure = {
            'identifier': doc_id,
            'total_pages': int(pages_element.text.strip()),
            'has_content': has_content,
        }

        structure_file.parent.mkdir(parents=True, exist_ok=True)
        structure_file.write_text(json.dumps(structure), encoding='utf-8')
        return structure

    async def download_text(
        self,
        identifier: str,
        first_page: int = 1,
        last_page: int | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Download OCR text for a range of a document's pages.

        Gallica serves OCR one page at a time as ALTO XML. Each page is cached
        individually, so a download interrupted by the rate limiter resumes
        where it stopped rather than starting over - which matters when the
        penalty for re-requesting is measured in hours.

        Args:
            identifier: Document ARK identifier (e.g., 'ark:/12148/bpt6k5619759j')
            first_page: First page to fetch, 1-indexed and inclusive
            last_page: Last page, inclusive; None means through the end
            refresh: Ignore cached pages and fetch them again

        Returns:
            A summary carrying the assembled file's path, the range covered and
            what the call actually cost in requests.
        """
        structure = await self.document_structure(identifier)
        doc_id = structure['identifier']
        total_pages = structure['total_pages']

        if first_page > total_pages:
            raise RuntimeError(
                f"{doc_id} has {total_pages} page(s); page {first_page} does not exist."
            )

        last = total_pages if last_page is None else min(last_page, total_pages)
        if last < first_page:
            raise RuntimeError(
                f"Page range {first_page}-{last_page} is empty; last_page must not "
                f"precede first_page."
            )

        page_dir = self.cache_dir / 'pages' / doc_id
        page_dir.mkdir(parents=True, exist_ok=True)

        texts: list[tuple[int, str]] = []
        fetched = 0
        from_cache = 0

        for page in range(first_page, last + 1):
            page_file = page_dir / f"p{page:05d}.txt"

            if page_file.exists() and not refresh:
                texts.append((page, page_file.read_text(encoding='utf-8')))
                from_cache += 1
                continue

            page_text = await self._retrieve_alto_page(doc_id, page)
            page_file.write_text(page_text, encoding='utf-8')
            texts.append((page, page_text))
            fetched += 1

        empty_pages = [page for page, text in texts if not text.strip()]
        if len(empty_pages) == len(texts):
            raise RuntimeError(
                f"Gallica returned no OCR text for pages {first_page}-{last} of "
                f"{doc_id}"
                + ("" if structure['has_content'] else " (the document is flagged as "
                   "having no indexed text)")
                + ". The pages are most likely image-only, which is a property of the "
                "scan rather than a failure to retry."
            )

        # Page numbers are kept in the assembled file: a researcher citing this
        # material needs the page, and the whole point of the snippet workflow
        # is to arrive at a page reference.
        body = "\n\n".join(
            f"--- page {page} ---\n\n{text}" for page, text in texts if text.strip()
        )

        suffix = "" if (first_page, last) == (1, total_pages) else f".p{first_page}-{last}"
        cache_file = self.cache_dir / f"{doc_id}{suffix}.txt"
        cache_file.write_text(body, encoding='utf-8')

        return {
            'path': str(cache_file.resolve()),
            'identifier': doc_id,
            'first_page': first_page,
            'last_page': last,
            'total_pages': total_pages,
            'pages_fetched': fetched,
            'pages_from_cache': from_cache,
            'empty_pages': empty_pages,
        }

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
        root = ET.fromstring(xml_text)

        # Find all content items
        for item in root.findall('.//item'):
            content_elem = item.find('content')
            page_elem = item.find('p_id')

            if content_elem is not None and content_elem.text:
                text = self._clean_snippet(content_elem.text)

                # Extract page identifier
                page_id = page_elem.text if page_elem is not None and page_elem.text else None

                if text:
                    snippets.append({
                        'text': text,
                        'page': page_id
                    })

        return snippets

    @staticmethod
    def _clean_snippet(raw: str) -> str:
        """Turn a ContentSearch <content> payload into readable text.

        The payload is escaped twice: markup arrives as ``&lt;span&gt;`` and
        accented characters as ``&amp;#233;``. Unescaping once exposes the
        markup, which carries a highlight span around each match; that span is
        converted to braces because knowing which token matched is how a reader
        spots substring false positives. A second unescape then resolves the
        remaining character entities.
        """
        text = unescape(raw)
        text = re.sub(
            r"<span[^>]*class=['\"]?highlight['\"]?[^>]*>(.*?)</span>",
            r'{\1}',
            text,
            flags=re.DOTALL,
        )
        text = re.sub(r'<[^>]+>', '', text)
        text = unescape(text)
        return ' '.join(text.split())

    def _build_cql_query(
        self,
        query: str,
        creators: list[str] | None = None,
        doc_types: list[str] | None = None,
        date_start: int | None = None,
        date_end: int | None = None,
        language: str | None = None,
        title: str | None = None,
        subject: str | None = None,
        publisher: str | None = None,
        library: str | None = None,
        min_ocr_quality: float | None = None,
        public_domain_only: bool = True,
        sort: str = DEFAULT_SORT
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
            subject: BnF subject heading
            publisher: Publisher name
            library: Holding institution
            min_ocr_quality: Lowest acceptable OCR quality score, 0-100
            public_domain_only: Restrict to public domain documents
            sort: One of SORT_ORDERS

        Returns:
            CQL query string
        """
        if sort not in SORT_CLAUSES:
            raise ValueError(
                f"Unknown sort order {sort!r}; expected one of {', '.join(SORT_ORDERS)}"
            )

        parts = []

        # Text search in OCR content
        if query and query.strip():
            parts.append(self._build_text_clause(query.strip()))

        # Title search
        if title and title.strip():
            parts.append(self._field_clause('dc.title', 'all', title))

        # Creators (OR logic)
        if creators:
            parts.append(self._any_of('dc.creator', 'all', creators))

        # Document types (OR logic)
        if doc_types:
            parts.append(self._any_of('dc.type', 'adj', doc_types))

        # Subject heading.
        #
        # `dc.subject` carries the BnF's catalogue headings, which is a strict
        # index rather than a ranked one: a heading that does not exist returns
        # nothing at all instead of a loose tail. That makes it the sharpest
        # filter here - and also the narrowest, because only catalogued items
        # carry a heading and periodical *issues* carry none.
        if subject and subject.strip():
            parts.append(self._field_clause('dc.subject', 'all', subject))

        # Publisher, as printed on the item.
        if publisher and publisher.strip():
            parts.append(self._field_clause('dc.publisher', 'all', publisher))

        # Holding institution.
        #
        # `dc.source` is the provenance string, holding library followed by
        # shelfmark ("Bibliothèque nationale de France, département Arts du
        # spectacle, DIAMAQ23513"), so matching words in it selects a library or
        # one of the BnF's departments.
        if library and library.strip():
            parts.append(self._field_clause('dc.source', 'all', library))

        # OCR quality floor.
        #
        # `ocrquality` is scored out of 100 and compared as a "xx.xx" string, so
        # the threshold is formatted rather than interpolated raw.
        if min_ocr_quality is not None:
            if not OCR_QUALITY_MIN <= min_ocr_quality <= OCR_QUALITY_MAX:
                raise ValueError(
                    f"min_ocr_quality must be between {OCR_QUALITY_MIN:.0f} and "
                    f"{OCR_QUALITY_MAX:.0f}; got {min_ocr_quality}"
                )
            parts.append(f'ocrquality >= "{min_ocr_quality:.2f}"')

        # Date range.
        #
        # `dc.date` is a string index: relational comparison against it either
        # errors or silently matches nothing, so a date-filtered search quietly
        # returned zero results. `gallicapublication_date` is the index that
        # actually supports ranges, and it wants full YYYY/MM/DD bounds.
        if date_start is not None:
            parts.append(f'gallicapublication_date>="{date_start}/01/01"')
        if date_end is not None:
            parts.append(f'gallicapublication_date<="{date_end}/12/31"')

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

        # Ordering.
        #
        # Gallica's `text adj` is a ranked match rather than a strict filter: a
        # phrase search reports six-figure totals whose tail is barely related.
        # Relevance ordering is therefore what makes the source usable at all —
        # the material worth reading sits in the first page or two. Sorting by
        # date instead buries it behind thousands of weak matches, so date order
        # is for bounded sweeps (a filtered range you intend to read whole),
        # never for exploring a large result set.
        suffix = SORT_CLAUSES[sort]
        return f'{cql}{suffix}'

    def _build_text_clause(self, query: str) -> str:
        """Normalize a user text query into a valid CQL clause."""
        return build_text_query_clause(query)

    @staticmethod
    def _field_clause(index: str, relation: str, value: str) -> str:
        """One `index relation "value"` clause, with the value made safe.

        Filter values are user-supplied and land inside a quoted CQL literal, so
        an unescaped quote in one would truncate the literal and get the whole
        query rejected.
        """
        return f'{index} {relation} "{escape_cql_literal(value.strip())}"'

    @classmethod
    def _any_of(cls, index: str, relation: str, values: list[str]) -> str:
        """Match any of several values against one index (OR), parenthesised.

        The parentheses matter: the caller joins clauses with `and`, which binds
        tighter than `or` in CQL, so a bare alternation would silently regroup.
        """
        clauses = [cls._field_clause(index, relation, value) for value in values]
        if len(clauses) == 1:
            return clauses[0]
        return f'({" or ".join(clauses)})'

    async def _rate_limited_get(self, url: str, **kwargs) -> httpx.Response:
        """Issue a GET request honoring concurrency and rate limits."""
        async with self._request_semaphore:
            await self._wait_for_request_slot()
            response = await self.client.get(url, **kwargs)
            return response

    async def _wait_for_request_slot(self) -> None:
        """Ensure minimum spacing between outbound requests, across processes."""
        await self._rate_limiter.acquire()

    def _normalize_identifier(self, identifier: str) -> str:
        """Ensure identifier is an ark:/... string recognized by Gallica."""
        ident = identifier.strip()
        if ident.startswith('ark:/'):
            return ident
        if ident.startswith('ark:'):
            ident = ident[len('ark:'):]
        ident = ident.lstrip('/')
        return f"ark:/{ident}"

    async def _retrieve_alto_page(self, doc_id: str, page: int) -> str:
        """Fetch one page of OCR as ALTO XML and reduce it to plain text."""
        await self._ocr_budget.acquire()

        try:
            response = await self._rate_limited_get(
                self.ALTO_URL, params={'O': doc_id, 'E': 'ALTO', 'Deb': page}
            )
        except httpx.TimeoutException as error:
            # Once the OCR budget has been overdrawn repeatedly, Gallica stops
            # answering at all rather than returning a further 429 - the
            # connection simply hangs. A timeout here is therefore a throttling
            # signal, not a network blip, and retrying deepens it.
            raise RuntimeError(
                f"Gallica stopped responding while fetching page {page} of {doc_id} "
                f"({error}). On this endpoint a stall follows repeated rate limiting; "
                "treat it as a block, stop downloading, and come back later. Pages "
                "already fetched are cached."
            ) from error
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Could not reach Gallica for page {page} of {doc_id}: {error}"
            ) from error

        if response.status_code == 429 or self._is_challenge_page(response.text):
            await self._ocr_budget.drain()
        self._raise_for_refusal(response, f"page {page} of {doc_id}")

        try:
            return alto_to_text(response.content)
        except ET.ParseError as error:
            raise RuntimeError(
                f"Gallica returned unreadable ALTO for page {page} of {doc_id}: {error}"
            ) from error

    def _raise_for_refusal(self, response: httpx.Response, what: str) -> None:
        """Turn Gallica's two ways of saying no into one explicit error.

        The download endpoints refuse in two different shapes, and neither is a
        plain error status: `RequestDigitalElement` answers an exhausted budget
        with HTTP 429, while the site as a whole answers traffic it dislikes
        with HTTP 200 carrying an anti-bot challenge page. Both have to stop the
        download, because a challenge page written to the cache would sit there
        masquerading as the document's text.
        """
        if response.status_code == 429:
            raise RuntimeError(
                f"Gallica rate-limited the download of {what} (HTTP 429). Its OCR "
                "endpoint allows only a short burst before refusing, and it refills "
                "slowly. Pages already fetched are cached, so re-running the same "
                "command after a few minutes resumes rather than restarts - but do "
                "not retry in a loop."
            )

        if self._is_challenge_page(response.text):
            raise RuntimeError(
                f"Gallica served an anti-bot challenge instead of {what}. Too many "
                "requests have been made recently. Stop querying Gallica: the block "
                "lasts hours, and retrying extends it."
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Gallica returned HTTP {response.status_code} for {what}."
            )

    @staticmethod
    def _is_challenge_page(html_text: str) -> bool:
        """Whether a 200 response is really Gallica's anti-bot interstitial.

        The challenge is byte-identical whatever document was asked for, and
        carries none of its content, so it must never reach the cache.
        """
        head = html_text[:4000].lower()
        return any(
            marker in head
            for marker in ("altcha", "vérification de sécurité", "verification de securite")
        )

    @staticmethod
    def _document_id(identifier: str) -> str:
        """The bare document id Gallica's OCR services want.

        `RequestDigitalElement` and `Pagination` take the trailing id
        ("bpt6k5619759j"), not the full ARK the SRU reports.
        """
        return identifier.strip().rstrip('/').rsplit('/', 1)[-1]
