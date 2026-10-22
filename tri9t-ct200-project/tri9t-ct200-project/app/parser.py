"""CT-200-focused PDF extraction and conservative hierarchy reconstruction.

Text layer is preferred; OCR is used page-by-page only when a page has no useful text.
Unsupported or ambiguous material remains attached to the nearest known node instead
of being silently discarded.
"""
from __future__ import annotations
import hashlib, re, unicodedata
from pathlib import Path
from typing import Any
import fitz

SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:\.)?\s+(.+?)\s*$")
LIST_RE = re.compile(r"^(?:\d+[.)]|[•*-])\s+.+")
TABLE_HEADER_RE = re.compile(r"^(?:Parameter\s+Value|Code\s+Meaning\s+Device Behavior)$", re.I)
TABLE_ROW_RE = re.compile(r"^(?:Measurement method|Pressure range|Pulse range|Accuracy \(|Power source|Display|E\d+\s+|\s{2,}\w).*")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\ufb01", "fi").replace("\ufb02", "fl")
    value = value.replace("\u00ad", "")
    return re.sub(r"\s+", " ", value).strip()

def _ocr_page(page: fitz.Page) -> str:
    """OCR fallback for scanned pages; requires optional Tesseract executable."""
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        import io
        return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))))
    except Exception:
        return ""

def extract_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    path = Path(pdf_path)
    if not path.exists(): raise FileNotFoundError(f"PDF not found: {path}")
    doc = fitz.open(path)
    pages = []
    for index, page in enumerate(doc, start=1):
        text = page.get_text("text", sort=True) or ""
        method = "text"
        if len(re.sub(r"\s", "", text)) < 25:
            text = _ocr_page(page)
            method = "ocr" if text.strip() else "empty"
        pages.append({"page": index, "text": text, "method": method})
    doc.close()
    return pages

def _is_heading(line: str) -> tuple[str, str] | None:
    cleaned = normalize_text(line)
    match = SECTION_RE.match(cleaned)
    if not match: return None
    number, title = match.groups()
    # Avoid interpreting numbered clinical classification list items as headings.
    if len(number.split(".")) == 1 and title.lower().startswith(("normal:", "elevated:", "hypertension", "hypertensive crisis:")):
        return None
    if len(number) > 0 and title and len(title) < 130:
        return number, title
    return None

def _content_blocks(lines: list[tuple[str, int]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    table: list[str] = []
    list_items: list[str] = []
    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            text = normalize_text(" ".join(paragraph))
            if text: blocks.append({"type": "paragraph", "text": text})
            paragraph = []
    def flush_table():
        nonlocal table
        if table:
            blocks.append({"type": "table", "text": "\n".join(x.strip() for x in table), "rows": [x.strip() for x in table]})
            table = []
    def flush_list():
        nonlocal list_items
        if list_items:
            blocks.append({"type": "list", "items": [normalize_text(x) for x in list_items]})
            list_items = []
    for raw, _page in lines:
        line = raw.strip()
        if not line:
            flush_paragraph(); flush_table(); flush_list(); continue
        if TABLE_HEADER_RE.match(line) or (table and (TABLE_ROW_RE.match(line) or re.match(r"^E\d+\s", line))):
            flush_paragraph(); flush_list(); table.append(line); continue
        if table:
            # Table values in this manual wrap across lines; retain them as table rows.
            if re.match(r"^(E\d+|Measurement method|Pressure range|Pulse range|Accuracy|Power source|Display|leak detected|during measurement|measurement|function|serviced|displays|attempt;)", line, re.I):
                table.append(line); continue
            flush_table()
        if LIST_RE.match(line):
            flush_paragraph(); list_items.append(line); continue
        if list_items and not LIST_RE.match(line):
            # wrapped continuation of previous list item
            list_items[-1] += " " + line; continue
        # Keep short standalone labels and paragraphs, joining PDF line wraps.
        paragraph.append(line)
    flush_paragraph(); flush_table(); flush_list()
    return blocks

def parse_pdf(pdf_path: str | Path) -> dict[str, Any]:
    pages = extract_pages(pdf_path)
    all_lines: list[tuple[str, int]] = []
    for page in pages:
        for line in page["text"].replace("\r", "").splitlines():
            all_lines.append((line, page["page"]))
    # Find the document title from the first meaningful non-section lines.
    meaningful = [(normalize_text(line), p) for line, p in all_lines if normalize_text(line)]
    title_lines = []
    for line, _ in meaningful[:5]:
        if _is_heading(line): break
        title_lines.append(line)
    title = normalize_text(" ".join(title_lines)) or Path(pdf_path).stem
    raw_nodes: list[dict[str, Any]] = [{"heading": title, "section_number": None, "level": 0, "node_key": "document", "parent_key": None, "lines": [], "page_start": 1, "page_end": 1}]
    stack: dict[str, dict[str, Any]] = {}
    current = raw_nodes[0]
    for raw, page_no in all_lines:
        line = normalize_text(raw)
        if not line: continue
        # Skip repeated document title on page breaks, but preserve all other content.
        if line == title or line in title_lines: continue
        heading = _is_heading(line)
        if heading:
            number, heading_text = heading
            node_key = f"section:{number}:{normalize_text(heading_text).casefold()}"
            level = len(number.split("."))
            parent_key = "document"
            prefixes = [key for key in stack if number.startswith(key + ".")]
            if prefixes:
                parent_number = max(prefixes, key=lambda key: len(key.split(".")))
                parent_key = stack[parent_number]["node_key"]
            node = {"heading": heading_text, "section_number": number, "level": level, "node_key": node_key, "parent_key": parent_key, "lines": [], "page_start": page_no, "page_end": page_no}
            raw_nodes.append(node); stack[number] = node; current = node
            continue
        current["lines"].append((raw, page_no))
        current["page_end"] = page_no
    # Make every node's body structured; duplicate titles remain distinct because section path is part of key.
    nodes = []
    for item in raw_nodes:
        blocks = _content_blocks(item["lines"])
        body = "\n\n".join(
            block.get("text", "\n".join(block.get("items", []))) if block["type"] != "list" else "\n".join(block["items"])
            for block in blocks
        ).strip()
        nodes.append({k: item[k] for k in ("heading", "section_number", "level", "node_key", "parent_key", "page_start", "page_end")} | {"body_text": body, "content_hash": sha256_text(body), "content_blocks": blocks})
    # Validate parent references; absent intermediate levels are intentionally attached to nearest existing ancestor.
    keys = {n["node_key"] for n in nodes}
    for n in nodes:
        if n["parent_key"] not in keys: n["parent_key"] = "document"
    return {"title": title, "page_count": len(pages), "ocr_pages": [p["page"] for p in pages if p["method"] == "ocr"], "source_sha256": hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest(), "nodes": nodes}
