"""Optional token-aware chunking sidecar, built on Docling's HybridChunker.

Off by default. This repo is deliberately extraction-only (see README); chunking
here exists so every consumer shares one implementation of the fiddly parts
(token-sized chunks, table headers surviving a chunk split) instead of each
consumer writing its own and drifting. It writes a separate sidecar file and
never touches the Docling JSON.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"


def _item_label(item: Any) -> str:
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "").lower()


def _chunk_pages(doc_items: list[Any]) -> list[int]:
    pages: set[int] = set()
    for item in doc_items or []:
        for prov in getattr(item, "prov", None) or []:
            try:
                pages.add(int(prov.page_no))
            except (TypeError, ValueError):
                pass
    return sorted(pages)


def _section_path(meta: Any) -> str:
    headings = getattr(meta, "headings", None) or []
    parts = [str(h).strip() for h in headings if str(h).strip()]
    return " > ".join(parts)


def _tail_by_tokens(text: str, tokenizer: Any, min_tokens: int) -> str:
    """The shortest word-suffix of *text* whose token count is >= *min_tokens*.

    HybridChunker has no native overlap between chunks, so this reconstructs it:
    walk the previous chunk's words from the end, growing the suffix, and stop as
    soon as the tokenizer (the same one sizing chunks) says it has enough. Word
    granularity, not character, so the prepended text starts on a word boundary.
    """
    words = text.split()
    if not words or min_tokens <= 0:
        return ""
    for k in range(1, len(words) + 1):
        candidate = " ".join(words[-k:])
        if tokenizer.count_tokens(candidate) >= min_tokens:
            return candidate
    return " ".join(words)


def build_hybrid_chunker(*, tokenizer_name: str, max_tokens: int | None):
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

    try:
        tokenizer = HuggingFaceTokenizer.from_pretrained(
            model_name=tokenizer_name, max_tokens=max_tokens
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"Could not resolve max_tokens for tokenizer {tokenizer_name!r} "
            "(it has no sentence_bert_config.json). Pass --chunk-max-tokens explicitly."
        ) from exc

    return HybridChunker(
        tokenizer=tokenizer,
        repeat_table_header=True,
        merge_peers=True,
    )


def chunk_document(
    document: Any,
    *,
    tokenizer_name: str = DEFAULT_TOKENIZER,
    max_tokens: int | None = None,
    overlap: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Chunk *document* and return (records, config).

    ``config`` (tokenizer, max_tokens, overlap) is what makes the sidecar
    reproducible: a chunk store whose token budget is unrecorded can't be
    compared against another one.
    """
    chunker = build_hybrid_chunker(tokenizer_name=tokenizer_name, max_tokens=max_tokens)
    resolved_max_tokens = chunker.max_tokens

    raw_chunks = list(chunker.chunk(document))
    raw_texts = [str(getattr(ch, "text", "") or "") for ch in raw_chunks]

    records: list[dict[str, Any]] = []
    for idx, ch in enumerate(raw_chunks):
        meta = getattr(ch, "meta", None)
        doc_items = list(getattr(meta, "doc_items", None) or [])
        labels = {_item_label(it) for it in doc_items}

        text = raw_texts[idx]
        if overlap > 0 and idx > 0:
            prefix = _tail_by_tokens(raw_texts[idx - 1], chunker.tokenizer, overlap)
            if prefix:
                text = f"{prefix}\n\n{text}"

        records.append(
            {
                "chunk_index": idx,
                "text": text,
                "token_count": chunker.tokenizer.count_tokens(text),
                "section_path": _section_path(meta) if meta else "",
                "pages": _chunk_pages(doc_items),
                "is_table": "table" in labels,
                "is_figure": bool(labels & {"picture", "figure"}),
            }
        )

    config = {
        "tokenizer": tokenizer_name,
        "max_tokens": resolved_max_tokens,
        "overlap": overlap,
        "chunk_count": len(records),
    }
    return records, config


def write_chunks_sidecar(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
