# Gallica MCP Server

MCP server for searching and retrieving documents from Gallica, the digital library of the Bibliothèque nationale de France (BnF).

## Stack

- Python ≥3.12, uv, fastMCP ≥2.0.0, httpx ≥0.27.0

## Functionality

- **Fulltext search** with CQL operators (AND, OR, NOT, exact phrases)
- **Exact vs. fuzzy matching** control (exact matching by default)
- **Access rights filtering** for public domain documents (downloadable OCR)
- **Text snippets** showing search terms in context (via optional get_snippets tool using ContentSearch API)
- **OCR text download** by page range, with per-page local caching
- **Pagination support** (up to 50 results per page)

## Structure

```
gallica-mcp/
├── .claude/skills/gallica-search/   # Skill documenting the CLI
├── src/gallica_mcp/
│   ├── __init__.py
│   ├── alto.py             # ALTO XML -> plain text
│   ├── client.py           # API client + caching
│   ├── cli.py              # `gallica` command-line interface
│   ├── paths.py            # Cache location resolution
│   ├── query_parser.py     # CQL query construction
│   ├── server.py           # FastMCP tools
│   └── install.py          # MCP server installer
├── pyproject.toml
└── CLAUDE.md               # This file
```

`client.py` holds all the behaviour; `server.py` and `cli.py` are thin presentation layers over it, so search semantics and caching stay identical no matter how it is called. The CLI exposes every filter unconditionally, where the MCP server hides them behind `--enable-advanced-search`.

## API Details

**Search API:**
- Protocol: SRU (Search/Retrieve via URL) version 1.2
- Base URL: `https://gallica.bnf.fr/SRU`
- Query language: CQL (Contextual Query Language)
- Response format: XML with Dublin Core metadata
- **Collapsing:** Uses `collapsing=false` parameter to return all individual periodical issues separately (not collapsed by collection)

**ContentSearch API:**
- Base URL: `https://gallica.bnf.fr/services/ContentSearch`
- Returns text snippets with search terms highlighted
- Used by the `get_snippets` tool (requests go through the rate limiter: default one request per 3s, single concurrency)

**Text Retrieval (ALTO, page by page):**
- OCR: `https://gallica.bnf.fr/RequestDigitalElement?O=<id>&E=ALTO&Deb=<page>`
- Page count: `https://gallica.bnf.fr/services/Pagination?ark=<id>` — `nbVueImages` and `hasContent`
- Both take the **bare document id** (`bpt6k5619759j`), not the full ARK the SRU reports; `_document_id` strips it
- Document identifiers elsewhere: ARK format (`ark:/12148/...`)

