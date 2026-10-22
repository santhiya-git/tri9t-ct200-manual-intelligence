from __future__ import annotations
import difflib, json, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Base, engine, get_db
from app.models import DocumentVersion, DocumentNode, Selection, SelectionItem
from app.schemas import IngestRequest, SelectionCreate, GenerateRequest
from app.parser import parse_pdf
from app.generation_store import GenerationStore
from app.llm import generate_cases

Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="1.0.0", description="Versioned PDF hierarchy, QA generation and traceability API for the CT-200 assignment.")
store = GenerationStore()

def latest_version(db: Session, document_key: str = "ct200"):
    return db.scalar(select(DocumentVersion).where(DocumentVersion.document_key == document_key).order_by(DocumentVersion.version_number.desc()).limit(1))

def version_by_number(db: Session, number: int | None, document_key: str = "ct200"):
    if number is None: return latest_version(db, document_key)
    return db.scalar(select(DocumentVersion).where(DocumentVersion.document_key == document_key, DocumentVersion.version_number == number))

def node_payload(node: DocumentNode, include_children: bool = False, db: Session | None = None) -> dict:
    data = {"id": node.id, "logical_id": node.logical_id, "version_id": node.version_id, "version_number": node.version.version_number, "node_key": node.node_key, "heading": node.heading, "section_number": node.section_number, "level": node.level, "parent_node_id": node.parent_node_id, "body_text": node.body_text, "content_hash": node.content_hash, "content_blocks": json.loads(node.content_blocks_json or "[]"), "page_start": node.page_start, "page_end": node.page_end}
    if include_children and db:
        children = db.scalars(select(DocumentNode).where(DocumentNode.parent_node_id == node.id).order_by(DocumentNode.id)).all()
        data["children"] = [node_payload(child, True, db) for child in children]
    return data

def ingest_pdf(db: Session, file_path: str, document_key: str = "ct200") -> dict:
    parsed = parse_pdf(file_path)
    existing = db.scalar(select(DocumentVersion).where(DocumentVersion.document_key == document_key, DocumentVersion.source_sha256 == parsed["source_sha256"]))
    if existing:
        return {"message": "This exact PDF has already been ingested; no duplicate version created.", "version_id": existing.id, "version_number": existing.version_number, "node_count": len(existing.nodes), "already_ingested": True}
    current = latest_version(db, document_key)
    version_number = (current.version_number + 1) if current else 1
    version = DocumentVersion(document_key=document_key, version_number=version_number, source_filename=Path(file_path).name, source_sha256=parsed["source_sha256"])
    db.add(version); db.flush()
    by_key: dict[str, DocumentNode] = {}
    for item in parsed["nodes"]:
        logical_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"ct200-node:{document_key}:{item['node_key']}"))
        parent = by_key.get(item["parent_key"])
        node = DocumentNode(logical_id=logical_id, version_id=version.id, node_key=item["node_key"], heading=item["heading"], section_number=item["section_number"], level=item["level"], parent_node_id=parent.id if parent else None, body_text=item["body_text"], content_hash=item["content_hash"], content_blocks_json=json.dumps(item["content_blocks"], ensure_ascii=False), page_start=item["page_start"], page_end=item["page_end"])
        db.add(node); db.flush(); by_key[item["node_key"]] = node
    db.commit()
    return {"message": "PDF ingested successfully", "version_id": version.id, "version_number": version_number, "node_count": len(parsed["nodes"]), "page_count": parsed["page_count"], "ocr_pages": parsed["ocr_pages"], "source_sha256": parsed["source_sha256"], "already_ingested": False}

@app.get("/")
def root(): return {"name": settings.app_name, "docs": "/docs", "health": "/health"}

@app.get("/health")
def health(): return {"status": "ok", "llm_provider": settings.llm_provider if settings.llm_provider == "groq" and settings.llm_api_key else "mock"}

@app.post("/documents/ingest")
def ingest(request: IngestRequest, db: Session = Depends(get_db)):
    try: return ingest_pdf(db, request.file_path, request.document_key)
    except FileNotFoundError as exc: raise HTTPException(400, str(exc))
    except Exception as exc:
        db.rollback(); raise HTTPException(422, f"Could not ingest PDF: {exc}")

