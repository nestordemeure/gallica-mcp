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

### Rate limits

**None of these numbers are published by BnF.** Its stated policy for the Gallica APIs is open access "except in case of abusive usage" ([api.bnf.fr](https://api.bnf.fr/fr/api-gallica-de-recherche)); the one published figure covers the IIIF image API, which this client does not use. Everything below is either community practice or measured against the live service, so treat it as an observation with a date on it rather than a contract — and see *Re-deriving these* if the client starts getting refused where it used to work.

There are two separate budgets, and both are shared across processes via lock files in the cache directory, so parallel invocations draw on one allowance rather than each getting its own.

**Search and snippets** are paced at one request every **3 seconds**, following established Gallica clients such as [bnfimage](https://rekyt.github.io/bnfimage/) and [bnf_downloader](https://github.com/yoshimitsuhiro/bnf_downloader), which treat that as the point above which BnF starts reading traffic as malicious. Community practice, not measurement. Override with `GALLICA_MIN_REQUEST_INTERVAL`.

**OCR download is metered separately and much more tightly**, because Gallica serves it one page per request from `RequestDigitalElement`. Measured 2026-07-29 from a single residential IP:

| Pacing between requests | Successes before HTTP 429 |
| --- | --- |
| 3s | 5 |
| 5s | 4 |

Roughly 120 seconds of quiet restored the allowance. **Slower pacing bought fewer requests, not more** — which is the interesting part: it rules out a rate limit, because the server is counting requests in a window rather than measuring the gap between them. So the client models it as a token bucket: a burst of **4 pages** refilling at **one per 25 seconds**, set one step under the observed cliff. Override with `GALLICA_OCR_BURST` and `GALLICA_OCR_REFILL_SECONDS`.

The 120s recovery figure is from probing rather than from the server; the client does not read a `Retry-After` header, and whether one is sent was not checked.

One further behaviour, same session: **sustained overdraw stops producing 429s and starts stalling.** After repeated refusals the endpoint simply stops answering and the connection times out. The client reports a timeout there as a block rather than a network fault, because retrying it is exactly wrong.

In practice: a handful of pages found via `snippets` costs seconds, an 8-page newspaper issue about two minutes, and a 200-page book over an hour. `get` declines documents longer than 20 pages unless you pass `--pages` (or `--pages all` to mean it). Pages are cached individually, so a download interrupted by the rate limit resumes rather than restarts.

#### Re-deriving these

If downloads start failing at counts these defaults should allow, the ceiling has moved and the measurement is worth redoing. It costs about ten minutes:

1. Leave Gallica alone for several minutes, so the bucket is full and you are measuring the limit rather than your own recent traffic.
2. Request consecutive ALTO pages of one public-domain document at a fixed spacing, recording the status of each: `https://gallica.bnf.fr/RequestDigitalElement?O=<id>&E=ALTO&Deb=<n>`. Stop at the first 429 — that count is the burst.
3. Repeat at a different spacing. If the count does not rise with the gap, it is still a bucket and only the capacity changed.
4. Wait, and probe single requests to find how long recovery takes. Divide by the burst for the refill rate.

Set `GALLICA_OCR_BURST` one below the smallest observed failure point, and update the table above with the new date. Do not run this while doing real research — it deliberately ends in a block, and a stalled endpoint takes a good while to come back.

### MCP server

Run the server directly:

```bash
uv run gallica-mcp
```

Test with MCP Inspector:

```bash
uv run fastmcp dev src/gallica_mcp/server.py
```
