# Gallica MCP Server

An MCP server for a search of Gallica, the digital library of the Bibliothèque nationale de France (BnF), and for retrieval of its documents.

## Stack

- Python ≥3.12, uv, fastMCP ≥2.0.0, httpx ≥0.27.0

## Functions

- **A full-text search** with the CQL operators (AND, OR, NOT, exact phrases)
- **Control of exact matching against fuzzy matching** (exact matching is the default)
- **A filter on the access rights**, for public-domain documents with an OCR download
- **Text snippets** that show the search terms in context (through the optional `get_snippets` tool, which uses the ContentSearch API)
- **An OCR text download** by page range, with a local cache for each page
- **Pagination** up to 50 results for each page

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

`client.py` holds all the behaviour. `server.py` and `cli.py` are thin presentation layers over it, so the search semantics and the cache stay identical for each method of access. The CLI shows each filter without a condition. The MCP server hides them behind `--enable-advanced-search`.

## API Details

**Search API:**
- Protocol: SRU (Search/Retrieve via URL) version 1.2
- Base URL: `https://gallica.bnf.fr/SRU`
- Query language: CQL (Contextual Query Language)
- Response format: XML with Dublin Core metadata
- **Collapsing:** the client uses the `collapsing=false` parameter, so the server returns each periodical issue separately and does not group them by collection

**ContentSearch API:**
- Base URL: `https://gallica.bnf.fr/services/ContentSearch`
- Returns text snippets with the search terms highlighted
- The `get_snippets` tool uses it. The requests pass through the rate limiter: one request each 3s by default, with one request at a time.

**Text Retrieval (ALTO, one page at a time):**
- OCR: `https://gallica.bnf.fr/RequestDigitalElement?O=<id>&E=ALTO&Deb=<page>`
- Page count: `https://gallica.bnf.fr/services/Pagination?ark=<id>` — `nbVueImages` and `hasContent`
- Both take the **bare document id** (`bpt6k5619759j`), not the full ARK that the SRU reports. `_document_id` removes the prefix.
- Document identifiers elsewhere: the ARK format (`ark:/12148/...`)

