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
gallica get <ark>                  # download OCR text, prints path to the cached file
```

Filters for `search`: `--creator NAME` (repeatable), `--type TYPE` (repeatable, from `monographie`, `périodique`, `fascicule`, `manuscrit`, `image`, `carte`, `partition`), `--from-year`, `--to-year`, `--language CODE` (ISO 639-2: `fre`, `eng`, `ger`…), `--title TEXT`, `--include-restricted`, `--fuzzy`.

`--sort` takes `relevance` (default), `date_asc` or `date_desc`.

**Search returns no snippets.** This is the important workflow difference: `search` gives you documents, then `snippets` tells you whether a given document is actually worth anything, and only then does `get` download it. Going straight from search to `get` wastes a large download on documents that hold a single passing mention.

`snippets` marks matched terms in `{braces}` and reports a page identifier such as `PAG_30` for each occurrence. Its excerpts run to a sentence or two of real context, not a few words, so they are frequently enough to judge *and* to quote in a report without downloading anything.

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
- **An anti-bot challenge can arrive as a normal-looking success** — HTTP 200 carrying an ALTCHA "Vérification de sécurité" page rather than a 429. `get` detects it and refuses rather than caching it. If you see it, you have been querying too fast: **stop querying Gallica entirely and tell the user**. The block is measured in hours, not minutes, so retrying makes it worse and there is nothing to be gained by trying again in this session.
- **`get` is the expensive command, the first to be refused and the last to recover.** Downloads come from a different endpoint (`texteBrut`) to search and snippets, and it is guarded harder: in testing, search and `snippets` kept answering normally on a document whose `get` came back as a challenge page. So a failing `get` does not mean you are safely under the limit elsewhere — it is the earliest warning you are over it. It also cools down slowest, so search recovering tells you nothing about whether downloads have. Treat a refusal as the signal to stop, not as one command to work around. See **Cost** below for how to budget around it.
- **`get` can also fail on documents that searched fine** — an image-only scan has no OCR to return. That is a property of the document, not an error to retry. A challenge page says so explicitly; a document with no text does not.
- **Prefer `snippets` over `get` far more than on other sources.** Snippets are cheap, quote generously, and carry page identifiers, which is often the whole deliverable: a researcher wants `PAG_33` of a named document, not a megabyte of OCR. Reach for `get` only when a document warrants reading at length.
- Use `--refresh` to replace a cached copy you have reason to distrust.

## Cost

Rate-limited to **one request every three seconds** with single concurrency, so sweeps are slow: 50 results per page means a 20-page sweep costs a minute of waiting before any reading starts. Budget for that, and prefer narrowing the query to sweeping a huge result set. BnF publishes no limit for these endpoints, but established Gallica clients treat 3s as the point above which traffic is read as malicious. Downloads are cached under `$XDG_CACHE_HOME/gallica-mcp`. When reading many documents, dispatch subagents and have them report back with page identifiers and quotes.

That pacing is shared across every process, so parallel subagents share one budget rather than each getting their own. Fanning out widely speeds up the reading, not the fetching.

**Requests are not all worth the same, and `get` is the expensive one.** The 3s interval paces them identically, but Gallica does not treat them identically. A `get` pulls a whole document's OCR off `texteBrut`, and it counts for far more against whatever budget BnF is actually keeping than a search or a `snippets` call does — a handful of downloads can put you over a line that dozens of searches would not have reached. Budget in documents downloaded, not in requests made.

**And it recovers slowest.** When `get` starts being refused, it stays refused long after the search endpoints are answering normally again. Search coming back is therefore not evidence that downloads have come back, and it is not permission to start retrying them — the usual pattern is that you resume searching happily, assume the block has lifted, and walk straight back into it on the first download. Once `get` has been refused, treat downloading as closed for the session and work from snippets, even when everything else looks healthy.

The practical consequence: decide a document is worth reading in full *before* spending a `get` on it, using snippets to make that call. Downloads are cached under `$XDG_CACHE_HOME/gallica-mcp`, so the cost is paid once per document — but a download spent on a document that turns out to hold one passing mention is not refundable, and on this source it is one of the few mistakes that can end the session's access rather than merely waste a little time.

**Over-querying gets you banned, and the ban outlasts the session.** This is a free public service; a sweep that looks thorough from here looks like scraping from theirs. If requests start failing or returning something that is not what you asked for, stop and say so rather than retrying into a longer ban.
