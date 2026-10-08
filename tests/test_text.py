import pytest

from speak_core.text import close, normalize, pieces, sentences


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
    assert sentences("Dr. Smith is here. Yes.") == ["Dr. Smith is here.", "Yes."]


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
        ("Dr. Smith arrived late.", ["Dr. Smith arrived late."]),
        ("Darker, e.g. here, is fine.", ["Darker, e.g. here, is fine."]),
        ("Yes. That is right.", ["Yes. That is right."]),
        ("That is right. Yes.", ["That is right.", "Yes."]),
    ],
)
def test_a_one_word_sentence_goes_with_the_sentence_after_it(text, expected):
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


@pytest.mark.parametrize(
    ("piece", "expected"),
    [
        ("a whole sentence.", "a whole sentence."),
        ("a question?", "a question?"),
        ('a quote."', 'a quote."'),
        ("a clause,", "a clause."),
        ("a clause \u2014", "a clause."),
        ("no punctuation", "no punctuation."),
    ],
)
def test_close_ends_a_piece_in_sentence_final_punctuation(piece, expected):
    assert close(piece) == expected
