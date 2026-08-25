from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    offset: int
    line: int
    column: int


class LexError(ValueError):
    pass


_SPECIAL = set('{}=<>!#"')


def lex(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    column = 1

    def advance(raw: str) -> None:
        nonlocal line, column
        newlines = raw.count("\n")
        if newlines:
            line += newlines
            column = len(raw.rsplit("\n", 1)[-1]) + 1
        else:
            column += len(raw)

    while i < len(text):
        char = text[i]

        if char.isspace() or char == "\ufeff":
            advance(char)
            i += 1
            continue

        start = i
        start_line = line
        start_column = column

        if char == "#":
            end = text.find("\n", i)
            if end < 0:
                end = len(text)
            raw = text[i:end]
            tokens.append(
                Token("COMMENT", raw[1:].lstrip(), start, start_line, start_column)
            )
            advance(raw)
            i = end
            continue

        if char == '"':
            i += 1
            column += 1
            content_start = i
            escaped = False
            while i < len(text):
                current = text[i]
                if escaped:
                    escaped = False
                    i += 1
                    column += 1
                    continue
                if current == "\\":
                    escaped = True
                    i += 1
                    column += 1
                    continue
                if current == '"':
                    raw_content = text[content_start:i]
                    tokens.append(
                        Token("STRING", raw_content, start, start_line, start_column)
                    )
                    i += 1
                    column += 1
                    break
                if current == "\n":
                    line += 1
                    column = 1
                else:
                    column += 1
                i += 1
            else:
                raise LexError(f"Unterminated string at {start_line}:{start_column}")
            continue

        if char == "{":
            tokens.append(Token("LBRACE", char, start, start_line, start_column))
            i += 1
            column += 1
            continue
        if char == "}":
            tokens.append(Token("RBRACE", char, start, start_line, start_column))
            i += 1
            column += 1
            continue

        if char in "!<>=":
            two = text[i : i + 2]
            if two in {"!=", "<=", ">="}:
                tokens.append(Token("OP", two, start, start_line, start_column))
                i += 2
                column += 2
                continue
            if char in "=<>":
                tokens.append(Token("OP", char, start, start_line, start_column))
                i += 1
                column += 1
                continue
            raise LexError(f"Unexpected '!' at {start_line}:{start_column}")

        end = i
        while end < len(text):
            current = text[end]
            if current.isspace() or current in _SPECIAL:
                break
            end += 1
        if end == i:
            raise LexError(f"Unexpected character {char!r} at {line}:{column}")
        raw = text[i:end]
        tokens.append(Token("ATOM", raw, start, start_line, start_column))
        advance(raw)
        i = end

    tokens.append(Token("EOF", "", len(text), line, column))
    return tokens
