---
name: gallica-search
description: Search Gallica, the Bibliothèque nationale de France digital library, with the `gallica` CLI. Use for French-language newspapers, periodicals and books — and for the French and European press coverage of touring performers.
---

# Gallica

The BnF's digital library: French newspapers, periodicals, books and manuscripts, plus a run of English-language titles such as the Paris edition of the *New York Herald*. The place to look for European press coverage of performers who toured the Continent.

## Commands

```sh
gallica search "<query>" [--pages N|N-M|all] [--sort ORDER] [filters] [--json]
gallica snippets <ark> "<query>"   # where the query appears inside one document
gallica get <ark> [--pages 30-35]  # download OCR text, prints path to the cached file
```

Note that `--pages` means different things on the two commands: *result* pages on `search`, *document* pages on `get`.

Filters for `search`: `--creator NAME` (repeatable), `--type TYPE` (repeatable, from `monographie`, `périodique`, `fascicule`, `manuscrit`, `image`, `carte`, `partition`), `--from-year`, `--to-year`, `--language CODE` (ISO 639-2: `fre`, `eng`, `ger`…), `--title TEXT`, `--include-restricted`, `--fuzzy`.

`--sort` takes `relevance` (default), `date_asc` or `date_desc`.

**Search returns no snippets.** This is the important workflow difference: `search` gives you documents, then `snippets` tells you whether a given document is actually worth anything, and only then does `get` download it. Going straight from search to `get` wastes a large download on documents that hold a single passing mention.

`snippets` marks matched terms in `{braces}` and reports a page identifier such as `PAG_30` for each occurrence. Its excerpts run to a sentence or two of real context, not a few words, so they are frequently enough to judge *and* to quote in a report without downloading anything.

**Those page identifiers feed straight into `get`.** Gallica serves OCR one page per request, so `get` takes a page range and `--pages` accepts the `PAG_30` form verbatim:

```sh
gallica snippets ark:/12148/bd6t5841739g "prestidigitateur"   # → occurrences on PAG_3, PAG_4
gallica get ark:/12148/bd6t5841739g --pages PAG_3-PAG_4       # → two requests, not sixteen
```

This is the whole shape of working with this source: search to find documents, snippets to find the pages, `get` to read only those pages. A `get` without `--pages` on a 544-page book asks for 544 requests against an endpoint that allows a burst of four before making you wait, so the command declines documents over 20 pages and tells you to pick a range. `--pages all` overrides that when you genuinely mean it.

## Query syntax

- Boolean operators **must be uppercase**: `AND`, `OR`, `NOT`
- `"quoted phrases"` match exactly, and always force exact matching
- Parentheses group: `(Houdini OR Houdin) AND escape`
- Bare words are ANDed

Matching is exact by default. `--fuzzy` finds OCR errors and spelling variants but is drastically noisier — one documented case went from 465 to 6,450 results. Reach for it only when you suspect a name is being mis-scanned, and expect to sift hard.

**Search in French, or in both languages.** The collection is French-dominant, so an English-only query will miss most of what is there: `"prestidigitation" OR "magic"`, `"lecture de pensée" OR "mind reading"`, `"voyant" OR "clairvoyant"`. Names usually carry across unchanged, but titles and honorifics do not — French press writes "le professeur Reese", not "Prof. Reese".

## The result count is not what you think it is

**Gallica ranks, it does not filter.** `text adj` scores documents rather than restricting to those containing the phrase, so the reported total is a relevance tail, not a set of matches. `"Robert-Houdin"` reports **124,709 results**. The first three are his own *Album des soirées fantastiques*, a Théâtre Robert-Houdin programme, and a satirical paper reviewing him; by result fifty you are into documents with no connection to him at all.

Three consequences, and they govern how this source is used:

- **Never quote the total as a finding.** "124,709 mentions of Robert-Houdin in the French press" is not true and would be a serious error in a report. It is a ranking depth, not a count.
- **Relevance ordering is what makes the source work.** It is the default. The material worth reading is in the first page or two, and it is genuinely good material.
- **`--pages all` is almost never right here.** On a ranked tail it sweeps tens of thousands of non-matches, costs hours at 3s a request, and invites a ban. Narrow the query with filters until the total is plausible, *then* consider sweeping.

Use `--sort date_asc` only once a query is narrowed enough that you intend to read the whole result set — a chronological reconstruction over a bounded date range, say. On an un-narrowed query, date order buries the good material behind thousands of weak matches, which is exactly the wrong thing to hand a researcher.

## Being exhaustive

50 results per page — half the other sources, so page counts run higher. Periodical issues are returned individually rather than collapsed by title, so a single newspaper's coverage appears as many separate dated results; that is correct, and it is what makes date-ordered reconstruction possible.