@app.post("/documents/upload")
def upload_pdf(file: UploadFile = File(...), document_key: str = Query("ct200"), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"): raise HTTPException(400, "Please upload a PDF file.")
    upload_dir = Path("data/uploads"); upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    target = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    target.write_bytes(file.file.read())
    try: return ingest_pdf(db, str(target), document_key)
    except Exception as exc:
        db.rollback(); raise HTTPException(422, f"Could not ingest PDF: {exc}")

@app.get("/documents/versions")
def list_versions(document_key: str = "ct200", db: Session = Depends(get_db)):
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_key == document_key).order_by(DocumentVersion.version_number)).all()
    return {"document_key": document_key, "versions": [{"id": v.id, "version_number": v.version_number, "source_filename": v.source_filename, "source_sha256": v.source_sha256, "created_at": v.created_at.isoformat(), "node_count": len(v.nodes)} for v in versions]}

@app.get("/sections")
def top_sections(version: int | None = None, document_key: str = "ct200", db: Session = Depends(get_db)):
    ver = version_by_number(db, version, document_key)
    if not ver: raise HTTPException(404, "No document version found. Ingest a PDF first.")
    nodes = db.scalars(select(DocumentNode).where(DocumentNode.version_id == ver.id, DocumentNode.level == 1).order_by(DocumentNode.id)).all()
    return {"version": ver.version_number, "sections": [node_payload(n) for n in nodes]}

@app.get("/nodes/{node_id}")
def get_node(node_id: int, db: Session = Depends(get_db)):
    node = db.get(DocumentNode, node_id)
    if not node: raise HTTPException(404, "Node not found")
    return node_payload(node, True, db)

