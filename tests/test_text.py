import pytest

from speak_core.text import close, normalize, pieces, sentences, without_date_commas


def test_collapses_all_whitespace_to_single_spaces():
    assert normalize("  hello\n\tthere   world  ") == "hello there world"


def test_rejects_text_that_is_only_whitespace():
    with pytest.raises(ValueError, match="nothing to speak"):
        normalize("   \n\t ")


def test_rejects_none():
    with pytest.raises(ValueError, match="nothing to speak"):
        normalize(None)


def test_never_cuts_a_long_text():
    text = "word " * 2000
    assert normalize(text) == text.strip()


def test_sentences_are_whole_however_long():
    long = "Clause, " * 100 + "and the end."
    assert sentences(f"Short one. {long} Another!") == ["Short one.", long, "Another!"]


def test_a_one_word_sentence_is_spoken_with_the_next():
    assert sentences("Prof. Smith is here. Yes.") == ["Prof. Smith is here.", "Yes."]


def test_one_word_is_one_sentence():
    assert sentences("Hello") == ["Hello"]


def test_every_sentence_is_a_piece_of_its_own_however_much_room_is_left():
    assert pieces("One two. Three four! Five six?", max_chars=1000) == [
        "One two.",
        "Three four!",
        "Five six?",
    ]


def test_a_long_sentences_clauses_are_packed_but_never_with_the_next_sentence():
    text = "alpha beta, gamma delta, epsilon zeta, eta theta. Next one here."
    assert pieces(text, max_chars=30) == [
        "alpha beta, gamma delta,",
        "epsilon zeta, eta theta.",
        "Next one here.",
    ]


def test_a_clause_longer_than_the_limit_is_cut_at_its_words():
    assert pieces("one two three four five six", max_chars=10) == [
        "one two",
        "three four",
        "five six",
    ]


def test_a_word_longer_than_the_limit_is_cut_where_the_limit_falls():
    assert pieces("supercalifragilistic", max_chars=8) == ["supercal", "ifragili", "stic"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Prof. Smith arrived late.", ["Prof. Smith arrived late."]),
        ("Darker, e.g. here, is fine.", ["Darker, e.g. here, is fine."]),
        ("Yes. That is right.", ["Yes. That is right."]),
        ("That is right. Yes.", ["That is right.", "Yes."]),
    ],
)
def test_a_one_word_sentence_goes_with_the_sentence_after_it(text, expected):
    assert pieces(text, max_chars=100) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello world. !!!", ["Hello world. !!!"]),
        ("Hello world. Yes.", ["Hello world.", "Yes."]),
    ],
)
def test_a_wordless_last_sentence_goes_with_the_one_before_it(text, expected):
    assert pieces(text, max_chars=100) == expected


def test_a_one_word_sentence_stands_alone_when_the_next_would_not_fit_with_it():
    assert pieces("Yes. That is quite right.", max_chars=20) == ["Yes.", "That is quite right."]


def test_no_character_but_the_whitespace_at_a_cut_is_lost():
    text = "First, a clause; then: another \u2014 and more. Second sentence here! Done?"
    for limit in (5, 12, 30, 1000):
        cut = pieces(text, max_chars=limit)
        assert all(len(piece) <= limit for piece in cut)
        assert "".join(cut).replace(" ", "") == text.replace(" ", "")


def test_nothing_is_no_pieces():
    assert pieces("", max_chars=10) == []


def test_a_limit_under_one_is_refused():
    with pytest.raises(ValueError, match="max_chars"):
        pieces("word", max_chars=0)


def test_an_abbreviation_before_a_lowercase_letter_of_any_alphabet_ends_no_sentence():
    text = "Il faut, p. ex. \u00e9videmment, le faire, e.g. \u00e9clair."
    assert sentences(text) == [text]


@pytest.mark.parametrize(
    "text",
    [
        "We met Dr. Lee today.",
        "Turn left on Nobel Dr. and park.",
        "Ask Mr. Smith and Mrs. Jones on St. Louis Ave.",
        "It opened in Oct. Nobody came.",
        "Ask (Dr. Lee) now.",
    ],
)
def test_a_title_street_or_month_abbreviation_ends_no_sentence(text):
    assert sentences(text) == [text]


def test_a_word_that_only_ends_like_an_abbreviation_still_ends_a_sentence():
    assert sentences("Talk to Mr. Hyde. Then sing a dr. Next is Dr. Oct. Done.") == [
        "Talk to Mr. Hyde.",
        "Then sing a dr.",
        "Next is Dr. Oct. Done.",
    ]
    assert sentences("Ask the DrDr. Then go.") == ["Ask the DrDr.", "Then go."]


def test_a_clause_mark_inside_a_closing_quote_still_cuts():
    text = 'She said, "Wait," and then she left the room without another word.'
    assert pieces(text, max_chars=30) == [
        'She said, "Wait,"',
        "and then she left the room",
        "without another word.",
    ]


# Chinese, written without spaces: "this is the first sentence." and "the second!"
FIRST, SECOND = "\u8fd9\u662f\u7b2c\u4e00\u53e5\u3002", "\u7b2c\u4e8c\u53e5\uff01"
CLAUSE, END = "\u4e00\u4e8c\u4e09\u56db\uff0c", "\u5b8c\u3002"


def test_full_width_punctuation_ends_a_sentence_without_a_space_after_it():
    assert sentences(FIRST + SECOND) == [FIRST, SECOND]


def test_full_width_commas_cut_a_long_sentence_without_a_space_after_them():
    assert pieces(CLAUSE * 4 + END, max_chars=10) == [CLAUSE, CLAUSE, CLAUSE, f"{CLAUSE} {END}"]


@pytest.mark.parametrize(
    ("piece", "expected"),
    [
        ("a whole sentence.", "a whole sentence."),
        ("a question?", "a question?"),
        ('a quote."', 'a quote."'),
        ("a clause,", "a clause."),
        ("a clause \u2014", "a clause."),
        ("no punctuation", "no punctuation."),
        ('a "quoted clause,"', 'a "quoted clause."'),
        (CLAUSE, CLAUSE[:-1] + "."),
        (FIRST, FIRST),
    ],
)
def test_close_ends_a_piece_in_sentence_final_punctuation(piece, expected):
    assert close(piece) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It happened on May 3, 1999.", "It happened on May 3 1999."),
        ("The launch is on Oct. 8, 2026, at noon.", "The launch is on Oct. 8 2026, at noon."),
        ("On Monday, May 3rd, 1999 it rained.", "On Monday, May 3rd 1999 it rained."),
        ("Due September 30, 1999 and Sept. 1, 2000.", "Due September 30 1999 and Sept. 1 2000."),
        ("It happened in May, 1999.", "It happened in May 1999."),
    ],
)
def test_the_comma_between_a_month_or_day_and_its_year_is_dropped(text, expected):
    assert without_date_commas(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We may, 1999 times over, be wrong.",
        "Room 3, 1999 guests.",
        "On May 3, 99 people came.",
        "On May 3, 19999 people came.",
        "In Mayfair, 1999 was quiet.",
        "Monday, May 3 1999.",
    ],
)
def test_other_commas_before_a_number_are_kept(text):
    assert without_date_commas(text) == text
