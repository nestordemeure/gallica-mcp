# Gallica MCP Server

MCP server for [Gallica](https://gallica.bnf.fr/), the digital library of the Bibliothèque nationale de France (BnF).
Search and access OCR text from millions of digitized documents:

- **search_gallica**: Text search with boolean operators (AND, OR, NOT), exact phrase matching with quotes, and parentheses for grouping. Returns paginated results (50 docs/page) with metadata.
- **get_snippets**: Retrieves text excerpts showing where search terms appear within a specific document. Includes page numbers for each snippet.
- **advanced_search_gallica**: Search with filters for creators (authors), document types, date ranges, language, and title. All filter parameters are optional.
- **download_text**: Downloads complete OCR text from any document using its ARK identifier. Caches results locally for fast repeated access.

The search functions convert your inputs into CQL (Contextual Query Language) queries that are sent to Gallica's SRU API.

## Installation

### Install the code

```bash
uv sync
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

Run the server directly:

```bash
uv run gallica-mcp
```

Test with MCP Inspector:

```bash
uv run fastmcp dev src/gallica_mcp/server.py
```
