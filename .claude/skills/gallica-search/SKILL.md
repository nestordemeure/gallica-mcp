---
name: gallica-search
description: Search Gallica, the digital library of the Bibliothèque nationale de France, with the `gallica` CLI. Use it for French-language newspapers, periodicals and books, and for the French and European press reports about performers who travelled.
---

# Gallica

The digital library of the BnF: French newspapers, periodicals, books and manuscripts. It also holds some English-language titles, such as the Paris edition of the *New York Herald*. Use it for European press reports about performers who travelled in Continental Europe.

## Commands

```sh
gallica search "<query>" [--pages N|N-M|all] [--sort ORDER] [filters] [--json]
gallica snippets <ark> "<query>"   # where the query appears inside one document
gallica get <ark> [--pages 30-35]  # download OCR text, prints path to the cached file
```

Note that `--pages` has a different meaning on each command. On `search` it means the *result* pages. On `get` it means the *document* pages.

The filters for `search` are `--creator NAME` (repeatable), `--type TYPE` (repeatable, from `monographie`, `périodique`, `fascicule`, `manuscrit`, `image`, `carte`, `partition`), `--from-year`, `--to-year`, `--language CODE` (ISO 639-2: `fre`, `eng`, `ger`…), `--title TEXT`, `--subject HEADING`, `--publisher NAME`, `--library NAME`, `--min-ocr-quality SCORE`, `--include-restricted` and `--fuzzy`.

`--sort` takes `relevance` (default), `date_asc` or `date_desc`.

**A search gives no snippets.** This is the important difference in the procedure. `search` gives you documents. Then `snippets` tells you if a document has value. Only then does `get` download it. If you go directly from `search` to `get`, you spend a large download on documents that hold one brief mention.

`snippets` marks the matched terms with `{braces}` and gives a page identifier such as `PAG_30` for each occurrence. Its snippets hold one or two sentences of real context, not a few words. Thus they are frequently enough to judge a document *and* to quote it in a report with no download.

**These page identifiers go directly into `get`.** Gallica sends the OCR one page for each request, so `get` takes a page range, and `--pages` accepts the `PAG_30` form exactly:

```sh
gallica snippets ark:/12148/bd6t5841739g "prestidigitateur"   # → occurrences on PAG_3, PAG_4
gallica get ark:/12148/bd6t5841739g --pages PAG_3-PAG_4       # → two requests, not sixteen
```

This is the full procedure for this source: search to find the documents, `snippets` to find the pages, and `get` to read only those pages. A `get` command without `--pages` on a 544-page book asks for 544 requests. The endpoint permits a burst of four requests and then makes you wait. Thus the command refuses a document of more than 20 pages, and tells you to select a range. `--pages all` overrides this when you truly intend it.

## Query syntax

- The boolean operators **must be uppercase**: `AND`, `OR`, `NOT`
- `"quoted phrases"` match exactly, and they always force an exact match
- Parentheses group the terms: `(Houdini OR Houdin) AND escape`
- The tool joins bare words with AND

A match is exact by default. `--fuzzy` finds OCR errors and spelling variants, but it gives many more incorrect results. One measured case moved from 465 to 6,450 results. Use it only when you suspect that the OCR holds a name incorrectly, and expect much rejection work.

**Search in French, or in both languages.** The collection is mostly French, so a query in English only will not find most of the material: `"prestidigitation" OR "magic"`, `"lecture de pensée" OR "mind reading"`, `"voyant" OR "clairvoyant"`. Names usually stay the same, but titles and honorifics do not. The French press writes "le professeur Reese", not "Prof. Reese".

## The four filters that have a large effect

Most of the filters above only make a result set smaller. These four change the character of a search, and two of them make a real result set out of the ranked tail of Gallica.

**`--subject HEADING`** selects on the subject headings of the BnF catalogue (RAMEAU), in French. This is the sharpest instrument here, because it is a *strict* filter and the text index is not. `--subject Prestidigitation` gives **29 results**, not a six-figure tail, and each one is truly about conjuring. Write a subdivision with two hyphens: `--subject 'Prestidigitation -- XIXe siecle'` gives **6 results**, and one of them is Robert-Houdin's *Confidences et révélations*. You can leave out the accents.

**Warning: read this before you use `--subject`.** The headings belong to the parent catalogue record, and periodical *issues* have none. `--subject Prestidigitation --type fascicule` gives **zero**, and so does each combination of a subject with a search of the press. Use `--subject` to find catalogued books, prints and programmes. Never use it to limit newspaper coverage, where it removes everything and gives no message.

