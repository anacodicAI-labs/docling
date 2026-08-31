"""Convert academic PDFs to DoclingDocument JSON with maximum structure."""

from __future__ import annotations

import io
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from paper_extract.chunking import DEFAULT_TOKENIZER, chunk_document, write_chunks_sidecar
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
OcrEngine = Literal["auto", "easyocr", "rapidocr"]
Device = Literal["auto", "cpu", "cuda", "mps"]
TableMode = Literal["accurate", "fast"]
OutputFormat = Literal["json", "markdown", "both"]

# RapidOCR (this docling version) only ships model bundles for these language
# families, selected by name rather than ISO code. Devanagari and most other
# scripts aren't covered by any of them — use --ocr-engine easyocr instead.
_RAPIDOCR_LANG_FAMILIES = {"english", "chinese", "latin"}


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
    markdown_md: Path | None = None
    chunks_jsonl: Path | None = None


def _ensure_model_cache() -> None:
    """Use a project-local HF cache when the user has not set one."""
    if os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE"):
        return
    cache_dir = Path(__file__).resolve().parents[2] / ".cache" / "huggingface"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache_dir)


def _resolve_ocr_options(
    *,
    ocr: bool,
    ocr_engine: OcrEngine,
    ocr_full_page: bool,
    ocr_lang: list[str] | None,
) -> tuple[str, Any | None]:
    """Return (resolved_engine, OcrOptions | None).

    Raises if full-page mode, an explicit engine, or a language hint is passed
    without --ocr: silently ignoring them is the exact "partial transcription,
    no error" failure this exists to prevent.
    """
    if not ocr:
        if ocr_engine != "auto" or ocr_full_page or ocr_lang:
            raise ValueError(
                "--ocr-engine / --ocr-full-page / --ocr-lang have no effect "
                "without --ocr (OCR is off by default)."
            )
        return ocr_engine, None

    import importlib.util

    from docling.datamodel.pipeline_options import EasyOcrOptions, OcrAutoOptions, RapidOcrOptions

    resolved_engine = ocr_engine
    if ocr_lang and resolved_engine == "auto":
        # OcrAutoOptions defers language entirely to whichever engine it picks
        # at runtime and ignores `lang` — passing lang hints with the default
        # engine is a silent no-op in docling itself.
        resolved_engine = "easyocr"
        log.warning(
            "--ocr-lang has no effect with --ocr-engine auto (docling ignores "
            "language hints in auto mode); using --ocr-engine easyocr instead "
            "so %s take effect",
            ocr_lang,
        )

    if resolved_engine == "auto":
        return resolved_engine, OcrAutoOptions(force_full_page_ocr=ocr_full_page)

    if resolved_engine == "easyocr":
        if importlib.util.find_spec("easyocr") is None:
            raise RuntimeError("--ocr-engine easyocr requires the `easyocr` package: pip install easyocr")
        kwargs: dict[str, Any] = {"force_full_page_ocr": ocr_full_page}
        if ocr_lang:
            kwargs["lang"] = ocr_lang
        return resolved_engine, EasyOcrOptions(**kwargs)

    if resolved_engine == "rapidocr":
        if importlib.util.find_spec("rapidocr") is None:
            raise RuntimeError("--ocr-engine rapidocr requires the `rapidocr` package: pip install rapidocr onnxruntime")
        langs = ocr_lang or RapidOcrOptions.model_fields["lang"].default
        bad = [l for l in langs if l not in _RAPIDOCR_LANG_FAMILIES]
        if bad:
            raise ValueError(
                f"--ocr-engine rapidocr only supports language families "
                f"{sorted(_RAPIDOCR_LANG_FAMILIES)}, got {bad!r}. RapidOCR has no "
                "Devanagari model in this docling version; use --ocr-engine easyocr."
            )
        return resolved_engine, RapidOcrOptions(lang=langs, force_full_page_ocr=ocr_full_page)

    raise ValueError(f"Unknown --ocr-engine: {ocr_engine!r}")


def _resolve_accelerator_options(*, device: Device, threads: int | None) -> Any:
    from docling.datamodel.pipeline_options import AcceleratorDevice, AcceleratorOptions

    device_enum = {
        "auto": AcceleratorDevice.AUTO,
        "cpu": AcceleratorDevice.CPU,
        "cuda": AcceleratorDevice.CUDA,
        "mps": AcceleratorDevice.MPS,
    }[device]
    kwargs: dict[str, Any] = {"device": device_enum}
    if threads is not None:
        kwargs["num_threads"] = threads
    return AcceleratorOptions(**kwargs)


