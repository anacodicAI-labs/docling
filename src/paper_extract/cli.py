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
        "--formulas",
        action="store_true",
        help="Enable formula enrichment VLM (large model download; off by default)",
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
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


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
            formulas=args.formulas,
            images_scale=args.images_scale,
            write_element_tree=not args.no_element_tree,
            write_assets=not args.no_assets,
            write_links=not args.no_links,
        )
    except Exception as exc:
        logging.error("%s", exc)
        return 1

    print(f"Docling JSON : {result.docling_json}")
    print(f"Artifacts    : {result.artifacts_dir}")
    print(f"Assets       : {result.assets_dir}")
    print(f"Links        : {result.links_json}")
    print(f"Element tree : {result.element_tree_txt}")
    print(f"Manifest     : {result.manifest_json}")
    print(f"Counts       : {result.manifest.counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
