from app.infrastructure.parsers.chunking import chunk_chapter_text, split_sentences


def test_split_sentences_basic() -> None:
    text = "First sentence. Second sentence! Third one? Fourth."
    assert split_sentences(text) == [
        "First sentence.",
        "Second sentence!",
        "Third one?",
        "Fourth.",
    ]


def test_split_sentences_empty() -> None:
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_asymmetric_first_chunk_is_a_single_sentence() -> None:
    text = " ".join(f"Sentence number {i}." for i in range(10))
    chunks = chunk_chapter_text("chap-1", text)

    assert chunks[0].text == "Sentence number 0."
    assert chunks[0].index == 0
    # Later chunks group multiple sentences (plan.md: biggest single win on
    # perceived latency comes from getting the first chunk out fast).
    assert len(chunks) > 1
    assert chunks[1].text.count(".") > 1


def test_chunk_ids_are_unique() -> None:
    text = " ".join(f"Sentence number {i}." for i in range(10))
    chunks = chunk_chapter_text("chap-1", text)
    assert len({c.id for c in chunks}) == len(chunks)


def test_chunk_chapter_text_empty_returns_no_chunks() -> None:
    assert chunk_chapter_text("chap-1", "") == []
