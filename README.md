# Gallica MCP Server

MCP server for [Gallica](https://gallica.bnf.fr/), the digital library of the Bibliothèque nationale de France (BnF). Search and access OCR text from millions of digitized documents:

- **search_gallica**: Text search with boolean operators (AND, OR, NOT), exact phrase matching with quotes, and parentheses for grouping. Returns paginated results (50 docs/page) with metadata.
- **get_snippets**: Retrieves text excerpts showing where search terms appear within a specific document. Includes page numbers for each snippet.
- **advanced_search_gallica**: Search with filters for creators (authors), document types, date ranges, language, and title. All filter parameters are optional.
- **download_text**: Downloads complete OCR text from any document using its ARK identifier. Caches results locally for fast repeated access.

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
gallica snippets 'ark:/12148/bpt6k1910270z' '"Tour Eiffel"'    # where it appears
gallica get 'ark:/12148/bpt6k1910270z'                         # cached OCR text path
```

Search returns documents without snippets, so the workflow is search → `snippets` to judge a document cheaply → `get` only what is worth reading. Boolean operators must be UPPERCASE. Add `--json` for machine-readable output.

**Results are ordered by relevance, and that matters more than it sounds.** Gallica's text index ranks rather than filters: a phrase search reports a long tail of loosely related documents, so `"Tour Eiffel"` claims ~620,000 results while only the first page or two are actually about it. Treat the total as a ranking depth, not a count of matches. `--sort date_asc`/`date_desc` are available for chronological work, but they are worth using only on a query narrowed by filters until its total is plausible — on a broad query they bury the good material.

Downloads are cached in `$XDG_CACHE_HOME/gallica-mcp` (override with `--cache-dir` or `GALLICA_CACHE_DIR`). The cache location does not depend on the working directory, so the CLI can be run from anywhere.

Requests are paced one every 3 seconds by default, matching what established Gallica clients use; BnF publishes no limit for these endpoints but blocks traffic it considers abusive, serving an ALTCHA challenge page instead of results. Override with `GALLICA_MIN_REQUEST_INTERVAL` if you know what you are doing.

**`get` is the expensive call.** The pacing treats all three endpoints alike, but BnF does not: `texteBrut` downloads are guarded harder than search, are the first thing to be refused, and are the last to start working again — search recovering does not mean downloads have. Budget in documents downloaded rather than requests issued, and use `snippets` to decide a document is worth reading before spending a download on it.

### MCP server

Run the server directly:

```bash
uv run gallica-mcp
```

Test with MCP Inspector:

```bash
uv run fastmcp dev src/gallica_mcp/server.py
```
