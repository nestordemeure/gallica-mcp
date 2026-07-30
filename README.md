# Gallica MCP Server

MCP server for [Gallica](https://gallica.bnf.fr/), the digital library of the Bibliothèque nationale de France (BnF). Search and access OCR text from millions of digitized documents:

- **search_gallica**: Text search with boolean operators (AND, OR, NOT), exact phrase matching with quotes, and parentheses for grouping. Returns paginated results (50 docs/page) with metadata.
- **get_snippets**: Retrieves text excerpts showing where search terms appear within a specific document. Includes page numbers for each snippet.
- **advanced_search_gallica**: Search with filters for creators (authors), document types, date ranges, language, and title. All filter parameters are optional.
- **download_text**: Downloads OCR text for a range of a document's pages, given its ARK identifier. Caches each page locally for fast repeated access.

The search functions convert your inputs into CQL (Contextual Query Language) queries that are sent to Gallica's SRU API.

There are two ways to use it: an **MCP server** for clients that speak MCP, and a **`gallica` CLI** for agents driven through a shell. Both share one client, one cache and one set of behaviours. The CLI is what the bundled `gallica-search` skill uses, and it exposes every filter unconditionally rather than hiding them behind an install flag.

## Installation

### Install the code

```bash
uv sync
```

### Install the CLI

```bash
uv tool install .        # puts `gallica` on your PATH
```

### Install to MCP CLIs

Installs to Claude Code, Codex CLI, and Gemini CLI:

```bash
# Basic installation (search_gallica + download_text tools only)
uv run gallica-mcp-install

# With advanced search enabled (adds advanced_search_gallica tool)
uv run gallica-mcp-install --enable-advanced-search
```

Verify the installation:

```bash
claude mcp list   # For Claude Code
codex mcp list    # For Codex CLI
gemini mcp list   # For Gemini CLI
```

## Usage

### CLI

```bash
gallica search '"Tour Eiffel"'                                 # first page, best matches first
gallica search '"Tour Eiffel"' --type monographie --from-year 1889 --to-year 1900
gallica search 'Exposition universelle' --from-year 1889 --to-year 1890 --sort date_asc --pages all
gallica snippets 'ark:/12148/bpt6k1910270z' '"Tour Eiffel"'    # where it appears, with PAG_ page ids
gallica get 'ark:/12148/bpt6k1910270z' --pages 2-3             # cached OCR text path
```

Search returns documents without snippets, so the workflow is search → `snippets` to judge a document cheaply → `get` only the pages worth reading. Boolean operators must be UPPERCASE. Add `--json` for machine-readable output.

`snippets` reports page identifiers like `PAG_30`, and `get --pages` accepts that form verbatim, so a page reference carries from one command to the next without translation.

**Results are ordered by relevance, and that matters more than it sounds.** Gallica's text index ranks rather than filters: a phrase search reports a long tail of loosely related documents, so `"Tour Eiffel"` claims ~620,000 results while only the first page or two are actually about it. Treat the total as a ranking depth, not a count of matches. `--sort date_asc`/`date_desc` are available for chronological work, but they are worth using only on a query narrowed by filters until its total is plausible — on a broad query they bury the good material.

Downloads are cached in `$XDG_CACHE_HOME/gallica-mcp` (override with `--cache-dir` or `GALLICA_CACHE_DIR`). The cache location does not depend on the working directory, so the CLI can be run from anywhere.

Requests are paced one every 3 seconds by default, matching what established Gallica clients use; BnF publishes no limit for these endpoints but blocks traffic it considers abusive, serving an ALTCHA challenge page instead of results. Override with `GALLICA_MIN_REQUEST_INTERVAL` if you know what you are doing.

**`get` is metered separately, and much more tightly.** Gallica serves OCR one page per request, and that endpoint allows only a short burst before answering HTTP 429 for minutes — measured at 5 requests, whether spaced 3s or 5s apart, with roughly two minutes to recover. The client therefore holds a token bucket for OCR alone: a burst of **4 pages** refilling at **one per 25 seconds**, tunable with `GALLICA_OCR_BURST` and `GALLICA_OCR_REFILL_SECONDS`.

So a handful of pages found via `snippets` costs seconds, an 8-page newspaper issue about two minutes, and a 200-page book over an hour. `get` declines documents longer than 20 pages unless you pass `--pages` (or `--pages all` to mean it). Pages are cached individually, so a download interrupted by the rate limit resumes rather than restarts.

Both budgets are shared across processes, so parallel invocations draw on one allowance rather than each getting its own.

### MCP server

Run the server directly:

```bash
uv run gallica-mcp
```

Test with MCP Inspector:

```bash
uv run fastmcp dev src/gallica_mcp/server.py
```
