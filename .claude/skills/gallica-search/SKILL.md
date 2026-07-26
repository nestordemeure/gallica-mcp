---
name: gallica-search
description: Search Gallica, the Bibliothèque nationale de France digital library, with the `gallica` CLI. Use for French-language newspapers, periodicals and books — and for the French and European press coverage of touring performers.
---

# Gallica

The BnF's digital library: French newspapers, periodicals, books and manuscripts, plus a
run of English-language titles such as the Paris edition of the *New York Herald*. The
place to look for European press coverage of performers who toured the Continent.

> Gallica support is newer than the other sources. Sanity-check its results rather than
> assuming they are complete.

## Commands

```sh
gallica search "<query>" [--pages N|N-M|all] [filters] [--json]
gallica snippets <ark> "<query>"   # where the query appears inside one document
gallica get <ark>                  # download OCR text, prints path to the cached file
```

Filters for `search`: `--creator NAME` (repeatable), `--type TYPE` (repeatable, from
`monographie`, `périodique`, `fascicule`, `manuscrit`, `image`, `carte`, `partition`),
`--from-year`, `--to-year`, `--language CODE` (ISO 639-2: `fre`, `eng`, `ger`…),
`--title TEXT`, `--include-restricted`, `--fuzzy`.

**Search returns no snippets.** This is the important workflow difference: `search` gives
you documents, then `snippets` tells you whether a given document is actually worth
anything, and only then does `get` download it. Going straight from search to `get` wastes
a large download on documents that hold a single passing mention.

`snippets` marks matched terms in `{braces}` and reports a page identifier such as
`PAG_30` for each occurrence.

## Query syntax

- Boolean operators **must be uppercase**: `AND`, `OR`, `NOT`
- `"quoted phrases"` match exactly, and always force exact matching
- Parentheses group: `(Houdini OR Houdin) AND escape`
- Bare words are ANDed

Matching is exact by default. `--fuzzy` finds OCR errors and spelling variants but is
drastically noisier — one documented case went from 465 to 6,450 results. Reach for it
only when you suspect a name is being mis-scanned, and expect to sift hard.

**Search in French, or in both languages.** The collection is French-dominant, so an
English-only query will miss most of what is there: `"prestidigitation" OR "magic"`,
`"lecture de pensée" OR "mind reading"`, `"voyant" OR "clairvoyant"`. Names usually carry
across unchanged, but titles and honorifics do not — French press writes "le professeur
Reese", not "Prof. Reese".

## Being exhaustive

50 results per page — half the other sources, so page counts run higher. `--pages all`
sweeps everything. Periodical issues are returned individually rather than collapsed by
title, so a single newspaper's coverage appears as many separate dated results; that is
correct, and it is what makes date-ordered reconstruction possible.

By default only public-domain documents with downloadable OCR are returned.
`--include-restricted` widens the net, but the extra results generally cannot be
downloaded — useful for knowing something exists, not for reading it.

## False positives to expect

- **French OCR mangles accents**, and 19th-century typography compounds it. Names lose
  diacritics or gain them spuriously.
- **Name fragments**, as everywhere: check the `{braces}` in the snippet output.
- **The same wire story reprinted across dozens of papers.** Gallica will return each
  reprint separately. Recognise repeats and report them as one story with many
  appearances, rather than as many independent sources.
- **`texte` as document type** is generic and tells you little about the item.

## Cost

Rate-limited to one request per second with single concurrency, so sweeps are slow —
budget for it on large result sets. Downloads are cached under
`$XDG_CACHE_HOME/mentalism-research/gallica`. When reading many documents, dispatch
subagents and have them report back with page identifiers and quotes.
