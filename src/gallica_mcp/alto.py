"""Turn Gallica's per-page ALTO XML into plain text.

Gallica serves OCR one page at a time as ALTO XML from `RequestDigitalElement`.
This module is the conversion only; the fetching, pacing and caching live in
`client.py`.

ALTO nests `TextBlock` > `TextLine` > `String`, which maps onto blank-line-
separated blocks of newline-separated lines. Keeping that structure matters for
a research tool: a newspaper page is columns of unrelated articles, and
flattening it into one paragraph glues the end of one story to the start of
another, which is exactly the kind of false adjacency that produces a
misquotation.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# Gallica's ALTO declares `encoding="ISO-8859-1"` in its XML prolog and then
# serves UTF-8 bytes. Honouring the declaration turns every accented French
# word into mojibake ("SCÃNE" for "SCÈNE"), so the declaration is stripped and
# the bytes are decoded as what they actually are.
_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")


def _local_name(tag: str) -> str:
    """The tag without its namespace, since BnF uses two ALTO namespaces."""
    return tag.rsplit("}", 1)[-1]


def alto_to_text(payload: bytes) -> str:
    """Extract the reading text from one page of ALTO XML.

    Args:
        payload: Raw bytes of an ALTO document as served by Gallica.

    Returns:
        Plain text, blocks separated by blank lines. Empty when the page
        carries no OCR - an illustration plate, say, which is a property of the
        page rather than an error.
    """
    decoded = payload.decode("utf-8", errors="replace")
    root = ET.fromstring(_XML_DECLARATION.sub("", decoded).lstrip())

    blocks: list[str] = []
    for block in root.iter():
        if _local_name(block.tag) != "TextBlock":
            continue

        lines = [
            line_text
            for line in block.iter()
            if _local_name(line.tag) == "TextLine"
            and (line_text := _line_to_text(line))
        ]
        if lines:
            blocks.append("\n".join(lines))

    return "\n\n".join(blocks).strip()


def _line_to_text(line: ET.Element) -> str:
    """Join one TextLine's words, rejoining any word broken across the break.

    A word hyphenated at the end of a line is stored twice: as the two visible
    halves, and as the whole word in `SUBS_CONTENT` on both. Emitting the whole
    word on the first half and dropping the second reconstructs it, so a search
    over the downloaded text finds "connoitre" rather than only "con-".
    """
    words: list[str] = []

    for element in line:
        if _local_name(element.tag) != "String":
            continue

        subs_type = element.get("SUBS_TYPE")
        if subs_type == "HypPart2":
            continue
        if subs_type == "HypPart1":
            content = element.get("SUBS_CONTENT") or element.get("CONTENT") or ""
        else:
            content = element.get("CONTENT") or ""

        if content:
            words.append(content)

    return " ".join(words).strip()