def _build_converter(
    *,
    ocr: bool,
    ocr_engine: OcrEngine,
    ocr_full_page: bool,
    ocr_lang: list[str] | None,
    images_scale: float,
    formulas: bool,
    code_enrichment: bool,
    picture_classification: bool,
    picture_description: bool,
    device: Device,
    threads: int | None,
    table_mode: TableMode,
) -> tuple[Any, str]:
    """Build the DocumentConverter. Returns (converter, resolved_ocr_engine)."""
    # Resolved before docling's own (slow: torch/transformers) imports below, so a
    # bad flag combination (e.g. --ocr-lang without --ocr) fails in milliseconds
    # instead of after paying the import cost.
    resolved_ocr_engine, ocr_options = _resolve_ocr_options(
        ocr=ocr, ocr_engine=ocr_engine, ocr_full_page=ocr_full_page, ocr_lang=ocr_lang
    )

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
        do_code_enrichment=code_enrichment,
        do_picture_classification=picture_classification,
        do_picture_description=picture_description,
    )
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.ACCURATE if table_mode == "accurate" else TableFormerMode.FAST,
    )
    pipeline_options.accelerator_options = _resolve_accelerator_options(device=device, threads=threads)

    if ocr_options is not None:
        pipeline_options.ocr_options = ocr_options

    if formulas and hasattr(pipeline_options, "do_formula_enrichment"):
        pipeline_options.do_formula_enrichment = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    return converter, resolved_ocr_engine


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
    ocr_engine: OcrEngine = "auto",
    ocr_full_page: bool = False,
    ocr_lang: list[str] | None = None,
    formulas: bool = False,
    code_enrichment: bool = False,
    picture_classification: bool = False,
    picture_description: bool = False,
    device: Device = "auto",
    threads: int | None = None,
    table_mode: TableMode = "accurate",
    output_format: OutputFormat = "json",
    images_scale: float = 2.0,
    write_element_tree: bool = True,
    write_assets: bool = True,
    write_links: bool = True,
    chunk: bool = False,
    chunk_tokenizer: str = DEFAULT_TOKENIZER,
    chunk_max_tokens: int | None = None,
    chunk_overlap: int = 0,
) -> ExtractionResult:
    """
    Extract a paper PDF to structured Docling JSON and companion files.

    Outputs (next to the PDF by default):
      - {stem}.docling.json       — full DoclingDocument (texts, tables, pictures, prov/bbox)
      - {stem}_artifacts/         — figure images referenced from JSON (when image_mode=referenced)
      - {stem}.links.json         — PDF hyperlinks (DOIs, URLs) with page + bbox
      - {stem}.assets/            — cropped table/figure PNGs with stable names
      - {stem}.elements.txt       — human-readable element tree (reading order)
      - {stem}.manifest.json      — run summary, paths, and every option used
      - {stem}.md                 — markdown export, when output_format is markdown|both
      - {stem}.chunks.jsonl       — token-sized chunks, when chunk=True
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
            markdown_md=Path(manifest.markdown_md) if manifest.markdown_md else None,
            chunks_jsonl=Path(manifest.chunking["chunks_jsonl"]) if manifest.chunking else None,
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
    markdown_md = output_dir / f"{stem}.md"
    chunks_jsonl = output_dir / f"{stem}.chunks.jsonl"

    log.info("Converting %s", pdf_path)
    converter, resolved_ocr_engine = _build_converter(
        ocr=ocr,
        ocr_engine=ocr_engine,
        ocr_full_page=ocr_full_page,
        ocr_lang=ocr_lang,
        images_scale=images_scale,
        formulas=formulas,
        code_enrichment=code_enrichment,
        picture_classification=picture_classification,
        picture_description=picture_description,
        device=device,
        threads=threads,
        table_mode=table_mode,
    )
    conversion_started = time.perf_counter()
    result = converter.convert(str(pdf_path))
    conversion_seconds = round(time.perf_counter() - conversion_started, 3)
    document = result.document

    ref_mode = _resolve_image_mode(image_mode)
    document.save_as_json(
        docling_json,
        artifacts_dir=artifacts_dir,
        image_mode=ref_mode,
        indent=2,
    )
    log.info("Wrote Docling JSON: %s", docling_json)

    markdown_path: Path | None = None
    if output_format in ("markdown", "both"):
        document.save_as_markdown(markdown_md, artifacts_dir=artifacts_dir, image_mode=ref_mode)
        markdown_path = markdown_md
        log.info("Wrote markdown: %s", markdown_md)

    chunking_info: dict[str, Any] | None = None
    if chunk:
        records, chunk_config = chunk_document(
            document,
            tokenizer_name=chunk_tokenizer,
            max_tokens=chunk_max_tokens,
            overlap=chunk_overlap,
        )
        write_chunks_sidecar(records, chunks_jsonl)
        chunking_info = {**chunk_config, "chunks_jsonl": str(chunks_jsonl)}
        log.info("Wrote %s chunks: %s", chunk_config["chunk_count"], chunks_jsonl)

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
        options={
            "ocr": ocr,
            "ocr_engine": resolved_ocr_engine,
            "ocr_full_page": ocr_full_page,
            "ocr_lang": ocr_lang or [],
            "device": device,
            "threads": threads,
            "formulas": formulas,
            "code_enrichment": code_enrichment,
            "picture_classification": picture_classification,
            "picture_description": picture_description,
            "table_mode": table_mode,
            "output_format": output_format,
            "images_scale": images_scale,
        },
        markdown_md=str(markdown_path) if markdown_path else None,
        chunking=chunking_info,
        conversion_seconds=conversion_seconds,
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
        markdown_md=markdown_path,
        chunks_jsonl=chunks_jsonl if chunking_info else None,
    )
