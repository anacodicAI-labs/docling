"""Convert academic PDFs to DoclingDocument JSON with maximum structure."""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from paper_extract.layout import (
    OutputLayout,
    clear_partial_outputs,
    is_extraction_complete,
    resolve_paper_output_dir,
)
from paper_extract.links import write_links_sidecar
from paper_extract.manifest import ExtractionManifest

log = logging.getLogger(__name__)

ImageMode = Literal["referenced", "embedded", "placeholder"]


@dataclass
class ExtractionResult:
    pdf_path: Path
    output_dir: Path
    docling_json: Path
    artifacts_dir: Path
    links_json: Path
    assets_dir: Path
    element_tree_txt: Path
    manifest_json: Path
    manifest: ExtractionManifest


def _ensure_model_cache() -> None:
    """Use a project-local HF cache when the user has not set one."""
    if os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE"):
        return
    cache_dir = Path(__file__).resolve().parents[2] / ".cache" / "huggingface"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache_dir)


def _build_converter(*, ocr: bool, images_scale: float, formulas: bool):
    _ensure_model_cache()
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions(
        do_ocr=ocr,
        do_table_structure=True,
        generate_page_images=True,
        generate_picture_images=True,
        images_scale=images_scale,
    )
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.ACCURATE,
    )

    if formulas and hasattr(pipeline_options, "do_formula_enrichment"):
        pipeline_options.do_formula_enrichment = True

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )


def _resolve_image_mode(mode: ImageMode):
    from docling_core.types.doc import ImageRefMode

    return {
        "referenced": ImageRefMode.REFERENCED,
        "embedded": ImageRefMode.EMBEDDED,
        "placeholder": ImageRefMode.PLACEHOLDER,
    }[mode]


def _pdf_metadata(pdf_path: Path) -> dict[str, Any]:
    import fitz

    doc = fitz.open(str(pdf_path))
    meta = dict(doc.metadata)
    meta["page_count"] = doc.page_count
    doc.close()
    return meta


def _export_element_tree(document, output_path: Path) -> None:
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        document.print_element_tree()
    output_path.write_text(buffer.getvalue(), encoding="utf-8")


def _export_table_and_figure_assets(document, assets_dir: Path, stem: str) -> dict[str, int]:
    """Save cropped table/figure PNGs with predictable names."""
    from docling_core.types.doc import PictureItem, TableItem

    assets_dir.mkdir(parents=True, exist_ok=True)
    table_count = 0
    picture_count = 0

    for element, _level in document.iterate_items():
        if isinstance(element, TableItem):
            image = element.get_image(document)
            if image is None:
                continue
            table_count += 1
            out = assets_dir / f"{stem}-table-{table_count:03d}.png"
            image.save(out, "PNG")

        elif isinstance(element, PictureItem):
            image = element.get_image(document)
            if image is None:
                continue
            picture_count += 1
            out = assets_dir / f"{stem}-figure-{picture_count:03d}.png"
            image.save(out, "PNG")

    return {"tables_exported": table_count, "figures_exported": picture_count}


