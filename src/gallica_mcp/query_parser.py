"""Utilities for parsing simple boolean queries into Gallica CQL clauses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence


class QueryParseError(ValueError):
    """Raised when a user text query cannot be parsed."""


@dataclass(frozen=True)
class Token:
    """Token representation for the query parser."""

    type: str
    value: str


def _tokenize(expr: str) -> List[Token]:
    """Convert a text expression into tokens understood by the parser."""
    tokens: List[Token] = []
    i = 0
    length = len(expr)

    while i < length:
        ch = expr[i]

        if ch.isspace():
            i += 1
            continue

        if ch == '"':
            i += 1
            buf: List[str] = []
            escaped = False
            while i < length:
                curr = expr[i]
                i += 1
                if escaped:
                    buf.append(curr)
                    escaped = False
                    continue
                if curr == '\\':
                    escaped = True
                    continue
                if curr == '"':
                    break
                buf.append(curr)
            else:
                raise QueryParseError("Unterminated quoted phrase")
            tokens.append(Token("PHRASE", "".join(buf)))
            continue

        if ch in "()":
            tokens.append(Token("LPAREN" if ch == "(" else "RPAREN", ch))
            i += 1
            continue

        if ch == '!':
            tokens.append(Token("NOT", "NOT"))
            i += 1
            continue

        start = i
        while (
            i < length
            and not expr[i].isspace()
            and expr[i] not in '()"!'
            and expr[i] not in "()"
        ):
            i += 1

        value = expr[start:i]
        upper_value = value.upper()
        if upper_value in {"AND", "&&"}:
            tokens.append(Token("AND", "AND"))
        elif upper_value in {"OR", "||"}:
            tokens.append(Token("OR", "OR"))
        elif upper_value in {"NOT"}:
            tokens.append(Token("NOT", "NOT"))
        else:
            tokens.append(Token("WORD", value))

    return tokens


class _Node:
    """Base AST node."""


@dataclass
class _TermNode(_Node):
    value: str
    exact: bool = False


@dataclass
class _NotNode(_Node):
    child: _Node


@dataclass
class _AndNode(_Node):
    children: Sequence[_Node]


@dataclass
class _OrNode(_Node):
    children: Sequence[_Node]


class _BooleanQueryParser:
    """Recursive descent parser for simple boolean expressions."""

    def __init__(self, expr: str):
        tokens = _tokenize(expr)
        self._tokens = tokens
        self._index = 0

    def parse(self) -> _Node:
        if not self._tokens:
            raise QueryParseError("Query is empty")
        node = self._parse_or()
        if self._index != len(self._tokens):
            token = self._tokens[self._index]
            raise QueryParseError(f"Unexpected token '{token.value}'")
        return node

    def _parse_or(self) -> _Node:
        node = self._parse_and()
        children: List[_Node] = [node]
        while self._match("OR"):
            children.append(self._parse_and())
        if len(children) == 1:
            return children[0]
        return _OrNode(children)

    def _parse_and(self) -> _Node:
        node = self._parse_not()
        children: List[_Node] = [node]
        while True:
            if self._match("AND"):
                children.append(self._parse_not())
            elif self._next_starts_expression():
                children.append(self._parse_not())
            else:
                break
        if len(children) == 1:
            return children[0]
        return _AndNode(children)

    def _parse_not(self) -> _Node:
        if self._match("NOT"):
            child = self._parse_not()
            return _NotNode(child)
        return self._parse_primary()

    def _parse_primary(self) -> _Node:
        token = self._peek()
        if token is None:
            raise QueryParseError("Unexpected end of query")

        if token.type == "LPAREN":
            self._advance()
            node = self._parse_or()
            if not self._match("RPAREN"):
                raise QueryParseError("Missing closing parenthesis")
            return node

        if token.type == "PHRASE":
            self._advance()
            return _TermNode(token.value, exact=True)

        if token.type == "WORD":
            self._advance()
            return _TermNode(token.value, exact=False)

        raise QueryParseError(f"Unexpected token '{token.value}'")

    def _peek(self) -> Token | None:
        if self._index >= len(self._tokens):
            return None
        return self._tokens[self._index]

    def _advance(self) -> Token | None:
        token = self._peek()
        if token is not None:
            self._index += 1
        return token

    def _match(self, token_type: str) -> bool:
        token = self._peek()
        if token and token.type == token_type:
            self._index += 1
            return True
        return False

    def _next_starts_expression(self) -> bool:
        token = self._peek()
        if token is None:
            return False
        return token.type in {"WORD", "PHRASE", "LPAREN", "NOT"}


_PREC_TERM = 4
_PREC_NOT = 3
_PREC_AND = 2
_PREC_OR = 1


def _escape_cql_literal(value: str) -> str:
    """Escape double quotes and backslashes for CQL string literals."""
    return value.replace("\\", "\\\\").replace('"', r"\"")


def _emit_cql(node: _Node) -> tuple[str, int]:
    """Convert an AST node into a CQL fragment and return (fragment, precedence)."""
    if isinstance(node, _TermNode):
        relation = "adj" if node.exact else "all"
        literal = _escape_cql_literal(node.value)
        return f'text {relation} "{literal}"', _PREC_TERM

    if isinstance(node, _NotNode):
        child_str, child_prec = _emit_cql(node.child)
        if child_prec < _PREC_NOT:
            child_str = f"({child_str})"
        return f"not {child_str}", _PREC_NOT

    if isinstance(node, _AndNode):
        parts: List[str] = []
        for child in node.children:
            child_str, child_prec = _emit_cql(child)
            if child_prec < _PREC_AND:
                child_str = f"({child_str})"
            parts.append(child_str)
        return " and ".join(parts), _PREC_AND

    if isinstance(node, _OrNode):
        parts: List[str] = []
        for child in node.children:
            child_str, child_prec = _emit_cql(child)
            if child_prec < _PREC_OR:
                child_str = f"({child_str})"
            parts.append(child_str)
        return " or ".join(parts), _PREC_OR

    raise TypeError(f"Unsupported node type: {type(node)!r}")


def build_text_query_clause(expr: str) -> str:
    """Parse a free-text boolean expression into a Gallica-compatible CQL clause."""
    parser = _BooleanQueryParser(expr.strip())
    node = parser.parse()
    clause, _ = _emit_cql(node)
    return clause
