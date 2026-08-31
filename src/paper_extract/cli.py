"""CLI for paper PDF extraction."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from paper_extract.converter import extract_paper_pdf


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract an academic PDF to structured Docling JSON.",
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Path to the source PDF",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for outputs (default: same folder as the PDF)",
    )
    parser.add_argument(
        "--layout",
        choices=["flat", "folder"],
        default="flat",
        help="Output layout: flat files in output-dir, or folder per paper (default: flat)",
    )
    parser.add_argument(
        "--copy-source",
        action="store_true",
        help="Copy source PDF into the paper output directory (folder layout)",
    )
    parser.add_argument(
        "--image-mode",
        choices=["referenced", "embedded", "placeholder"],
        default="referenced",
        help="How images are stored in JSON (default: referenced)",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR for scanned pages (slower; off by default for born-digital PDFs)",
    )
    parser.add_argument(
        "--ocr-engine",
        choices=["auto", "easyocr", "rapidocr"],
        default="auto",
        help=(
            "OCR engine (requires --ocr; default: auto). RapidOCR only ships "
            "english/chinese/latin language models — for Devanagari or other "
            "scripts use easyocr."
        ),
    )
    parser.add_argument(
        "--ocr-full-page",
        action="store_true",
        help=(
            "Run OCR on the whole page instead of only regions the layout model "
            "flags as images (requires --ocr). Off by default a page can come back "
            "partially transcribed with no error; turn this on for scanned/photographed pages."
        ),
    )
    parser.add_argument(
        "--ocr-lang",
        action="append",
        default=None,
        metavar="LANG[,LANG...]",
        help=(
            "OCR language hints (requires --ocr and an explicit --ocr-engine; "
            "ignored by auto). Comma list or repeat the flag, e.g. "
            "--ocr-lang en,hi. ISO 639-1 codes for easyocr; rapidocr accepts only "
            "english/chinese/latin."
        ),
    )
    parser.add_argument(
        "--formulas",
        action="store_true",
        help="Enable formula enrichment VLM (large model download; off by default)",
    )
    parser.add_argument(
        "--code-enrichment",
        action="store_true",
        help="Recognise code blocks as code in the element tree (off by default)",
    )
    parser.add_argument(
        "--picture-classification",
        action="store_true",
        help="Classify picture/figure type, e.g. chart vs. photo (off by default)",
    )
    parser.add_argument(
        "--picture-description",
        action="store_true",
        help=(
            "Caption figures with a vision-language model (off by default). "
            "SLOW: runs a VLM pass over every picture; budget extra time on large runs."
        ),
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda", "mps"],
        default="auto",
        help="Accelerator device for layout/table/OCR models (default: auto)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="CPU thread count for model inference (default: leave to docling)",
    )
    parser.add_argument(
        "--table-mode",
        choices=["accurate", "fast"],
        default="accurate",
        help=(
            "TableFormer mode (default: accurate, already docling's default). "
            "fast trades accuracy for speed — useful to sanity-check layout "
            "across hundreds of documents before a full run."
        ),
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "both"],
        default="json",
        dest="output_format",
        help="Output format (default: json). markdown/both also write {stem}.md",
    )
    parser.add_argument(
        "--images-scale",
        type=float,
        default=2.0,
        help="Render scale for page/figure images (default: 2.0 ≈ 144 DPI)",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="Skip exporting cropped table/figure PNGs to .assets/",
    )
    parser.add_argument(
        "--no-links",
        action="store_true",
        help="Skip PyMuPDF hyperlink sidecar (.links.json)",
    )
    parser.add_argument(
        "--no-element-tree",
        action="store_true",
        help="Skip human-readable element tree (.elements.txt)",
    )
    parser.add_argument(
        "--chunk",
        action="store_true",
        help=(
            "Write a token-sized chunk sidecar ({stem}.chunks.jsonl) via docling's "
            "HybridChunker. Off by default; never alters the Docling JSON."
        ),
    )
    parser.add_argument(
        "--chunk-tokenizer",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="HuggingFace tokenizer used to size chunks (default: sentence-transformers/all-MiniLM-L6-v2)",
    )
    parser.add_argument(
        "--chunk-max-tokens",
        type=int,
        default=None,
        help="Max tokens per chunk (default: resolved from the tokenizer's own config)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=0,
        help="Tokens of the previous chunk to prepend to each chunk (default: 0, no overlap)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def _parse_ocr_lang(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    langs: list[str] = []
    for value in values:
        langs.extend(part.strip() for part in value.split(",") if part.strip())
    return langs or None


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        result = extract_paper_pdf(
            args.pdf,
            output_dir=args.output_dir,
            layout=args.layout,
            copy_source_pdf=args.copy_source,
            image_mode=args.image_mode,
            ocr=args.ocr,
            ocr_engine=args.ocr_engine,
            ocr_full_page=args.ocr_full_page,
            ocr_lang=_parse_ocr_lang(args.ocr_lang),
            formulas=args.formulas,
            code_enrichment=args.code_enrichment,
            picture_classification=args.picture_classification,
            picture_description=args.picture_description,
            device=args.device,
            threads=args.threads,
            table_mode=args.table_mode,
            output_format=args.output_format,
            images_scale=args.images_scale,
            write_element_tree=not args.no_element_tree,
            write_assets=not args.no_assets,
            write_links=not args.no_links,
            chunk=args.chunk,
            chunk_tokenizer=args.chunk_tokenizer,
            chunk_max_tokens=args.chunk_max_tokens,
            chunk_overlap=args.chunk_overlap,
        )
    except Exception as exc:
        logging.error("%s", exc)
        return 1

    print(f"Docling JSON : {result.docling_json}")
    print(f"Artifacts    : {result.artifacts_dir}")
    print(f"Assets       : {result.assets_dir}")
    print(f"Links        : {result.links_json}")
    print(f"Element tree : {result.element_tree_txt}")
    if result.markdown_md:
        print(f"Markdown     : {result.markdown_md}")
    if result.chunks_jsonl:
        print(f"Chunks       : {result.chunks_jsonl} ({result.manifest.chunking['chunk_count']} chunks)")
    print(f"Manifest     : {result.manifest_json}")
    print(f"Counts       : {result.manifest.counts}")
    print(f"Conversion   : {result.manifest.conversion_seconds}s (device={args.device})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
