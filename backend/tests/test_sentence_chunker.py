from backend.app.services.sentence_chunker import SentenceChunker


def test_emits_complete_sentences_as_they_arrive():
    c = SentenceChunker()
    assert c.feed("Hello") == []
    assert c.feed(" there.") == []  # boundary needs trailing whitespace/newline
    out = c.feed(" How are you? ")
    assert out == ["Hello there.", "How are you?"]


def test_flush_returns_remainder():
    c = SentenceChunker()
    c.feed("Just a fragment without end")
    assert c.flush() == "Just a fragment without end"
    assert c.flush() == ""


def test_newline_is_a_boundary():
    c = SentenceChunker()
    out = c.feed("Line one\nLine two")
    assert out == ["Line one"]
    assert c.flush() == "Line two"


def test_streaming_token_by_token():
    c = SentenceChunker()
    collected: list[str] = []
    for tok in ["The", " quick", " brown", " fox.", " Then", " more.", " end"]:
        collected.extend(c.feed(tok))
    assert collected == ["The quick brown fox.", "Then more."]
    assert c.flush() == "end"