Exhaustivity on Gallica means *a well-bounded query swept completely*, not a broad query swept deeply. Bound it with `--from-year`/`--to-year`, `--language`, `--type` or `--title` first.

By default only public-domain documents with downloadable OCR are returned. `--include-restricted` widens the net, but the extra results generally cannot be downloaded — useful for knowing something exists, not for reading it.

## False positives to expect

- **French OCR mangles accents**, and 19th-century typography compounds it. Names lose diacritics or gain them spuriously. A single document's snippets gave *Robert-Boudin*, *Robert-Hoiïdin*, *Robert-Houdm* and *ROBERT-HOUSXK* alongside the correct spelling — all on pages that genuinely concern him. Expect the mis-scans to be the reason a name looks under-represented, and reach for `--fuzzy` when a search is suspiciously thin.
- **Hyphenated names are two tokens.** Snippets highlight `{Robert}-{Houdin}` as a separate pair, so a hyphenated name is matched loosely and drags in documents holding only the common half. This is a large part of why totals run so high.
- **Name fragments**, as everywhere: check the `{braces}` in the snippet output.
- **The same wire story reprinted across dozens of papers.** Gallica will return each reprint separately. Recognise repeats and report them as one story with many appearances, rather than as many independent sources.
- **`texte` as document type** is generic and tells you little about the item.

## Traps specific to this source

- **`--type périodique` matches nothing.** Because issues are returned individually rather than collapsed, periodicals appear as `fascicule`. Use that instead.
- **An anti-bot challenge can arrive as a normal-looking success** — HTTP 200 carrying an ALTCHA "Vérification de sécurité" page rather than a 429. The client detects it and refuses rather than caching it. If you see it, you have been querying too fast: **stop querying Gallica entirely and tell the user**. The block is measured in hours, not minutes, so retrying makes it worse and there is nothing to be gained by trying again in this session.
- **`get` is metered separately from search, and far more tightly.** OCR comes from a different endpoint, which allows a short burst and then answers HTTP 429 for minutes. Search and `snippets` keep working throughout, so search answering normally is no evidence that downloads will. Measured: the fifth request of a burst was refused whether they were spaced three seconds or five, and about two minutes of quiet restored the allowance.
- **Three different refusals, and they mean different things.** HTTP 429 is the ordinary budget running out — pages already fetched stay cached, so the same command a few minutes later resumes where it stopped. A stalled request that times out means the budget has been overdrawn repeatedly and Gallica has stopped answering that endpoint at all; treat it as a block and stop. An ALTCHA page is the site-wide block, and is the most serious. Only the first is worth waiting out.
- **`get` can also fail on documents that searched fine** — an image-only scan has no OCR to return. That is a property of the document, not an error to retry. The command says which pages came back empty.
- **Prefer `snippets` over `get` far more than on other sources.** Snippets are cheap, quote generously, and carry page identifiers, which is often the whole deliverable: a researcher wants `PAG_33` of a named document, not a megabyte of OCR. Reach for `get` only when a document warrants reading at length — and then only for the pages that do.
- Use `--refresh` to replace a cached copy you have reason to distrust.

## Cost

Searches are rate-limited to **one request every three seconds** with single concurrency, so sweeps are slow: 50 results per page means a 20-page sweep costs a minute of waiting before any reading starts. Budget for that, and prefer narrowing the query to sweeping a huge result set. BnF publishes no limit for the search endpoints, but established Gallica clients treat 3s as the point above which traffic is read as malicious.

That pacing is shared across every process, so parallel subagents share one budget rather than each getting their own. Fanning out widely speeds up the reading, not the fetching.

**`get` is metered in pages, and the budget is small.** OCR is served one page per request, and the client holds a burst of **4 pages** that refills at about **one page every 25 seconds** — measured against the endpoint, not published by BnF. So:

| What you ask for | Roughly what it costs |
| --- | --- |
| 3 pages found via snippets | seconds |
| an 8-page newspaper issue | ~2 minutes |
| a 200-page book | over an hour, and it will be interrupted |

This budget is shared across processes too, so subagents downloading in parallel drain one bucket. Fanning out does not multiply it.

**The practical consequence:** use snippets to find the pages, then fetch that range. A three-page `get` is cheap and near-instant; a whole-book `get` is the one mistake on this source that can cost the session's access rather than a little time. Pages are cached individually under `$XDG_CACHE_HOME/gallica-mcp`, so nothing already fetched is ever re-fetched, and a download stopped by a 429 resumes rather than restarts.

**Over-querying gets you banned, and the ban outlasts the session.** This is a free public service; a sweep that looks thorough from here looks like scraping from theirs. If requests start failing or returning something that is not what you asked for, stop and say so rather than retrying into a longer ban.
