# CT-200 Traceable QA API

A beginner-friendly backend for the Tri9T AI engineering internship assignment. It parses the supplied CardioTrack CT-200 PDFs into a versioned hierarchy, stores the tree in SQLite, creates version-pinned selections, generates structured QA test-case ideas, and marks generated cases stale when their source text changes.

> **Important:** This is an engineering assignment demo, not a medical device validation system. Generated test cases are ideas and require review by a qualified QA engineer. The offline default generator is deterministic and does not call an LLM.

## Features

- PDF text extraction with page-level Tesseract OCR fallback when a page has no usable text.
- Section/subsection hierarchy, paragraphs, numbered lists, heuristic table blocks, page ranges, and SHA-256 content hashes.
- Handles the observed CT-200 irregularities: `2.1.1.1` without a `2.1.1` heading, out-of-order `3.4` and `3.3`, repeated “Error Codes” heading under different sections, wrapped table rows, and v2-only sections.
- SQLite persistence with immutable version records and version-specific node records.
- Path/section-number based logical node identity; changed body text retains the same logical identity when its heading path is unchanged.
- Search, browse, lightweight diff, version-pinned selection snapshots, structured test-case validation, JSON-file generation store, and retrieval-time stale status.
- Default offline/mock generation works without a secret or network connection. Optional Groq-compatible API mode is available.
- Automated parser and end-to-end API tests.

## Requirements

- Python 3.10 or newer (Python 3.11 recommended)
- `pip`
- Optional: Tesseract OCR installed and on `PATH` for scanned PDF pages
- Optional: Groq API key for live LLM generation

## Windows setup (PowerShell)

Open PowerShell in this repository folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again. Or run commands with `.venv\Scripts\python.exe` directly.

## macOS / Linux setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

## Start the API

From the project root, with the virtual environment active:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for interactive Swagger docs and <http://127.0.0.1:8000/health> for a health check. The API creates `ct200.db` on first import. The generated QA output store is `data/generated_cases.json`.

## Run the complete v1 → v2 demo

**Terminal 1:** Start the API as above.

**Terminal 2 (PowerShell):**

```powershell
# Ingest v1
$body = @{ file_path = (Resolve-Path .\data\ct200_manual.pdf).Path; document_key = 'ct200' } | ConvertTo-Json
$v1 = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/documents/ingest -ContentType 'application/json' -Body $body
$v1

# Browse the top-level sections
Invoke-RestMethod 'http://127.0.0.1:8000/sections?version=1' | ConvertTo-Json -Depth 5

# Find the battery-life section
$found = Invoke-RestMethod 'http://127.0.0.1:8000/search?q=measurement%20cycles&version=1'
$node = $found.results | Where-Object { $_.section_number -eq '2.1.1.1' } | Select-Object -First 1
$node | ConvertTo-Json -Depth 4

# Create a version-pinned selection
$selectionBody = @{ name = 'Battery-life QA'; node_ids = @([int]$node.id) } | ConvertTo-Json
$selection = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/selections -ContentType 'application/json' -Body $selectionBody
$selection | ConvertTo-Json -Depth 5

# Generate 3–5 QA ideas (offline mode by default)
$generationBody = @{ selection_id = [int]$selection.selection_id } | ConvertTo-Json
$generation = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/generations -ContentType 'application/json' -Body $generationBody
$generation.generation | ConvertTo-Json -Depth 8

# Ingest v2 as the next version (v1 remains intact)
$body2 = @{ file_path = (Resolve-Path .\data\ct200_manual_v2.pdf).Path; document_key = 'ct200' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/documents/ingest -ContentType 'application/json' -Body $body2

# Retrieve old generation; stale should now be true for the changed battery-life section
Invoke-RestMethod "http://127.0.0.1:8000/generations?selection_id=$($selection.selection_id)" | ConvertTo-Json -Depth 9

# Compare the v1 node with the latest version
Invoke-RestMethod "http://127.0.0.1:8000/nodes/$($node.id)/diff" | ConvertTo-Json -Depth 6
```

**Alternative upload:** `POST /documents/upload` accepts a PDF as multipart form data. This is useful in Swagger UI (`/docs`).

The ingest endpoint is idempotent for an identical PDF file: submitting the same exact bytes does not create a duplicate version. Ingesting the supplied v2 file after v1 creates version 2.

## Run tests

```bash
python -m pytest -q
```

Tests cover the three structural edge cases explicitly and an API flow that ingests both versions, selects a requirement, generates test cases, and verifies stale status after re-ingestion.

## Optional live LLM (Groq-compatible)

Edit `.env`:

```dotenv
LLM_PROVIDER=groq
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
```

Restart the API. The output is parsed as JSON and validated with Pydantic; one corrective retry is attempted. If the response is still malformed, the API returns HTTP 502 and does not save an invalid generation. Do not commit `.env` or API keys. Without a key/provider configuration, the deterministic offline generator is used.

## Main API routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/documents/ingest` | Ingest a local PDF path |
| `POST` | `/documents/upload` | Upload and ingest a PDF |
| `GET` | `/documents/versions` | List document versions |
| `GET` | `/sections?version=1` | List top-level sections; defaults to latest |
| `GET` | `/nodes/{node_id}` | Get a node, full text, blocks, and recursive children |
| `GET` | `/search?q=pressure&version=1` | Search heading/body text |
| `GET` | `/nodes/{node_id}/diff` | Compare a node with the latest matching logical node |
| `POST` | `/selections` | Create a version-pinned selection |
| `GET` | `/selections/{selection_id}` | Read exact pinned source snapshots |
| `POST` | `/generations` | Generate QA ideas for a selection |
| `GET` | `/generations?selection_id=1` | Retrieve generation(s) with live stale status |
| `GET` | `/generations/{generation_id}` | Retrieve one generation with live stale status |

### Example request bodies

`POST /documents/ingest`:

```json
{"file_path":"/absolute/path/to/ct200_manual.pdf","document_key":"ct200"}
```

`POST /selections`:

```json
{"name":"Overpressure safety","node_ids":[12,13]}
```

All selected nodes must belong to the same version. Each selection item stores a snapshot of the exact source text and hash, so re-ingestion cannot rewrite its original evidence.

`POST /generations`:

```json
{"selection_id":1,"force_new":false}
```

Repeat generation requests are idempotent by default and return the latest saved output for that selection. Set `force_new` to `true` to create another generation.

## Project layout

```text
app/                 FastAPI routes, parsing, SQLAlchemy models, LLM and JSON store
 data/               Source PDFs and assignment update; generated JSON is runtime data
 docs/                Approach and decision log
 tests/               Parser edge cases and API integration tests
 scripts/             End-to-end demonstration helper
 postman/             Importable Postman collection
 README.md
 requirements.txt
 .env.example
```

## GitHub submission checklist

1. Run tests and the end-to-end flow locally.
2. Review the code so you can explain the parser, identity matcher, and stale-check logic.
3. Initialize Git and make incremental commits (do not squash everything into one commit).
4. Push to a repository you own; verify that the PDFs, README, tests, and approach document are present.
5. Include the repository and `docs/APPROACH.md` in the submission email.

Suggested commit sequence is in `docs/GIT_WORKFLOW.md`. Create real commits while implementing/reviewing the code; the suggested sequence is not a substitute for actual history.