**`.texteBrut` is no longer usable, and this is why the client stopped using it.**
`https://gallica.bnf.fr/[ark].texteBrut` returned a whole document's OCR in one
request, which is why it was the original implementation. It now redirects to
`/services/engine/search/altcha` and serves the anti-bot challenge
*unconditionally* — verified on a cold connection with no recent traffic, with
both the client's own User-Agent and a full browser one, while SRU search
answered normally seconds either side. It is not throttling and it is not
fixable from here. ALTO is the documented alternative
([api.bnf.fr](https://api.bnf.fr/fr/api-document-de-gallica)) and it works, at
the cost of one request per page.

## Usage

**Development:**
```bash
uv run fastmcp dev src/gallica_mcp/server.py
```

**Installation:**
```bash
# Basic installation
uv run gallica-mcp-install

# With advanced search enabled
uv run gallica-mcp-install --enable-advanced-search
```

The `--enable-advanced-search` flag enables the `advanced_search_gallica` tool. Without it, only `search_gallica`, `get_snippets`, and `download_text` are available.

**Search Examples:**
```python
# Simple text search
search_gallica(query="Houdini")
search_gallica(query="magic tricks")

# Exact phrase matching
search_gallica(query='"Harry Houdini"')

# Boolean operators
search_gallica(query="magic AND illusion")
search_gallica(query="Houdini OR Houdin")
search_gallica(query="magic NOT card")

# Complex queries with parentheses
search_gallica(query='("Harry Houdini" OR "Jean Houdin") AND (escape OR illusion)')

# Advanced search with author filter (OR logic for multiple authors)
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

# Fuzzy matching for finding OCR errors and variants
advanced_search_gallica(query="Hanussen", exact_search=False)

# Get snippets for a specific document
get_snippets(identifier="ark:/12148/bpt6k5619759j", query="Houdini")

# Get snippets with complex query
get_snippets(identifier="ark:/12148/bpt6k5619759j", query="magic AND (illusion OR escape)")
```

## Search Interface

Three main tools are available (advanced search is optional):

**`search_gallica(query, page=1, sort="relevance")`** - Text search with boolean operators (always available)
- Query supports CQL boolean operators: AND, OR, NOT
- Exact phrase matching with quotes: "Harry Houdini"
- Grouping with parentheses: (A OR B) AND C
- Searches across all OCR content
- Returns document metadata (without snippets for faster searches)

**`get_snippets(identifier, query)`** - Fetch text excerpts for a specific document (always available)
- Takes a document identifier (ARK) and search query
- Returns text snippets showing where search terms appear
- Includes page numbers for each snippet (e.g., "PAG_200" for page 200)
- Useful for locating specific content within a document after searching

**`advanced_search_gallica(...)`** - Advanced search with filters (optional, enabled with `--enable-advanced-search`)
- All parameters are optional (except defaults)
- Same query syntax as search_gallica (with boolean support)
- Provides separate parameters for common filters:

### Query Syntax

**IMPORTANT:** By default, searches use **exact matching** for precise results. The `exact_search` parameter in `advanced_search_gallica` can be set to `False` to enable fuzzy matching (which may find OCR errors and variants).

The `query` parameter supports:

1. **Simple text** - All words must appear (AND logic by default)
   - `"Houdini"` → finds "Houdini"
   - `"magic tricks"` → finds both "magic" AND "tricks" (any order)

2. **Exact phrases** - Use double quotes for phrase matching
   - `'"Harry Houdini"'` → exact phrase only
   - `'"hanussen"'` → exact word only

3. **AND operator** - Explicit AND (uppercase)
   - `"magic AND illusion"` → both must appear
   - `"Paris AND France"` → both must appear

4. **OR operator** - Either term (uppercase)
   - `"Houdini OR Houdin"` → either name
   - `"escape OR évasion"` → either term

5. **NOT operator** - Exclude terms (uppercase)
   - `"magic NOT card"` → "magic" yes, "card" no
   - `"Paris NOT Texas"` → "Paris" yes, "Texas" no

6. **Parentheses** - Group operations
   - `"(Houdini OR Houdin) AND escape"` → (either name) AND escape
   - `"magic AND (illusion OR trick)"` → magic AND (either illusion or trick)

7. **Complex combinations**
   - `'"Harry Houdini" AND (escape OR illusion) NOT death'`
   - `'("Robert-Houdin" OR Houdini) AND (magic OR prestidigitation)'`

**Important:** Operators (AND, OR, NOT) must be UPPERCASE

**Parameters:**
- `query` (str) - Text to search in OCR content (simple text, not CQL)
- `page` (int) - Page number for pagination (default: 1)
- `creators` (list[str]) - Filter by author names (OR logic)
- `doc_types` (list[str]) - Filter by document types (OR logic)
- `date_start` (int) - Earliest publication year (inclusive)
- `date_end` (int) - Latest publication year (inclusive)
- `language` (str) - Language code (ISO 639-2, 3 letters)
- `title` (str) - Text to search in document titles
- `subject` (str) - BnF catalogue subject heading, French, subdivided with ` -- `
- `publisher` (str) - Publisher as printed on the item
- `library` (str) - Holding institution, matched against `dc.source`
- `min_ocr_quality` (float) - Lowest acceptable OCR score, 0-100
- `public_domain_only` (bool) - Restrict to public domain documents with downloadable OCR (default: True)
- `exact_search` (bool) - Enable exact matching (default: True). Set to False for fuzzy matching

**Document Types:**
- `monographie` - Books
- `périodique` - Periodicals/journals
- `manuscrit` - Manuscripts
- `image` - Images
- `carte` - Maps and plans
- `partition` - Musical scores

**Language Codes (ISO 639-2):**
- `fre` - French
- `eng` - English
- `lat` - Latin
- `ger` - German
- `ita` - Italian
- `spa` - Spanish

## Search Behavior

### Exact vs. Fuzzy Matching

**Default: Exact Matching** (`exact_search=True`)
- Searches are precise, matching only exact terms
- "Hanussen" finds only "Hanussen" (465 results)
- Recommended for most use cases

**Fuzzy Matching** (`exact_search=False`)
- Searches find variants and OCR errors
- "Hanussen" finds "Hanussen", "Haussen", "Hansen", etc. (6,450 results)
- Useful for finding documents with OCR errors
- Can produce many irrelevant results

**Note:** Using quotes in the query (e.g., `'"exact phrase"'`) always forces exact phrase matching regardless of the `exact_search` setting.

### Public Domain Filtering

**By default**, searches return only **public domain documents** with freely downloadable OCR (`public_domain_only=True`).

To include **all documents** regardless of access restrictions:

```python
# Include documents with usage restrictions
advanced_search_gallica(query="prestidigitation", public_domain_only=False)
```

**Default behavior:**
- Only public domain documents are returned using the filter: `dc.rights any "domaine public"`
- All documents have downloadable OCR text
- Ensures users can access the full text of search results
- **Excludes restricted documents** such as RetroNews partnership newspapers that require institutional access

**Note:** The filter uses `dc.rights any "domaine public"` rather than `access any "fayes"` because the latter can return documents marked as "restricted use" (such as BnF-partenariats newspapers) that require special accreditation to download.

## Internal CQL Generation

The client automatically builds CQL queries from the parameters:
- Text query: `text all "query"` (processed by query parser)
- Multiple creators use OR logic: `(dc.creator all "A" or dc.creator all "B")`
- Multiple doc types use OR logic: `(dc.type adj "A" or dc.type adj "B")`
- Subject / publisher / library: `dc.subject all`, `dc.publisher all`, `dc.source all`
- OCR floor: `ocrquality >= "NN.NN"`, formatted to two decimals because the index compares as a string
- Every filter value passes through `escape_cql_literal`, since an unescaped `"` would close the literal early and get the query rejected
- Public domain filter: `dc.rights any "domaine public"` (applied by default)
- All filters are combined with AND logic
- SRU parameter `exactSearch` controls fuzzy matching behavior
- Ordering is appended last, from `SORT_CLAUSES` (see below)

## Result Ordering

`sort` accepts `relevance` (default), `date_asc` or `date_desc`, sharing the vocabulary of the sibling archive clients. Relevance is expressed by omitting `sortby` altogether — Gallica has no relevance sort key, it is simply what you get by not asking for anything else.

**Why relevance is the default.** The client previously appended `sortby dc.date/sort.ascending` unconditionally, which was close to unusable. Gallica's `text adj` ranks rather than filters, so a phrase search reports a long relevance tail: `"Robert-Houdin"` returns ~125,000 results whose first page is his own *Album des soirées fantastiques* and a programme from his theatre, and whose depths are unrelated. Forcing date order put a 1705 treatise on Paris rôtisseurs at position one and buried every genuinely relevant document thousands of results deep. Date order remains available because chronological reconstruction over a bounded range is a real use case; it is just the wrong default.

A consequence worth carrying into any interface built on this: `total_results` is a ranking depth, not a count of documents containing the term, and must never be presented as one.

## Rate Limiting

Requests are spaced by a cross-process rate limiter (`ratelimit.py`), default **3s**, overridable with `GALLICA_MIN_REQUEST_INTERVAL`, on top of an in-process semaphore limiting concurrency.

BnF publishes no rate limit for the SRU or ContentSearch endpoints - only a policy of open access "except in case of abusive usage" ([api.bnf.fr](https://api.bnf.fr/fr/api-gallica-de-recherche)). The one published figure covers the IIIF image API, which this client does not use. The 3s default follows established Gallica clients such as [bnfimage](https://rekyt.github.io/bnfimage/) and [bnf_downloader](https://github.com/yoshimitsuhiro/bnf_downloader), which treat one request per three seconds as the threshold above which BnF reads traffic as malicious. That figure is community practice rather than official documentation, but the downside is asymmetric: exceeding it costs hours of blocked access, while pacing conservatively costs seconds.

**Why cross-process rather than an instance attribute.** An instance attribute was adequate while the only caller was a long-lived MCP server. It is not adequate now: every CLI invocation is a separate process with its own instance, and callers are expected to fan work out across several at once, so an instance attribute paces nothing. The limiter keeps its timestamp in `.rate-limit` inside the cache directory, guarded by an exclusive `flock`, which every process sharing that cache observes.

### The OCR endpoint has a second, tighter budget

`RequestDigitalElement` is metered as a **token bucket**, not a rate, so `CrossProcessTokenBucket` (state in `.ocr-budget`) sits on top of the interval limiter for OCR requests only. Defaults: burst **4**, refill **one per 25s**, overridable with `GALLICA_OCR_BURST` and `GALLICA_OCR_REFILL_SECONDS`.

Those numbers are measured (2026-07-29, single residential IP), and the measurement is the argument for the shape:

| Pacing | Successes before HTTP 429 |
| --- | --- |
| 3s | 5 |
| 5s | 4 |

Slower pacing did not buy more requests, which is what rules out a simple interval — the server is counting requests in a window, not spacing between them. Roughly 120s of quiet restored the full allowance. Capacity is set to 4 rather than 5 so the client stops one short of the observed cliff.

BnF publishes none of this, so it is an observation with a date on it rather than a contract. **The README's "Re-deriving these" section carries the procedure for redoing the measurement** if the ceiling ever moves; keep the two tables in step if it does.

Two further behaviours the client depends on:

- **A 429 drains the bucket** (`CrossProcessTokenBucket.drain`). The refusal proves the real budget was lower than the bucket believed, so leaving tokens in it would let the next call - very possibly another process - spend one the server will not honour.
- **Sustained overdraw stops producing 429s and starts stalling.** After repeated refusals the endpoint simply does not answer and the connection times out. `_retrieve_alto_page` catches `httpx.TimeoutException` separately and reports it as a block rather than a network blip, because retrying it is exactly wrong.

## Caching

- **Cache:** OCR text, **per page** under `pages/<doc_id>/pNNNNN.txt`, plus the assembled file the caller is handed
- **Don't cache:** Search results (small, dynamic)
- **Location:** `$XDG_CACHE_HOME/gallica-mcp/`, resolved by `paths.cache_dir()`; override with `--cache-dir` or `GALLICA_CACHE_DIR`

The cache must not depend on the working directory: the CLI is installed globally and run from whatever project the researcher is in, so a CWD-relative cache would scatter downloads and destroy the hit rate.

**Per page, not per document, and that is load-bearing.** A download long enough to exhaust the OCR budget *will* be cut off part way through. Caching each page as it arrives means re-running the same command resumes rather than restarts - which matters when every wasted request is drawn from a budget of four. Caching only the finished document would throw away the whole burst on each attempt and guarantee the download could never complete.

The assembled file is named for the range: `<doc_id>.txt` for a whole document, `<doc_id>.p30-35.txt` for a slice. It carries `--- page N ---` markers, because the point of the snippet workflow is to arrive at a citable page reference and flattening that away would discard it.

## Document Types

- `monographie` - Books
- `périodique` - Periodicals (collections)
- `fascicule` - Individual periodical issues
- `manuscrit` - Manuscripts
- `image` - Images
- `carte` - Maps and plans
- `partition` - Musical scores

## Periodical Handling

**Important:** With `collapsing=false`, the server returns individual periodical issues as separate results rather than grouping them by collection.

**Example:** Searching for "Hanussen" returns:
- Without `collapsing=false`: 167 results (one per periodical collection)
- With `collapsing=false`: 465 results (each periodical issue counted separately)

For a periodical like "Istanbul" that has 6 issues mentioning "Hanussen", all 6 issues are returned as individual results with:
- Unique `dc:identifier` for each issue (e.g., `ark:/12148/bd6t552367k`)
- Specific publication dates (e.g., `1921-05-02`, `1921-05-05`, etc.)
- `dc:type` set to `fascicule` instead of `périodique`
- Each issue can be downloaded and searched independently

This ensures users see **all matching content**, not just one arbitrary issue per periodical.

## Notes

- Maximum 50 results per page (API limit)
- OCR text files can be very large (100KB-1MB+)
- Documents use ARK (Archival Resource Key) identifiers
- All text is UTF-8 encoded
- Search results include all individual periodical issues (not collapsed)
- Use `get_snippets` to fetch text excerpts for specific documents after searching

## Gotchas

- **User-Agent is mandatory.** Gallica answers httpx's default `python-httpx/...` agent with `403 Forbidden`. `client.py` sets an explicit `USER_AGENT`; do not remove it.
- **ContentSearch payloads are escaped twice.** Markup arrives as `&lt;span&gt;` and accents as `&amp;#233;`, so `_clean_snippet()` unescapes, converts the highlight span to `{braces}`, strips remaining markup, then unescapes again.
- **Date filtering uses `gallicapublication_date`, not `dc.date`.** `dc.date` is a string index: a relational comparison against it either errors or silently matches nothing, so every date-filtered search quietly returned zero results. The working index wants full `YYYY/MM/DD` bounds.
- **A rejected query returns HTTP 200 with an SRU diagnostic**, not an error status. Left unchecked that reads as "0 results", making a malformed filter indistinguishable from a search that genuinely found nothing. `_raise_for_diagnostics` surfaces it.
- **An anti-bot challenge also returns HTTP 200.** When Gallica decides it is being crawled it serves an ALTCHA "Vérification de sécurité" page, byte-identical whatever document was requested, served with HTTP 200 rather than 429. It was being stripped of markup and cached as the document's text, so every later read returned the challenge instead - silently and permanently. `_is_challenge_page` detects it and `download_text` refuses to cache it. The challenge is valid 24 hours, so a client that hits it should stop rather than retry.
- **`dc.type périodique` matches nothing** while `collapsing=false` is set, since issues are returned individually as `fascicule`.
- **`dc.subject` silently excludes all periodical issues.** Subject headings hang off the parent catalogue record, so `dc.subject all "X" and dc.type adj "fascicule"` is always zero — verified live. A subject filter combined with a press sweep returns nothing and looks exactly like a term nobody used.
- **There is no place-of-publication index.** `dc.coverage` does not exist (the server answers "There are no translation for the following key"), and `dc.publisher` conflates publisher and place — its values look like `E. Voisin (Paris)`, and `dc.publisher all "Paris"` returns 3.8M records. A `--place` flag would therefore be a lie; do not add one.
- **`dewey` only resolves at single-digit granularity, and `sdewey` does not resolve at all.** `dewey any "7"` narrows (193,864 → 4,653 on a text query); `dewey any "79"` and `dewey any "793"` both return zero, despite BnF documenting detailed codes. Ten buckets is too coarse to expose, so it is not wired up.
- **`provenance` works but does not discriminate here.** It is a genuine strict filter (`provenance adj "erara.ch"` alone returns 144,196), but the text index's ranked tail is entirely `bnf.fr`: adding `provenance adj "bnf.fr"` to a text query changes the total by nothing, and `erara.ch` takes it to zero. Not worth a flag.
- **`dc.format` is a grab-bag** — physical description, MIME type and view count share the field (`1 vol. (66 p.) : fig. ; in-16`, `image/jpeg`, `Nombre total de vues : 76`). Media type is what `dc.type` is for, so no `--format` flag.
- **SRU `explain` answers HTTP 500** (a Tomcat "Could not resolve view with name 'error'"), so the index list cannot be discovered from the service. The documented list lives at [api.bnf.fr](https://api.bnf.fr/fr/api-gallica-de-recherche) and does not entirely match reality — verify any new index live before exposing it.
- **A strict metadata filter converts the ranked tail into a real count.** `dc.subject all "Prestidigitation"` reports 39, not six figures, and intersects properly with a text clause (10 with `text adj "gobelet"`). This is the only reliable way to make `total_results` mean something on this source.
- **`texteBrut` is gated unconditionally; do not "fix" the download path by going back to it.** It is the obvious one-request-per-document endpoint and it is a dead end — see **Text Retrieval** above for what was tested. The per-page ALTO path is slower by design, not by oversight.
- **ALTO lies about its encoding.** The XML prolog says `ISO-8859-1`; the bytes are UTF-8. Trusting the declaration renders every accented French word as mojibake (`SCÃNE` for `SCÈNE`), which is quietly corrupting rather than loudly broken — it would survive into quoted material in a report. `alto.py` strips the prolog and decodes as UTF-8.
- **Hyphenated words are stored twice in ALTO.** A word broken across a line break appears as two `String` elements carrying `SUBS_TYPE="HypPart1"`/`"HypPart2"`, each with the whole word in `SUBS_CONTENT`. Emitting `CONTENT` naively yields `con- noitre`, which no search over the downloaded text will match. `_line_to_text` emits `SUBS_CONTENT` on the first half and drops the second.
- **ALTO block structure has to be preserved.** A newspaper page is columns of unrelated articles; flattening `TextBlock`s into one paragraph glues the end of one story to the start of another and manufactures false adjacency — the kind of error that produces a confident misquotation.
- **The OCR services want the bare id, not the ARK.** `RequestDigitalElement` and `Pagination` take `bpt6k5619759j`, while the SRU reports `ark:/12148/bpt6k5619759j`.
- **An empty page is normal.** Illustration plates and blank leaves return valid ALTO with no `String` content. `download_text` reports which pages were empty and only raises if *every* requested page was, since that is the image-only case.
- **Hyphenated terms are indexed as separate tokens.** ContentSearch highlights `{Robert}-{Houdin}` as two spans, so hyphenated names match loosely and inflate totals.
- **A malformed search record raises.** `_parse_record` used to swallow every exception and return None, which dropped the record from the results while the reported total still counted it - a search that silently under-reported. For a tool whose value rests on exhaustivity, a loud failure beats a quiet omission.
- **An empty result set is one empty page**, `total_pages: 1`. The API implies zero; the client normalises it so callers behave the same here as for any other source.
