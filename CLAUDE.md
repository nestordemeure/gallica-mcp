# Gallica MCP Server

MCP server for searching and retrieving documents from Gallica, the digital library of the Bibliothèque nationale de France (BnF).

## Stack

- Python ≥3.12, uv, fastMCP ≥2.0.0, httpx ≥0.27.0

## Functionality

- **Fulltext search** with CQL operators (AND, OR, NOT, exact phrases)
- **Text snippets** showing search terms in context (fetched concurrently via ContentSearch API)
- **OCR text download** with local caching
- **Pagination support** (up to 50 results per page)

## Structure

```
gallica-mcp/
├── cache/                   # Downloaded OCR text (gitignored)
│   └── gallica/
├── src/gallica_mcp/
│   ├── __init__.py
│   ├── client.py           # API client + caching
│   ├── server.py           # FastMCP tools
│   └── install.py          # CLI installer
├── pyproject.toml
└── CLAUDE.md               # This file
```

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
- Used automatically for each search result (requests go through the global rate limiter: default 1 req/sec, single concurrency)

**Text Retrieval:**
- Plain text: `https://gallica.bnf.fr/[ark].texteBrut`
- Document identifiers: ARK format (`ark:/12148/...`)

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

The `--enable-advanced-search` flag enables the `advanced_search_gallica` tool. Without it, only `search_gallica` and `download_text` are available.

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
```

## Search Interface

Two search functions are available (advanced search is optional):

**`search_gallica(query, page=1)`** - Text search with boolean operators (always available)
- Query supports CQL boolean operators: AND, OR, NOT
- Exact phrase matching with quotes: "Harry Houdini"
- Grouping with parentheses: (A OR B) AND C
- Searches across all OCR content
- Returns results with snippets

**`advanced_search_gallica(...)`** - Advanced search with filters (optional, enabled with `--enable-advanced-search`)
- All parameters are optional (except defaults)
- Same query syntax as search_gallica (with boolean support)
- Provides separate parameters for common filters:

### Query Syntax

**IMPORTANT:** Gallica uses **fuzzy matching by default**. Searching `"hanussen"` may return "haussen", "hansen", etc. Use double quotes for exact matches: `'"hanussen"'`. **Recommended:** Use quotes by default unless you want fuzzy search.

The `query` parameter supports:

1. **Simple text** - All words must appear (AND logic by default) with **FUZZY MATCHING**
   - `"Houdini"` → finds "Houdini", "Houdin", "Houdine", etc.
   - `"magic tricks"` → finds both "magic" AND "tricks" (any order, fuzzy for each)

2. **Exact phrases** - Use double quotes for **EXACT MATCHING** (no fuzzy)
   - `'"Harry Houdini"'` → exact phrase only
   - `'"hanussen"'` → exact word only (no "haussen")

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

## Internal CQL Generation

The client automatically builds CQL queries from the parameters:
- Text query without quotes: `text all "query"` (fuzzy matching, with expansion)
- Text query with quotes: `text adj "query"` (exact matching, no expansion)
- Multiple creators use OR logic: `(dc.creator all "A" or dc.creator all "B")`
- Multiple doc types use OR logic: `(dc.type adj "A" or dc.type adj "B")`
- All filters are combined with AND logic

## Caching

- **Cache:** OCR text downloads (large, static files)
- **Don't cache:** Search results (small, dynamic)
- **Location:** `cache/gallica/`

Downloaded text files are cached locally to avoid repeated API calls for the same document. The cache directory is gitignored.

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