**`.texteBrut` is not usable now, and this is why the client stopped its use.**
`https://gallica.bnf.fr/[ark].texteBrut` gave the full OCR of a document in one
request, which is why it was the first implementation. It now redirects to
`/services/engine/search/altcha` and serves the anti-bot challenge
*without a condition*. The tests confirmed this on a cold connection with no recent traffic, with
the User-Agent of the client and with a full browser User-Agent, while the SRU search
answered normally seconds before and after. This is not a rate limit, and we cannot
correct it from here. ALTO is the documented alternative
([api.bnf.fr](https://api.bnf.fr/fr/api-document-de-gallica)) and it operates, at
the cost of one request for each page.

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

The `--enable-advanced-search` flag enables the `advanced_search_gallica` tool. Without it, only `search_gallica`, `get_snippets` and `download_text` are available.

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

Three main tools are available. The advanced search is optional.

**`search_gallica(query, page=1, sort="relevance")`** - a text search with boolean operators (always available)
- The query supports the CQL boolean operators: AND, OR, NOT
- Exact phrase matching with quotation marks: "Harry Houdini"
- Grouping with parentheses: (A OR B) AND C
- Searches all of the OCR content
- Returns the document metadata (without snippets, for a faster search)

**`get_snippets(identifier, query)`** - fetches the text extracts for one document (always available)
- Takes a document identifier (ARK) and a search query
- Returns the text snippets that show where the search terms appear
- Includes a page number for each snippet (for example, "PAG_200" for page 200)
- Useful when you must find specific content inside a document after a search

**`advanced_search_gallica(...)`** - a search with filters (optional, enabled with `--enable-advanced-search`)
- Each parameter is optional, except the defaults
- The same query syntax as `search_gallica`, with boolean support
- Gives separate parameters for the common filters

### Query Syntax

**IMPORTANT:** by default a search uses **exact matching**, which gives precise results. Set the `exact_search` parameter of `advanced_search_gallica` to `False` to enable fuzzy matching, which can find OCR errors and variants.

The `query` parameter supports these forms:

1. **Simple text** - each word must appear (AND logic by default)
   - `"Houdini"` → finds "Houdini"
   - `"magic tricks"` → finds both "magic" AND "tricks" (in any order)

2. **Exact phrases** - use double quotation marks for a phrase match
   - `'"Harry Houdini"'` → the exact phrase only
   - `'"hanussen"'` → the exact word only

3. **AND operator** - an explicit AND (uppercase)
   - `"magic AND illusion"` → both must appear
   - `"Paris AND France"` → both must appear

4. **OR operator** - either term (uppercase)
   - `"Houdini OR Houdin"` → either name
   - `"escape OR évasion"` → either term

5. **NOT operator** - excludes terms (uppercase)
   - `"magic NOT card"` → "magic" yes, "card" no
   - `"Paris NOT Texas"` → "Paris" yes, "Texas" no

6. **Parentheses** - group the operations
   - `"(Houdini OR Houdin) AND escape"` → (either name) AND escape
   - `"magic AND (illusion OR trick)"` → magic AND (either illusion or trick)

7. **Complex combinations**
   - `'"Harry Houdini" AND (escape OR illusion) NOT death'`
   - `'("Robert-Houdin" OR Houdini) AND (magic OR prestidigitation)'`

**Important:** the operators (AND, OR, NOT) must be UPPERCASE.

**Parameters:**
- `query` (str) - the text to search in the OCR content (simple text, not CQL)
- `page` (int) - the page number for pagination (default: 1)
- `creators` (list[str]) - filter by author names (OR logic)
- `doc_types` (list[str]) - filter by document types (OR logic)
- `date_start` (int) - the earliest publication year (inclusive)
- `date_end` (int) - the latest publication year (inclusive)
- `language` (str) - a language code (ISO 639-2, 3 letters)
- `title` (str) - the text to search in the document titles
- `subject` (str) - a BnF catalogue subject heading, in French, subdivided with ` -- `
- `publisher` (str) - the publisher as printed on the item
- `library` (str) - the institution that holds the item, matched against `dc.source`
- `min_ocr_quality` (float) - the lowest acceptable OCR score, 0-100
- `public_domain_only` (bool) - limits the results to public-domain documents with an OCR download (default: True)
- `exact_search` (bool) - enables exact matching (default: True). Set it to False for fuzzy matching.

**Document Types:**
- `monographie` - books
- `périodique` - periodicals and journals
- `manuscrit` - manuscripts
- `image` - images
- `carte` - maps and plans
- `partition` - musical scores

**Language Codes (ISO 639-2):**
- `fre` - French
- `eng` - English
- `lat` - Latin
- `ger` - German
- `ita` - Italian
- `spa` - Spanish

## Search Behaviour

### Exact matching against fuzzy matching

**Default: exact matching** (`exact_search=True`)
- The search is precise, and it matches only the exact terms
- "Hanussen" finds only "Hanussen" (465 results)
- We recommend this for most uses

**Fuzzy matching** (`exact_search=False`)
- The search finds variants and OCR errors
- "Hanussen" finds "Hanussen", "Haussen", "Hansen" and more (6,450 results)
- Useful when you must find documents with OCR errors
- Can give many irrelevant results

**Note:** quotation marks in the query (for example `'"exact phrase"'`) always force an exact phrase match, whatever the `exact_search` setting.

### The public-domain filter

**By default**, a search returns only **public-domain documents** with an OCR text that a person can download freely (`public_domain_only=True`).

To include **all documents**, whatever their access restrictions:

```python
# Include documents with usage restrictions
advanced_search_gallica(query="prestidigitation", public_domain_only=False)
```

**Default behaviour:**
- The server returns only public-domain documents, through the filter `dc.rights any "domaine public"`
- Each document has an OCR text that a person can download
- Thus each user can read the full text of the search results
- This **excludes restricted documents**, such as the RetroNews partnership newspapers, which need institutional access

**Note:** the filter uses `dc.rights any "domaine public"` and not `access any "fayes"`, because the second form can return documents marked as "restricted use" (such as the BnF-partenariats newspapers) that need a special accreditation before a person can download them.

## Internal CQL Generation

The client builds the CQL queries from the parameters:
- Text query: `text all "query"` (the query parser processes it)
- Several creators use OR logic: `(dc.creator all "A" or dc.creator all "B")`
- Several doc types use OR logic: `(dc.type adj "A" or dc.type adj "B")`
- Subject, publisher and library: `dc.subject all`, `dc.publisher all`, `dc.source all`
- OCR floor: `ocrquality >= "NN.NN"`, formatted to two decimals because the index compares it as a string
- Each filter value passes through `escape_cql_literal`, because an unescaped `"` would close the literal early and the server would reject the query
- Public-domain filter: `dc.rights any "domaine public"` (applied by default)
- The client combines each filter with AND logic
- The SRU parameter `exactSearch` controls the fuzzy-matching behaviour
- The client appends the ordering last, from `SORT_CLAUSES` (see below)

## Result Ordering

`sort` takes `relevance` (default), `date_asc` or `date_desc`. This is the vocabulary of the client of each other archive. The client expresses relevance when it omits `sortby` completely. Gallica has no relevance sort key: relevance is what you receive when you ask for nothing else.

**Why relevance is the default.** An earlier version of the client appended `sortby dc.date/sort.ascending` without a condition, which was almost unusable. The `text adj` operator of Gallica ranks the documents. It does not filter them. Thus a phrase search reports a long relevance tail: `"Robert-Houdin"` gives approximately 125,000 results, whose first page is his own *Album des soirées fantastiques* and a programme from his theatre, and whose low positions are unrelated. A forced date order put a 1705 treatise on the rôtisseurs of Paris at position one, and it put each relevant document thousands of results lower. The date order stays available, because a chronological reconstruction over a limited range is a real use. It is only the incorrect default.

One consequence is important for each interface built on this client: `total_results` is a rank depth, not a count of the documents that contain the term, and you must never present it as one.

## Rate Limiting

A cross-process rate limiter (`ratelimit.py`) paces the requests. The default is **3s**, and `GALLICA_MIN_REQUEST_INTERVAL` changes it. An in-process semaphore also limits the concurrency.

The BnF publishes no rate limit for the SRU endpoints or the ContentSearch endpoints. It publishes only a policy of open access "except in case of abusive usage" ([api.bnf.fr](https://api.bnf.fr/fr/api-gallica-de-recherche)). The one published figure covers the IIIF image API, which this client does not use. The 3s default follows the established Gallica clients, such as [bnfimage](https://rekyt.github.io/bnfimage/) and [bnf_downloader](https://github.com/yoshimitsuhiro/bnf_downloader), which use one request each three seconds as the rate above which the BnF reads the traffic as an attack. That figure is community practice and not official documentation, but the risk is asymmetric: to go above it costs hours of blocked access, and to pace the requests carefully costs seconds.

**Why the limiter operates across processes, and not as an instance attribute.** An instance attribute was sufficient while the only caller was a long-lived MCP server. It is not sufficient now: each call of the CLI is a separate process with its own instance, and we expect the caller to run several at the same time. Thus an instance attribute paces nothing. The limiter keeps its timestamp in `.rate-limit` inside the cache directory, with an exclusive `flock` to guard it, and each process that shares that cache obeys it.

### The OCR endpoint has a second and tighter budget

The server meters `RequestDigitalElement` as a **token bucket**, not as a rate. Thus `CrossProcessTokenBucket` (state in `.ocr-budget`) sits on top of the interval limiter, for the OCR requests only. Defaults: a burst of **4**, and a refill of **one each 25s**. `GALLICA_OCR_BURST` and `GALLICA_OCR_REFILL_SECONDS` change them.

These numbers come from measurements (2026-07-29, one residential IP address), and the measurement is the argument for the shape:

| Pacing | Successes before HTTP 429 |
| --- | --- |
| 3s | 5 |
| 5s | 4 |

A slower pace did not buy more requests, which is what excludes a simple interval: the server counts the requests in a window. It does not measure the space between them. Approximately 120s with no requests restored the full allowance. The capacity is 4 and not 5, so the client stops one request before the observed limit.

The BnF publishes none of this, so it is an observation with a date on it and not a contract. **The "Re-deriving these" section of the README carries the procedure for a new measurement** if the limit ever moves. Keep the two tables in agreement if it does.

The client depends on two more behaviours:

- **An HTTP 429 empties the bucket** (`CrossProcessTokenBucket.drain`). The refusal proves that the real budget was lower than the value in the bucket. Thus to leave tokens in it would let the next call — very possibly another process — spend one that the server will not honour.
- **Sustained overdraw stops the HTTP 429 responses and starts a stall.** After repeated refusals the endpoint simply does not answer, and the connection times out. `_retrieve_alto_page` catches `httpx.TimeoutException` separately and reports it as a block and not as a temporary network fault, because a second attempt is exactly the wrong action.

## Caching

- **Cache:** the OCR text, **for each page**, under `pages/<doc_id>/pNNNNN.txt`, plus the assembled file that the caller receives
- **Do not cache:** the search results (small, dynamic)
- **Location:** `$XDG_CACHE_HOME/gallica-mcp/`, resolved by `paths.cache_dir()`; change it with `--cache-dir` or `GALLICA_CACHE_DIR`

The cache must not depend on the working directory. The CLI has a global installation and runs from whichever project the researcher is in, so a cache relative to the working directory would put the downloads in many places and would destroy the hit rate.

**The cache holds each page, not each document, and this is necessary.** A download long enough to empty the OCR budget *will* stop part of the way through. When the client caches each page as it arrives, a second run of the same command continues instead of a restart. That is important when each wasted request comes from a budget of four. A cache of the finished document only would discard the full burst on each attempt, and would make the download impossible to complete.

The client names the assembled file for the range: `<doc_id>.txt` for a full document, and `<doc_id>.p30-35.txt` for a part. It carries `--- page N ---` markers, because the purpose of the snippet procedure is to arrive at a page reference that a person can cite, and to remove that would discard it.

## Document Types

- `monographie` - books
- `périodique` - periodicals (collections)
- `fascicule` - individual periodical issues
- `manuscrit` - manuscripts
- `image` - images
- `carte` - maps and plans
- `partition` - musical scores

## Periodical Handling

**Important:** with `collapsing=false`, the server returns each periodical issue as a separate result. It does not group them by collection.

**Example:** a search for "Hanussen" gives these results:
- Without `collapsing=false`: 167 results (one for each periodical collection)
- With `collapsing=false`: 465 results (each periodical issue counted separately)

For a periodical such as "Istanbul", which has 6 issues that mention "Hanussen", the server returns all 6 issues as individual results with these properties:
- A unique `dc:identifier` for each issue (for example, `ark:/12148/bd6t552367k`)
- A specific publication date (for example, `1921-05-02`, `1921-05-05`)
- `dc:type` set to `fascicule` and not to `périodique`
- Each issue can be downloaded and searched independently

Thus each user sees **all of the content that matches**, and not one arbitrary issue for each periodical.

## Notes

- A maximum of 50 results for each page (an API limit)
- The OCR text files can be very large (100KB-1MB or more)
- The documents use ARK (Archival Resource Key) identifiers
- All of the text is UTF-8
- The search results include each individual periodical issue (not collapsed)
- Use `get_snippets` to fetch the text extracts for a specific document after a search

## Known behaviours and risks

- **The User-Agent is mandatory.** Gallica answers the default `python-httpx/...` agent of httpx with `403 Forbidden`. `client.py` sets an explicit `USER_AGENT`. Do not remove it.
- **The ContentSearch payloads are escaped two times.** The markup arrives as `&lt;span&gt;` and the accents as `&amp;#233;`. Thus `_clean_snippet()` unescapes the text, converts the highlight span to `{braces}`, removes the remaining markup, and then unescapes the text again.
- **The date filter uses `gallicapublication_date`, not `dc.date`.** `dc.date` is a string index: a relational comparison against it either gives an error or quietly matches nothing, so each date-filtered search quietly gave zero results. The index that operates needs full `YYYY/MM/DD` bounds.
- **A rejected query gives HTTP 200 with an SRU diagnostic**, not an error status. Without a check this reads as "0 results", which makes a filter with an incorrect form identical to a search that genuinely found nothing. `_raise_for_diagnostics` surfaces it.
- **An anti-bot challenge also gives HTTP 200.** When Gallica decides that a client is crawling it, it serves an ALTCHA "Vérification de sécurité" page. The page is identical byte for byte whatever document the client requested, and the server sends it with HTTP 200 and not with HTTP 429. An earlier version removed its markup and cached it as the text of the document, so each later read gave the challenge instead — quietly and permanently. `_is_challenge_page` detects it, and `download_text` refuses to cache it. The challenge is valid 24 hours, so a client that meets it must stop and must not try again.
- **`dc.type périodique` matches nothing** while `collapsing=false` is set, because the server returns the issues individually as `fascicule`.
- **`dc.subject` quietly excludes each periodical issue.** The subject headings belong to the parent catalogue record, so `dc.subject all "X" and dc.type adj "fascicule"` is always zero — confirmed live. A subject filter with a search of the press gives nothing, and it looks exactly like a term that no person used.
- **There is no index of the place of publication.** `dc.coverage` does not exist (the server answers "There are no translation for the following key"), and `dc.publisher` mixes the publisher and the place: its values look like `E. Voisin (Paris)`, and `dc.publisher all "Paris"` gives 3.8M records. Thus a `--place` flag would be a lie. Do not add one.
- **`dewey` resolves only at one-digit granularity, and `sdewey` does not resolve at all.** `dewey any "7"` narrows a text query (193,864 → 4,653). `dewey any "79"` and `dewey any "793"` both give zero, although the BnF documents the detailed codes. Ten buckets is too coarse to show, so the client does not use it.
- **`provenance` operates, but it does not discriminate here.** It is a genuine strict filter (`provenance adj "erara.ch"` alone gives 144,196), but the ranked tail of the text index is entirely `bnf.fr`: to add `provenance adj "bnf.fr"` to a text query changes the total by nothing, and `erara.ch` takes it to zero. It is not worth a flag.
- **`dc.format` mixes several things** — the physical description, the MIME type and the view count share the field (`1 vol. (66 p.) : fig. ; in-16`, `image/jpeg`, `Nombre total de vues : 76`). `dc.type` is the field for the media type, so there is no `--format` flag.
- **SRU `explain` answers HTTP 500** (a Tomcat "Could not resolve view with name 'error'"), so the client cannot discover the index list from the service. The documented list is at [api.bnf.fr](https://api.bnf.fr/fr/api-gallica-de-recherche), and it does not fully agree with reality. Confirm any new index live before you show it.
- **A strict metadata filter converts the ranked tail into a real count.** `dc.subject all "Prestidigitation"` reports 39, not a six-figure number, and it intersects correctly with a text clause (10 with `text adj "gobelet"`). This is the only reliable method to give `total_results` a meaning on this source.
- **`texteBrut` has a gate with no condition. Do not "correct" the download path when you go back to it.** It is the obvious endpoint with one request for each document, and it is a dead end. See **Text Retrieval** above for the tests. The per-page ALTO path is slower by design, not by oversight.
- **ALTO reports its encoding incorrectly.** The XML prolog says `ISO-8859-1`, and the bytes are UTF-8. To trust the declaration renders each accented French word as mojibake (`SCÃNE` for `SCÈNE`), which corrupts the text quietly and does not fail loudly. It would survive into quoted material in a report. `alto.py` removes the prolog and decodes the bytes as UTF-8.
- **ALTO stores a hyphenated word two times.** A word divided across a line break appears as two `String` elements that carry `SUBS_TYPE="HypPart1"` and `"HypPart2"`, and each one holds the full word in `SUBS_CONTENT`. To emit `CONTENT` naively gives `con- noitre`, which no search over the downloaded text will match. `_line_to_text` emits `SUBS_CONTENT` on the first half, and it drops the second half.
- **The client must keep the ALTO block structure.** A newspaper page is columns of unrelated articles. To flatten the `TextBlock` elements into one paragraph joins the end of one story to the start of another, and it manufactures a false adjacency. That is the error that produces a confident misquotation.
- **The OCR services need the bare id, not the ARK.** `RequestDigitalElement` and `Pagination` take `bpt6k5619759j`, and the SRU reports `ark:/12148/bpt6k5619759j`.
- **An empty page is normal.** An illustration plate and a blank leaf both give valid ALTO with no `String` content. `download_text` reports which pages were empty, and it raises an error only if *each* requested page was empty, because that is the image-only case.
- **The index holds a hyphenated term as separate tokens.** ContentSearch highlights `{Robert}-{Houdin}` as two spans, so a hyphenated name matches loosely and makes the totals larger.
- **A search record with an incorrect form raises an error.** An earlier `_parse_record` absorbed each exception and returned None, which dropped the record from the results while the reported total still counted it. That is a search that quietly under-reported. For a tool whose value is completeness, a loud failure is better than a quiet omission.
- **An empty result set is one empty page**, `total_pages: 1`. The API implies zero. The client normalises it, so each caller behaves the same here as for every other source.
