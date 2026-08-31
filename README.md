# Paper Extract (Docling)

Extract academic PDFs to **structured Docling JSON** with tables, figures, bounding boxes, reading order, and hyperlink sidecars.

Built for reference papers in KiB-heritage. Independent of `terrier-ta` (no curriculum cleaning, no RAG).

## Setup

```bash
cd docling
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

First conversion downloads Docling layout/table models (~hundreds of MB). Requires network.

## Usage

### CLI

```bash
extract-paper /path/to/paper.pdf
```

Or without installing the entry point:

```bash
python -m paper_extract.cli /path/to/paper.pdf
```

### Options

| Flag | Default | Purpose |
|------|---------|---------|
| `-o DIR` | PDF folder | Output directory |
| `--layout flat` | `flat` | `flat` \| `folder` (one subfolder per paper) |
| `--copy-source` | off | Copy source PDF into paper output dir |
| `--image-mode referenced` | `referenced` | `referenced` \| `embedded` \| `placeholder` |
| `--ocr` | off | Enable OCR for scanned PDFs |
| `--ocr-engine auto` | `auto` | `auto` \| `easyocr` \| `rapidocr` — requires `--ocr` |
| `--ocr-full-page` | off | OCR the whole page, not just regions flagged as images — requires `--ocr` |
| `--ocr-lang LANG,...` | none | Language hints, e.g. `en,hi` — requires `--ocr` **and** an explicit `--ocr-engine` |
| `--formulas` | off | Enable formula VLM enrichment (large extra model) |
| `--code-enrichment` | off | Recognise code blocks as code |
| `--picture-classification` | off | Classify picture/figure type (chart, photo, ...) |
| `--picture-description` | off | Caption figures with a VLM — **slow**, one model pass per picture |
| `--device auto` | `auto` | `auto` \| `cpu` \| `cuda` \| `mps` |
| `--threads N` | docling default | CPU thread count for model inference |
| `--table-mode accurate` | `accurate` | `accurate` \| `fast` — `fast` trades accuracy for speed on large batches |
| `--format json` | `json` | `json` \| `markdown` \| `both` — `markdown`/`both` also write `{stem}.md` |
| `--images-scale 2.0` | `2.0` | Figure/page render resolution |
| `--no-assets` | — | Skip cropped table/figure PNGs |
| `--no-links` | — | Skip hyperlink sidecar |
| `--no-element-tree` | — | Skip `.elements.txt` |
| `--chunk` | off | Write a token-sized chunk sidecar (`{stem}.chunks.jsonl`) via docling's `HybridChunker` |
| `--chunk-tokenizer NAME` | `sentence-transformers/all-MiniLM-L6-v2` | HuggingFace tokenizer used to size chunks |
| `--chunk-max-tokens N` | resolved from tokenizer | Max tokens per chunk |
| `--chunk-overlap N` | `0` | Tokens of the previous chunk prepended to each chunk |
| `-v` | — | Verbose logging |

**OCR gotchas** (measured on the installed docling version — reconfirm if you upgrade it):

- `--ocr-engine auto` **ignores `--ocr-lang` entirely**. Docling's auto mode defers language selection to whatever engine it probes for at runtime and never reads `lang`. Passing `--ocr-lang` with `auto` auto-upgrades the engine to `easyocr` (logged as a warning) so the hint actually takes effect.
- `easyocr` and `rapidocr` use **incompatible language vocabularies**. `easyocr` takes ISO 639-1 codes (`en`, `hi`, `fr`, ...) and supports 80+ languages including Devanagari. `rapidocr` (this docling version) only ships model bundles for the language *families* `english`, `chinese`, `latin` — there is no Devanagari model, so `--ocr-engine rapidocr --ocr-lang hi` raises rather than silently mis-OCRing.
- `--ocr-engine` / `--ocr-full-page` / `--ocr-lang` all raise if passed without `--ocr` — they'd otherwise be silent no-ops.

### Example (Henrickson et al.)

```bash
extract-paper \
  ../KiB-heritage/reference-papers-and-repos/2508.19093v2.pdf
