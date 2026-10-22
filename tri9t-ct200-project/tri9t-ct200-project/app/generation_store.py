"""Small JSON document store for generated outputs (no extra database service required)."""
import json
from pathlib import Path
from app.config import settings

class GenerationStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path or settings.generations_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists(): self.path.write_text("[]", encoding="utf-8")
    def all(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            # Corrupt JSON is surfaced as an explicit error, not silently overwritten.
            raise RuntimeError(f"Generated-output JSON store is unreadable: {self.path}")
    def save(self, item: dict) -> dict:
        items = self.all(); items.append(item)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)
        return item
    def get(self, generation_id: str) -> dict | None:
        return next((x for x in self.all() if x.get("generation_id") == generation_id), None)
    def by_selection(self, selection_id: int) -> list[dict]:
        return [x for x in self.all() if x.get("selection_id") == selection_id]
    def by_node(self, logical_id: str) -> list[dict]:
        return [x for x in self.all() if any(s.get("logical_id") == logical_id for s in x.get("source_snapshots", []))]
