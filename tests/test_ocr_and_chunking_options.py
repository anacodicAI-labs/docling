"""Tests for the OCR-option resolution and chunk-overlap logic added for the
OCR-control and chunking gaps. These pin down two easy-to-regress behaviours:
`auto` silently ignoring language hints, and RapidOCR's limited language set."""

from __future__ import annotations

import pytest

from paper_extract.chunking import _tail_by_tokens
from paper_extract.converter import _resolve_ocr_options


def test_ocr_options_require_ocr_flag() -> None:
    with pytest.raises(ValueError, match="without --ocr"):
        _resolve_ocr_options(ocr=False, ocr_engine="easyocr", ocr_full_page=False, ocr_lang=None)
    with pytest.raises(ValueError, match="without --ocr"):
        _resolve_ocr_options(ocr=False, ocr_engine="auto", ocr_full_page=True, ocr_lang=None)
    with pytest.raises(ValueError, match="without --ocr"):
        _resolve_ocr_options(ocr=False, ocr_engine="auto", ocr_full_page=False, ocr_lang=["en"])


def test_ocr_off_is_a_pure_noop() -> None:
    engine, options = _resolve_ocr_options(ocr=False, ocr_engine="auto", ocr_full_page=False, ocr_lang=None)
    assert engine == "auto"
    assert options is None


def test_auto_engine_with_lang_upgrades_to_easyocr() -> None:
    engine, options = _resolve_ocr_options(ocr=True, ocr_engine="auto", ocr_full_page=False, ocr_lang=["en", "hi"])
    assert engine == "easyocr"
    assert options.lang == ["en", "hi"]


def test_rapidocr_rejects_iso_codes() -> None:
    with pytest.raises(ValueError, match="chinese.*english.*latin"):
        _resolve_ocr_options(ocr=True, ocr_engine="rapidocr", ocr_full_page=False, ocr_lang=["hi"])


def test_rapidocr_accepts_its_own_language_families() -> None:
    engine, options = _resolve_ocr_options(ocr=True, ocr_engine="rapidocr", ocr_full_page=True, ocr_lang=["english"])
    assert engine == "rapidocr"
    assert options.lang == ["english"]
    assert options.force_full_page_ocr is True


class _FakeTokenizer:
    """~1 token per word, so overlap sizing is easy to assert on."""

    def count_tokens(self, text: str) -> int:
        return len(text.split())


def test_tail_by_tokens_takes_minimal_suffix() -> None:
    tokenizer = _FakeTokenizer()
    text = "the quick brown fox jumps over the lazy dog"
    assert _tail_by_tokens(text, tokenizer, 3) == "the lazy dog"


def test_tail_by_tokens_zero_overlap_is_empty() -> None:
    tokenizer = _FakeTokenizer()
    assert _tail_by_tokens("some text here", tokenizer, 0) == ""


def test_tail_by_tokens_overlap_larger_than_text_returns_whole_text() -> None:
    tokenizer = _FakeTokenizer()
    assert _tail_by_tokens("two words", tokenizer, 10) == "two words"