```

### Example (input → output, folder layout)

```bash
extract-paper input/2508.19093v2.pdf -o output --layout folder --copy-source
```

Or via the shell wrapper (activates `.venv` automatically):

```bash
./extract.sh input/2508.19093v2.pdf -o output --layout folder --copy-source
```

Batch all PDFs in `input/`:

```bash
for pdf in input/*.pdf; do
  ./extract.sh "$pdf" -o output --layout folder --copy-source
done
```

With `--layout folder`, outputs land in `output/{stem}/` (one folder per paper).

### Python API

```python
from pathlib import Path
from paper_extract import extract_paper_pdf

result = extract_paper_pdf(
    Path("paper.pdf"),
    image_mode="referenced",
    ocr=True,
    ocr_engine="easyocr",
    ocr_full_page=True,
    ocr_lang=["en", "hi"],
    device="cuda",
    chunk=True,
)
print(result.docling_json)
print(result.markdown_md)      # None unless output_format is markdown|both
print(result.chunks_jsonl)     # None unless chunk=True
print(result.manifest.counts)
print(result.manifest.options)          # every pipeline knob used for this run
print(result.manifest.conversion_seconds)
```

## Outputs

For `paper.pdf` with stem `paper`:

| File | Contents |
|------|----------|
| `paper.docling.json` | Full `DoclingDocument`: `texts`, `tables`, `pictures`, `body` tree, `prov` (page, bbox, charspan) |
| `paper_artifacts/` | Figure images referenced from JSON |
| `paper.assets/` | Cropped `paper-table-001.png`, `paper-figure-001.png`, … |
| `paper.links.json` | PDF hyperlinks (DOIs, URLs) with page + bbox |
| `paper.elements.txt` | Reading-order element tree (debug/inspect) |
| `paper.manifest.json` | Run summary, paths, counts, PDF metadata, and every option used for the run |
| `paper.md` | Markdown export, when `--format markdown` or `--format both` |
| `paper.chunks.jsonl` | Token-sized chunks, one JSON object per line, when `--chunk` |

## What you get vs. limitations

**Included**

- Body text, headings, lists, captions
- Tables as structured cells + optional PNG crops
- Figures as referenced images + optional PNG crops
- Per-block provenance (`page_no`, `bbox`, `charspan`)
- Document reading order via `body` tree
- Hyperlink annotations (PyMuPDF sidecar)

**Not guaranteed**

- Every in-text citation linked to bibliography entries (text only)
- Perfect two-column reading order on all layouts
- Equations in LaTeX (formula enrichment depends on docling version)

For scanned papers, add `--ocr` (and `--ocr-full-page` if the layout model only catches part of the page).

## Pipeline settings

### Docling defaults already on

Measured by instantiating `PdfPipelineOptions()` directly on the installed docling version — check this again after any docling upgrade before assuming a flag is a no-op or missing:

| Setting | Installed default |
|---|---|
| `do_table_structure` | `True` |
| `table_structure_options.mode` | `ACCURATE` (not `FAST`) |
| `do_cell_matching` | `True` |
| `do_ocr` | `True` (this repo passes `False` unless `--ocr`) |
| `images_scale` | `1.0` (this repo defaults to `2.0`) |
| `generate_page_images` / `generate_picture_images` | `False` (this repo turns both on — required for asset export) |
| `force_full_page_ocr` | `False`, and it lives on `ocr_options`, not on `PdfPipelineOptions` itself |
| `do_formula_enrichment` / `do_code_enrichment` / `do_picture_classification` / `do_picture_description` | `False` |
| `ocr_options.kind` | `auto` |

`--table-mode accurate` is therefore a no-op against the installed default — it exists only so `--table-mode fast` is selectable.  `images_scale` only affects *generated* images (page/figure PNGs); with those generation flags on (as this repo sets them) it does not change OCR input resolution or extracted text quality.

### What the converter sets

- `do_table_structure=True`, `TableFormerMode.ACCURATE` by default, `--table-mode fast` for a quicker sanity pass
- `generate_page_images=True` and `generate_picture_images=True` (required for asset export)
- `AcceleratorOptions(device=..., num_threads=...)` from `--device`/`--threads` — always set explicitly so a run's device is recorded, never left to whatever docling would pick silently
- OCR, formula enrichment, code enrichment, picture classification/description, and chunking are all **off** by default (faster for born-digital Word/LaTeX PDFs, and `--picture-description` in particular runs a VLM pass per picture)

Docling models are cached under `docling/.cache/huggingface/` unless you set `HF_HOME`.

### Chunking: extraction-only, with one opt-in exception

This repo is deliberately extraction-only — no curriculum cleaning, no RAG, no embeddings. `--chunk` is the one addition, and it was a real decision, not a default-on feature:

- **Why it's here at all**: a private pipeline (`guidelines-generator`) already has a working `HybridChunker` setup (token-aware sizing, table headers surviving a chunk split, section-context prefixing). Without a shared implementation, every consumer of this repo's JSON either re-derives that chunker or does something worse.
- **Why it's opt-in and a separate file**: turning it on by default would blur this repo's one clear responsibility. `--chunk` writes `{stem}.chunks.jsonl` next to the JSON and never modifies `{stem}.docling.json`.
- **What it does not do**: docling's `HybridChunker` has no native overlap between chunks. `--chunk-overlap N` is implemented here by taking the trailing N tokens (by word boundary, sized with the same tokenizer) of the previous chunk and prepending them to the next — good enough for retrieval context, not a docling feature.
- **Reproducibility**: `--chunk-tokenizer` and `--chunk-max-tokens` are recorded in `manifest.json` under `chunking`, alongside the resolved chunk count and the jsonl path. A chunk store whose tokenizer/token-budget is unrecorded can't be compared against another one.

## Platform (Phase 0)

HTTP API + Redis worker for batch PDF extraction with crash-safe resume.

### Setup

```bash
cd docling
python3 -m venv .venv          # skip if .venv already exists
source .venv/bin/activate
pip install -e ".[platform,dev]"
cp .env.example .env           # optional: DATABASE_URL, REDIS_URL, STORAGE_ROOT
```

Start Redis (Docker):

```bash
docker compose up -d redis
```

Run API + worker (single script):

```bash
chmod +x scripts/*.sh extract.sh
./scripts/run-platform.sh
```

Or run API and worker in **separate terminals**:

```bash
# Terminal 1 — API
source .venv/bin/activate
paper-extract-api

# Terminal 2 — worker
source .venv/bin/activate
paper-extract-worker
```

Or Docker full stack (redis + api + worker):

```bash
docker compose up --build
```

### Health checks

```bash
curl -s http://localhost:8000/api/v1/health | jq
curl -s http://localhost:8000/api/v1/ready | jq
```

### API flow

```bash
# 1. Create job (save job_id + token)
CREATE=$(curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" -d '{}')
echo "$CREATE" | jq
JOB_ID=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
TOKEN=$(echo "$CREATE" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 2. Upload one or more PDFs (up to 100 per job)
curl -s -X POST "http://localhost:8000/api/v1/jobs/$JOB_ID/files" \
  -H "X-Job-Token: $TOKEN" \
  -F "files=@input/2508.19093v2.pdf" \
  -F "files=@input/2508.02866v3.pdf" | jq

# Auth: X-Job-Token header, or Authorization: Bearer $TOKEN

# 3. Start processing
curl -s -X POST "http://localhost:8000/api/v1/jobs/$JOB_ID/start" \
  -H "X-Job-Token: $TOKEN" | jq

# 4. Poll status (progress, ETA, per-file counts)
curl -s "http://localhost:8000/api/v1/jobs/$JOB_ID" \
  -H "X-Job-Token: $TOKEN" | jq
```

End-to-end demo script (create → upload → start → poll):

```bash
./scripts/phase0-demo.sh input/2508.19093v2.pdf
```

After completion, inspect outputs:

```bash
find data/storage/jobs -name "*.manifest.json" | head
```

### Output layout (platform)

Each job writes under `data/storage/jobs/{job_id}/`:

```
uploads/{stem}.pdf
output/{stem}/
  {stem}.pdf
  {stem}.docling.json
  {stem}.manifest.json
  {stem}.links.json
  {stem}.elements.txt
  {stem}_artifacts/
  {stem}.assets/
```

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/health` | — | Liveness |
| GET | `/api/v1/ready` | — | DB + Redis + storage |
| POST | `/api/v1/jobs` | — | Create job, returns `token` |
| POST | `/api/v1/jobs/{id}/files` | `X-Job-Token` | Upload PDFs |
| POST | `/api/v1/jobs/{id}/start` | `X-Job-Token` | Enqueue processing |
| GET | `/api/v1/jobs/{id}` | `X-Job-Token` | Status, progress, ETA |

### Tests

```bash
pytest tests/ -q
```

PRD: `prd/PAPER_EXTRACT_PLATFORM_PRD.md`