@app.get("/search")
def search_nodes(q: str = Query(min_length=1), version: int | None = None, document_key: str = "ct200", limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    ver = version_by_number(db, version, document_key)
    if not ver: raise HTTPException(404, "No document version found")
    pattern = f"%{q}%"
    nodes = db.scalars(select(DocumentNode).where(DocumentNode.version_id == ver.id, or_(DocumentNode.heading.ilike(pattern), DocumentNode.body_text.ilike(pattern))).order_by(DocumentNode.id).limit(limit)).all()
    return {"version": ver.version_number, "query": q, "count": len(nodes), "results": [node_payload(n) for n in nodes]}

@app.get("/nodes/{node_id}/diff")
def node_diff(node_id: int, db: Session = Depends(get_db)):
    node = db.get(DocumentNode, node_id)
    if not node: raise HTTPException(404, "Node not found")
    latest = latest_version(db, node.version.document_key)
    current = db.scalar(select(DocumentNode).where(DocumentNode.version_id == latest.id, DocumentNode.logical_id == node.logical_id)) if latest else None
    if not current:
        return {"node_id": node.id, "logical_id": node.logical_id, "source_version": node.version.version_number, "latest_version": latest.version_number if latest else None, "changed": True, "status": "removed_or_renamed", "summary": "No matching logical node exists in the latest version."}
    changed = node.content_hash != current.content_hash or node.heading != current.heading
    diff_lines = list(difflib.unified_diff(node.body_text.splitlines(), current.body_text.splitlines(), fromfile=f"v{node.version.version_number}", tofile=f"v{latest.version_number}", lineterm=""))
    return {"node_id": node.id, "logical_id": node.logical_id, "source_version": node.version.version_number, "latest_version": latest.version_number, "latest_node_id": current.id, "changed": changed, "status": "changed" if changed else "unchanged", "source_hash": node.content_hash, "latest_hash": current.content_hash, "summary": f"Content {'differs' if changed else 'matches'} between versions.", "diff": diff_lines[:80]}

@app.post("/selections", status_code=201)
def create_selection(request: SelectionCreate, db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(request.node_ids))
    nodes = db.scalars(select(DocumentNode).where(DocumentNode.id.in_(ids))).all()
    if len(nodes) != len(ids): raise HTTPException(404, "One or more node IDs do not exist")
    version_ids = {n.version_id for n in nodes}
    if len(version_ids) != 1: raise HTTPException(400, "All selected nodes must belong to the same document version")
    selection = Selection(name=request.name.strip()); db.add(selection); db.flush()
    for n in nodes:
        db.add(SelectionItem(selection_id=selection.id, node_id=n.id, version_id=n.version_id, logical_id=n.logical_id, heading_snapshot=n.heading, text_snapshot=(n.heading + "\n" + n.body_text).strip(), content_hash_snapshot=n.content_hash))
    db.commit(); db.refresh(selection)
    return {"selection_id": selection.id, "name": selection.name, "version_id": next(iter(version_ids)), "version_number": nodes[0].version.version_number, "items": [{"node_id": n.id, "logical_id": n.logical_id, "heading": n.heading, "content_hash": n.content_hash} for n in nodes]}

@app.get("/selections/{selection_id}")
def get_selection(selection_id: int, db: Session = Depends(get_db)):
    selection = db.get(Selection, selection_id)
    if not selection: raise HTTPException(404, "Selection not found")
    return {"selection_id": selection.id, "name": selection.name, "created_at": selection.created_at.isoformat(), "items": [{"node_id": i.node_id, "version_id": i.version_id, "version_number": i.version.version_number, "logical_id": i.logical_id, "heading": i.heading_snapshot, "text_snapshot": i.text_snapshot, "content_hash": i.content_hash_snapshot} for i in selection.items]}

def decorate_generation(item: dict, db: Session) -> dict:
    latest = latest_version(db, item.get("document_key", "ct200")); current_by_logical = {}
    if latest:
        current_nodes = db.scalars(select(DocumentNode).where(DocumentNode.version_id == latest.id)).all()
        current_by_logical = {n.logical_id: n for n in current_nodes}
    snapshots = []
    for snap in item.get("source_snapshots", []):
        current = current_by_logical.get(snap["logical_id"])
        stale = current is None or current.content_hash != snap["content_hash"]
        snapshots.append(snap | {"stale": stale, "latest_version": latest.version_number if latest else None, "latest_content_hash": current.content_hash if current else None, "staleness_reason": "node removed or renamed" if current is None else ("source content changed" if stale else "source content unchanged")})
    result = dict(item); result["source_snapshots"] = snapshots; result["stale"] = any(s["stale"] for s in snapshots)
    result["staleness_summary"] = "One or more source requirements changed or disappeared." if result["stale"] else "All source requirement hashes match the latest version."
    return result

@app.post("/generations", status_code=201)
def create_generation(request: GenerateRequest, db: Session = Depends(get_db)):
    selection = db.get(Selection, request.selection_id)
    if not selection: raise HTTPException(404, "Selection not found")
    existing = store.by_selection(selection.id)
    if existing and not request.force_new:
        return {"policy": "idempotent", "message": "Returning the most recent generation for this selection. Set force_new=true to generate again.", "generation": decorate_generation(existing[-1], db)}
    source = "\n\n".join(i.text_snapshot for i in selection.items)
    try: output, provider = generate_cases(source)
    except RuntimeError as exc: raise HTTPException(502, str(exc))
    item = {"generation_id": str(uuid.uuid4()), "selection_id": selection.id, "selection_name": selection.name, "document_key": selection.items[0].version.document_key, "source_version": selection.items[0].version.version_number, "created_at": datetime.now(timezone.utc).isoformat(), "provider": provider, "source_snapshots": [{"node_id": i.node_id, "version_id": i.version_id, "version_number": i.version.version_number, "logical_id": i.logical_id, "heading": i.heading_snapshot, "content_hash": i.content_hash_snapshot, "text_snapshot": i.text_snapshot} for i in selection.items], "test_cases": [tc.model_dump() for tc in output.test_cases]}
    store.save(item)
    return {"policy": "created", "generation": decorate_generation(item, db)}

@app.get("/generations")
def retrieve_generations(selection_id: int | None = None, node_id: int | None = None, db: Session = Depends(get_db)):
    if selection_id is None and node_id is None: raise HTTPException(400, "Provide selection_id or node_id")
    items = store.by_selection(selection_id) if selection_id is not None else []
    if node_id is not None:
        node = db.get(DocumentNode, node_id)
        if not node: raise HTTPException(404, "Node not found")
        items += store.by_node(node.logical_id)
    unique = {x["generation_id"]: x for x in items}
    return {"count": len(unique), "generations": [decorate_generation(x, db) for x in unique.values()]}

@app.get("/generations/{generation_id}")
def retrieve_generation(generation_id: str, db: Session = Depends(get_db)):
    item = store.get(generation_id)
    if not item: raise HTTPException(404, "Generation not found")
    return decorate_generation(item, db)