def extract_paper_pdf(
    pdf_path: Path,
    *,
    output_dir: Path | None = None,
    layout: OutputLayout = "flat",
    copy_source_pdf: bool = False,
    skip_if_complete: bool = False,
    image_mode: ImageMode = "referenced",
    ocr: bool = False,
    formulas: bool = False,
    images_scale: float = 2.0,
    write_element_tree: bool = True,
    write_assets: bool = True,
    write_links: bool = True,
) -> ExtractionResult:
    """
    Extract a paper PDF to structured Docling JSON and companion files.

    Outputs (next to the PDF by default):
      - {stem}.docling.json       — full DoclingDocument (texts, tables, pictures, prov/bbox)
      - {stem}_artifacts/         — figure images referenced from JSON (when image_mode=referenced)
      - {stem}.links.json         — PDF hyperlinks (DOIs, URLs) with page + bbox
      - {stem}.assets/            — cropped table/figure PNGs with stable names
      - {stem}.elements.txt       — human-readable element tree (reading order)
      - {stem}.manifest.json      — run summary and file paths
    """
    pdf_path = pdf_path.expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {pdf_path}")

    stem = pdf_path.stem
    base_output_dir = (output_dir or pdf_path.parent).expanduser().resolve()
    base_output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = resolve_paper_output_dir(base_output_dir, stem, layout)
    output_dir.mkdir(parents=True, exist_ok=True)

    if skip_if_complete and is_extraction_complete(output_dir, stem):
        log.info("Skipping %s — manifest checkpoint exists", stem)
        manifest_json = output_dir / f"{stem}.manifest.json"
        manifest = ExtractionManifest(**json.loads(manifest_json.read_text(encoding="utf-8")))
        return ExtractionResult(
            pdf_path=pdf_path,
            output_dir=output_dir,
            docling_json=Path(manifest.docling_json),
            artifacts_dir=Path(manifest.artifacts_dir),
            links_json=Path(manifest.links_json),
            assets_dir=Path(manifest.assets_dir),
            element_tree_txt=Path(manifest.element_tree_txt),
            manifest_json=manifest_json,
            manifest=manifest,
        )

    clear_partial_outputs(output_dir, stem)

    if copy_source_pdf:
        import shutil

        shutil.copy2(pdf_path, output_dir / f"{stem}.pdf")

    docling_json = output_dir / f"{stem}.docling.json"
    artifacts_dir = output_dir / f"{stem}_artifacts"
    links_json = output_dir / f"{stem}.links.json"
    assets_dir = output_dir / f"{stem}.assets"
    element_tree_txt = output_dir / f"{stem}.elements.txt"
    manifest_json = output_dir / f"{stem}.manifest.json"

    log.info("Converting %s", pdf_path)
    converter = _build_converter(ocr=ocr, images_scale=images_scale, formulas=formulas)
    result = converter.convert(str(pdf_path))
    document = result.document

    ref_mode = _resolve_image_mode(image_mode)
    document.save_as_json(
        docling_json,
        artifacts_dir=artifacts_dir,
        image_mode=ref_mode,
        indent=2,
    )
    log.info("Wrote Docling JSON: %s", docling_json)

    asset_counts: dict[str, int] = {}
    if write_assets:
        asset_counts = _export_table_and_figure_assets(document, assets_dir, stem)
        log.info(
            "Exported assets: %s tables, %s figures",
            asset_counts.get("tables_exported", 0),
            asset_counts.get("figures_exported", 0),
        )

    link_count = 0
    if write_links:
        links = write_links_sidecar(pdf_path, links_json)
        link_count = len(links)
        log.info("Wrote %s hyperlinks: %s", link_count, links_json)

    if write_element_tree:
        _export_element_tree(document, element_tree_txt)
        log.info("Wrote element tree: %s", element_tree_txt)

    counts = {
        "texts": len(document.texts),
        "tables": len(document.tables),
        "pictures": len(document.pictures),
        "pages": len(document.pages) if hasattr(document, "pages") else 0,
        "hyperlinks": link_count,
        **asset_counts,
    }

    manifest = ExtractionManifest(
        source_pdf=str(pdf_path),
        stem=stem,
        output_dir=str(output_dir),
        docling_json=str(docling_json),
        artifacts_dir=str(artifacts_dir),
        links_json=str(links_json),
        assets_dir=str(assets_dir),
        element_tree_txt=str(element_tree_txt),
        image_mode=image_mode,
        counts=counts,
        pdf_metadata=_pdf_metadata(pdf_path),
    )
    manifest.write(manifest_json)

    return ExtractionResult(
        pdf_path=pdf_path,
        output_dir=output_dir,
        docling_json=docling_json,
        artifacts_dir=artifacts_dir,
        links_json=links_json,
        assets_dir=assets_dir,
        element_tree_txt=element_tree_txt,
        manifest_json=manifest_json,
        manifest=manifest,
    )