**`--min-ocr-quality SCORE`** keeps only the documents whose OCR score is SCORE or more, out of 100. The central problem of this source is scans that a person cannot read, so this is the most generally useful of the four filters. `"Tour Eiffel"` reports 622,818 results, and `--min-ocr-quality 99` reduces this to **113,479**. It also moves the documents that a person can read to the top. It is the correct filter to use *before* `get`, because you cannot quote a document with bad OCR. Any value above 0 excludes material with no OCR at all — engravings, photographs and image-only scans — so do not combine it with `--type image`.

**`--publisher NAME`** matches the publisher as printed: `"Tour Eiffel" --publisher Hachette` gives **287 results** in place of 622,818. Note one risk: this field also holds the place of publication in parentheses (`E. Voisin (Paris)`). Thus `--publisher Paris` matches the *place*. It is not a place filter, and this source has no index of the place of publication.

**`--library NAME`** selects the institution that holds the item. It matches against the provenance string of the record. This is how you reach a full specialist collection: `--library 'Centre National des Arts du Cirque'` gives **1,028 items**, mostly dated circus and variety programmes. This is an unusually rich set for the history of performance, and you can examine it with no text query at all. The departments of the BnF operate in the same way: `--library 'departement Arts du spectacle'`. You can leave out the accents.

Two strict filters combine correctly: `--subject Prestidigitation --min-ocr-quality 50` gives **12 results**, a set that you can read completely.

## The result count is not a count

**Gallica ranks the documents. It does not filter them.** `text adj` gives each document a score. It does not select only the documents that hold the phrase. Thus the reported total is a relevance tail, not a set of matches.

`"Robert-Houdin"` reports **124,709 results**. The first three are his own *Album des soirées fantastiques*, a programme of the Théâtre Robert-Houdin, and a satirical paper that reviews him. At result fifty, the documents have no relation to him.

This has three consequences, and they control how you use this source:

- **Never report the total to the user as a finding.** "124,709 mentions of Robert-Houdin in the French press" is not true, and it would be a serious error in a report. The number is a rank depth, not a count.
- **The order by relevance is what makes the source work.** It is the default. The material of value is on the first one or two pages, and that material is good.
- **`--pages all` is almost always incorrect here.** On a ranked list it collects tens of thousands of documents that do not match. It costs hours at 3s for each request, and it can cause a block. Make the query more narrow with filters until the total is credible. *Then* consider a complete search.

**A strict filter corrects the total, and this is the practical solution.** The ranked tail comes from the text index alone. The metadata filters intersect that tail strictly, so the reported number becomes a real count of matches again. `--subject Prestidigitation` reports 29 and means 29. This is why `--pages all` is safe on a filtered query and dangerous on a query with no filter. It is also the reason to spend one filter in place of more pagination.

Use `--sort date_asc` only after a query is narrow enough that you intend to read the full result set — for example, a chronological reconstruction across a limited date range. On a query with no limits, an order by date puts thousands of weak matches in front of the good material, which is the opposite of what a researcher needs.

## How to be complete

There are 50 results on each page. This is half of the other sources, so the page counts are higher. The source gives each periodical issue separately. It does not group them by title. Thus the coverage of one newspaper appears as many separate dated results. This is correct, and it is what makes a reconstruction in date order possible.

Completeness on Gallica means *a well-limited query collected completely*. It does not mean a broad query collected deeply. Limit the query first with `--from-year`, `--to-year`, `--language`, `--type`, `--title`, `--min-ocr-quality` or `--publisher`. Use `--subject` or `--library` when the material is catalogued and is not press.

Two of these limits remove real material, so select them with care. `--subject` removes all periodical coverage. `--min-ocr-quality` removes each item with no OCR. For a complete search of the press, limit by date and by type instead.

By default the source gives only public-domain documents with an OCR download. `--include-restricted` gives more results, but you usually cannot download them. Use it to know that something exists, not to read it.

## False positives to expect

- **French OCR damages the accents**, and the typography of the 19th century makes this worse. Names lose their diacritics, or they receive diacritics that are not correct. The snippets of one document gave *Robert-Boudin*, *Robert-Hoiïdin*, *Robert-Houdm* and *ROBERT-HOUSXK* together with the correct spelling. Each of those pages is truly about him. Expect these errors to be the reason that a name looks rare, and use `--fuzzy` when a search gives very few results.
- **A hyphenated name is two tokens.** The snippets highlight `{Robert}-{Houdin}` as a separate pair, so a hyphenated name matches loosely and brings in documents that hold only the common half. This is a large part of the reason that the totals are so high.
- **Fragments of names**, as on each source. Examine the `{braces}` in the snippet output.
- **The same wire story printed in tens of newspapers.** Gallica gives each reprint separately. Identify the repetitions, and report them as one story with many appearances. Do not report them as many independent sources.
- **`texte` as the document type** is general, and it tells you almost nothing about the item.

