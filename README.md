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
| `--formulas` | off | Enable formula VLM enrichment (large extra model) |
| `--images-scale 2.0` | `2.0` | Figure/page render resolution |
| `--no-assets` | — | Skip cropped table/figure PNGs |
| `--no-links` | — | Skip hyperlink sidecar |
| `--no-element-tree` | — | Skip `.elements.txt` |
| `-v` | — | Verbose logging |

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
    ocr=False,
)
print(result.docling_json)
print(result.manifest.counts)
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
| `paper.manifest.json` | Run summary, paths, counts, PDF metadata |

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

For scanned papers, add `--ocr`.

## Pipeline settings

The converter enables:

- `do_table_structure=True` with `TableFormerMode.ACCURATE`
- `generate_page_images=True` and `generate_picture_images=True` (required for asset export)
- Formula enrichment with `--formulas` (downloads CodeFormula VLM; slow)

OCR and formula enrichment are **off** by default (faster for born-digital Word/LaTeX PDFs).

Docling models are cached under `docling/.cache/huggingface/` unless you set `HF_HOME`.

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
