"""Turn arbitrary text into something worth saying out loud."""

import re

_WHITESPACE = re.compile(r"\s+")
# Sentence ends (with any closing quote or bracket) and clause breaks, followed by the
# whitespace a piece may be cut at. A sentence end followed by a lowercase word is an
# abbreviation (`e.g. here`), not an end. Typographic characters are written as escapes.
_SENTENCE_END = re.compile(r"[.!?\u2026][\"'\u201d\u2019)\]]*(\s+)(?![a-z])")
_CLAUSE_END = re.compile(r"[,;:\u2014\u2013](\s+)")
_FINAL = re.compile(r"[.!?\u2026][\"'\u201d\u2019)\]]*$")
_TRAILING_CLAUSE = re.compile(r"\s*[,;:\u2014\u2013]+$")


def normalize(text: str | None) -> str:
    """Collapse to one line. Nothing is cut: a long text is spoken in `sentences`, and a
    long sentence sent to a speech model in `pieces`.

    Raises:
        ValueError: if nothing is left after collapsing.
    """
    collapsed = _WHITESPACE.sub(" ", text or "").strip()
    if not collapsed:
        raise ValueError("nothing to speak: text is empty")
    return collapsed


def sentences(text: str) -> list[str]:
    """One-line `text`'s sentences, whole however long, each a separate utterance so the
    first is heard while the next is prepared. A one-word sentence (`Dr.`) goes with the
    sentence after it."""
    return pieces(text, max_chars=max(len(text), 1))


def pieces(text: str, *, max_chars: int) -> list[str]:
    """One-line `text` in the pieces a speech model is sent one at a time: a sentence a
    piece, because MagpieTTS repeats and garbles words when one request holds several. A
    sentence over `max_chars` is cut at its clauses, packed up to the limit, then at its
    words, and a word longer than the limit where the limit falls. A one-word sentence,
    usually an abbreviation such as `Dr.`, goes with the sentence after it when both
    fit. Every character but the whitespace a cut falls on is kept.

    Raises:
        ValueError: `max_chars` is under 1.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be at least 1, not {max_chars}")
    cut: list[str] = []
    held = ""  # a one-word sentence waiting for the sentence after it
    for sentence in _split_after(_SENTENCE_END, text):
        if held:
            if len(held) + 1 + len(sentence) <= max_chars:
                sentence = f"{held} {sentence}"
            else:
                cut.append(held)
            held = ""
        if " " not in sentence and len(sentence) <= max_chars:
            held = sentence
        elif len(sentence) <= max_chars:
            cut.append(sentence)
        else:
            cut += _pack(_clauses(sentence, max_chars), max_chars)
    if held:
        cut.append(held)
    return cut


def close(piece: str) -> str:
    """`piece` ending in sentence-final punctuation, so a speech model closes the phrase:
    a trailing clause mark becomes a full stop, and a piece with neither gets one."""
    if _FINAL.search(piece):
        return piece
    return _TRAILING_CLAUSE.sub("", piece) + "."


def _split_after(pattern: re.Pattern[str], text: str) -> list[str]:
    """`text` cut at each whitespace run `pattern` marks; the punctuation stays left."""
    cut, start = [], 0
    for match in pattern.finditer(text):
        cut.append(text[start : match.start(1)])
        start = match.end(1)
    cut.append(text[start:])
    return [piece for piece in cut if piece]


def _clauses(sentence: str, max_chars: int) -> list[str]:
    """`sentence`'s clauses, a clause over `max_chars` cut into its words."""
    units: list[str] = []
    for clause in _split_after(_CLAUSE_END, sentence):
        units += [clause] if len(clause) <= max_chars else _words(clause, max_chars)
    return units


def _words(text: str, max_chars: int) -> list[str]:
    cut: list[str] = []
    for word in text.split():
        cut += [word[i : i + max_chars] for i in range(0, len(word), max_chars)]
    return _pack(cut, max_chars)


def _pack(units: list[str], max_chars: int) -> list[str]:
    packed: list[str] = []
    for unit in units:
        if packed and len(packed[-1]) + 1 + len(unit) <= max_chars:
            packed[-1] = f"{packed[-1]} {unit}"
        else:
            packed.append(unit)
    return packed
