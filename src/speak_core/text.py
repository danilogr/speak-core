"""Turn arbitrary text into something worth saying out loud."""

import re

_WHITESPACE = re.compile(r"\s+")
# Sentence ends and clause breaks, each with any closing quote or bracket after it, and
# the whitespace a piece may be cut at. Latin punctuation needs whitespace after it; the
# full-width marks of Chinese and Japanese, written without spaces, do not. Typographic
# characters are written as escapes.
_CLOSERS = r"[\"'\u201d\u2019)\]\u300d\u300f\uff09]*"
_SENTENCE_END = re.compile(rf"(?:[.!?\u2026]{_CLOSERS}(?=\s)|[\u3002\uff01\uff1f]{_CLOSERS})(\s*)")
_CLAUSE_END = re.compile(
    rf"(?:[,;:\u2014\u2013]{_CLOSERS}(?=\s)|[\uff0c\u3001\uff1b\uff1a]{_CLOSERS})(\s*)"
)
_FINAL = re.compile(rf"[.!?\u2026\u3002\uff01\uff1f]{_CLOSERS}$")
_FULL_WIDTH_FINAL = re.compile(rf"[\u3002\uff01\uff1f]{_CLOSERS}$")
_TRAILING_CLAUSE = re.compile(rf"\s*[,;:\u2014\u2013\uff0c\u3001\uff1b\uff1a]+({_CLOSERS})$")
_WORD = re.compile(r"\w")
# Abbreviations a full stop after which ends no sentence: NVIDIA's English
# text-normalization grammar's `sentence_boundary_exceptions.txt`, the list the speech
# server itself does not break a sentence after.
_NO_BREAK_AFTER = re.compile(
    r"(?<![\w.])(?:Mr|Mrs|Dr|St|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.$"
)
# The longest of those, its full stop, and the character before it.
_NO_BREAK_REACH = 5
# A comma between a month, or a month and day, and a four-digit year: `May 3, 1999`.
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November"
    r"|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
)
_DATE_COMMA = re.compile(rf"\b({_MONTH}(?:\s+\d{{1,2}}(?:st|nd|rd|th)?)?),(?=\s+\d{{4}}\b)")


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
    first is heard while the next is prepared. A one-word sentence (`Prof.`) goes with the
    sentence after it."""
    return pieces(text, max_chars=max(len(text), 1))


def pieces(text: str, *, max_chars: int) -> list[str]:
    """One-line `text` in the pieces a speech model is sent one at a time: a sentence a
    piece, because MagpieTTS repeats and garbles words when one request holds several. A
    sentence over `max_chars` is cut at its clauses, packed up to the limit, then at its
    words, and a word longer than the limit where the limit falls. A one-word sentence,
    usually an abbreviation such as `Prof.`, goes with the sentence after it when both
    fit; one holding no word (`!!!`) at the end goes with the sentence before it. Every
    character but the whitespace a cut falls on is kept.

    Raises:
        ValueError: `max_chars` is under 1.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be at least 1, not {max_chars}")
    cut: list[str] = []
    held = ""  # a one-word sentence waiting for the sentence after it
    for sentence in _split_after(_SENTENCE_END, text, unless_lowercase=True):
        if held:
            if len(held) + 1 + len(sentence) <= max_chars:
                sentence = f"{held} {sentence}"
            else:
                cut.append(held)
            held = ""
        if _one_word(sentence) and len(sentence) <= max_chars:
            held = sentence
        elif len(sentence) <= max_chars:
            cut.append(sentence)
        else:
            cut += _pack(_clauses(sentence, max_chars), max_chars)
    if held and cut and not _WORD.search(held) and len(cut[-1]) + 1 + len(held) <= max_chars:
        cut[-1] = f"{cut[-1]} {held}"
    elif held:
        cut.append(held)
    return cut


def without_date_commas(text: str) -> str:
    """`text` without the comma between a month or a month and day and its year (`May 3,
    1999` as `May 3 1999`). NeMo-Speech.cpp 0.2.0's text normalization says an audible
    "sil" there; without the comma it reads the date cleanly. Remove once a release
    fixes it (issue #1)."""
    return _DATE_COMMA.sub(r"\1", text)


def close(piece: str) -> str:
    """`piece` ending in sentence-final punctuation, so a speech model closes the phrase:
    a trailing clause mark becomes a full stop, and a piece with neither gets one."""
    if _FINAL.search(piece):
        return piece
    trailing = _TRAILING_CLAUSE.search(piece)
    if trailing is None:
        return piece + "."
    return piece[: trailing.start()] + "." + trailing.group(1)


def _one_word(sentence: str) -> bool:
    """Whether `sentence` is one word, as an abbreviation (`Prof.`) is: no space in it, and
    not a sentence of a language written without spaces."""
    return " " not in sentence and _FULL_WIDTH_FINAL.search(sentence) is None


def _split_after(
    pattern: re.Pattern[str], text: str, *, unless_lowercase: bool = False
) -> list[str]:
    """`text` cut at each whitespace run `pattern` marks; the punctuation stays left. With
    `unless_lowercase`, a mark followed by whitespace and a lowercase letter, as an
    abbreviation is (`e.g. here`, `z. B. überall`), is no cut, and nor is the full stop
    of a title, street or month (`Dr. Lee`, `St. Louis`, `Oct. 8`)."""
    cut, start = [], 0
    for match in pattern.finditer(text):
        gap, after = match.group(1), text[match.end(1) : match.end(1) + 1]
        before = text[max(0, match.start(1) - _NO_BREAK_REACH) : match.start(1)]
        if unless_lowercase and gap and (after.islower() or _NO_BREAK_AFTER.search(before)):
            continue
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