## Risks specific to this source

- **`--type périodique` matches nothing.** The source gives each issue separately, so the periodicals appear as `fascicule`. Use `fascicule`.
- **`--subject` and a search of the press exclude each other**, and the failure gives no message: zero results, identical to a term that no person wrote about. If a search with a subject filter gives no results, remove the subject before you make a conclusion.
- **There is no filter for the place of publication, and `--publisher` is not one.** Gallica has no index of places (`dc.coverage` does not exist there), and the publisher field holds the city in parentheses. Thus `--publisher Lyon` gives each record that *mentions* Lyon in that field. If you need a place, filter with `--library`, or read the place from the results.
- **The subject headings and the library names must be almost exact.** They are catalogue strings, not free text. `--library 'Arts du spectacle'` operates, and an institution that you invent gives zero. You can leave out the accents, but you cannot invent the word order. Take the exact string from the `source` field or the `subject` field of a result that you already have.
- **An anti-bot challenge can arrive as a normal success.** The server sends HTTP 200 with an ALTCHA "Vérification de sécurité" page, not HTTP 429. The client detects this and refuses it. It does not put it in the cache. If you see it, you sent requests too fast. **Stop all requests to Gallica. Then tell the user.** The block is hours long, not minutes long. A second attempt makes it worse, and nothing in this session can improve it.
- **`get` has a separate budget from `search`, and that budget is much smaller.** The OCR comes from a different endpoint. That endpoint permits a short burst, and then it answers HTTP 429 for minutes. `search` and `snippets` continue to operate in this condition. Thus a normal answer from `search` is no evidence that a download will succeed. Measured: the endpoint refused the fifth request of a burst, at both 3 seconds and 5 seconds between the requests. Approximately two minutes with no requests restored the budget.
- **Three different refusals have three different meanings.** HTTP 429 means that the ordinary budget is empty. The pages that you already received stay in the cache, so the same command a few minutes later continues from the position where it stopped. A request that stops and then times out means that you overdrew the budget repeatedly, and Gallica stopped all answers on that endpoint. Treat this as a block, and stop. An ALTCHA page is the block of the full site, and it is the most serious. Only the first condition is worth a wait.
- **`get` can also fail on documents that a search found correctly.** An image-only scan has no OCR to give. This is a property of the document. It is not an error to retry. The command tells you which pages gave no text.
- **Use `snippets` in place of `get` much more than on the other sources.** The snippets have a low cost, they quote generously, and they carry page identifiers. Frequently they are the full product: a researcher wants `PAG_33` of a named document, not a megabyte of OCR. Use `get` only when a document deserves a long reading, and then only for the pages that deserve it.
- Use `--refresh` to replace a copy in the cache that you have a reason to doubt.

## Cost

The client permits **one request every three seconds**, with one request at a time. Thus a search is slow. At 50 results on each page, a search of 20 pages costs one minute of waiting before you can read anything. Plan for this, and make the query more narrow in place of a search of a very large result set. The BnF publishes no limit for the search endpoints, but the established Gallica clients treat 3s as the rate above which the BnF reads the traffic as an attack.

All processes share this rate limit. Therefore parallel subagents share one budget. Many parallel subagents read the documents more quickly. They do not send the requests more quickly.

**`get` has a budget in pages, and that budget is small.** The server sends the OCR one page for each request. The client holds a burst of **4 pages**, and the budget increases by approximately **one page every 25 seconds**. These figures come from measurements against the endpoint. The BnF does not publish them. Thus:

| What you ask for | Approximate cost |
| --- | --- |
| 3 pages found with snippets | seconds |
| an 8-page newspaper issue | approximately 2 minutes |
| a 200-page book | more than one hour, with interruptions |

All processes also share this budget, so parallel subagents take from one budget. More subagents do not increase it.

**The practical consequence:** use `snippets` to find the pages, then download that range. A `get` of three pages has a low cost and is almost immediate. A `get` of a full book is the one error on this source that can cost you the access of the session, not only a little time. The client keeps each page in a cache under `$XDG_CACHE_HOME/gallica-mcp`, so it never downloads a page two times, and a download that HTTP 429 stopped continues from that position.

**Warning: Do not send too many requests. Too many requests cause the archive to block you, and the block continues after this session.**

This is a free public service. A search that looks thorough to you looks like data collection to the archive operators. Sometimes the requests start to fail. Sometimes they give content that you did not ask for. If this occurs, stop. Tell the user. Do not send the request again, because a repeated request makes the block longer.
