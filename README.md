# Gallica MCP Server

MCP server for [Gallica](https://gallica.bnf.fr/), the digital library of the Bibliothèque nationale de France (BnF).
Search and access OCR text from millions of digitized documents:

- **search_gallica**: Text search with boolean operators (AND, OR, NOT), exact phrase matching with quotes, and parentheses for grouping. Returns paginated results (50 docs/page) with metadata.
- **get_snippets**: Retrieves text excerpts showing where search terms appear within a specific document. Includes page numbers for each snippet.
- **advanced_search_gallica**: Search with filters for creators (authors), document types, date ranges, language, and title. All filter parameters are optional.
- **download_text**: Downloads complete OCR text from any document using its ARK identifier. Caches results locally for fast repeated access.

The search functions convert your inputs into CQL (Contextual Query Language) queries that are sent to Gallica's SRU API.

There are two ways to use it: an **MCP server** for clients that speak MCP, and a
**`gallica` CLI** for agents driven through a shell. Both share one client, one cache and
one set of behaviours. The CLI is what the bundled `gallica-search` skill uses, and it
exposes every filter unconditionally rather than hiding them behind an install flag.

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
gallica search '"Harry Houdini"'                               # first page of results
gallica search '"prestidigitation" OR "magic"' --pages all     # sweep everything
gallica search 'Houdini' --type monographie --from-year 1900 --to-year 1930
gallica snippets 'ark:/12148/bpt6k55589910' '"Houdini"'        # where it appears
gallica get 'ark:/12148/bpt6k55589910'                         # cached OCR text path
```

Search returns documents without snippets, so the workflow is search → `snippets` to judge
a document cheaply → `get` only what is worth reading. Boolean operators must be
UPPERCASE. Add `--json` for machine-readable output.

Downloads are cached in `$XDG_CACHE_HOME/gallica-mcp` (override with
`--cache-dir` or `GALLICA_CACHE_DIR`). The cache location does not depend on the working
directory, so the CLI can be run from anywhere.

### MCP server

Run the server directly:

```bash
uv run gallica-mcp
```

Test with MCP Inspector:

```bash
uv run fastmcp dev src/gallica_mcp/server.py
```
