"""Run the full v1 -> selection -> generation -> v2 -> stale-check flow.
Start uvicorn from the repository root, then run: python scripts/demo.py
"""
import json
import os
import httpx

BASE = os.environ.get("CT200_API_URL", "http://127.0.0.1:8000")
DATA_V1 = "data/ct200_manual.pdf"
DATA_V2 = "data/ct200_manual_v2.pdf"

def show(label, value):
    print(f"\n--- {label} ---")
    print(json.dumps(value, indent=2, ensure_ascii=False))

def main():
    with httpx.Client(base_url=BASE, timeout=30) as client:
        response = client.get("/health"); response.raise_for_status()
        response = client.post("/documents/ingest", json={"file_path": DATA_V1, "document_key": "ct200"})
        response.raise_for_status(); show("INGEST V1", response.json())

        response = client.get("/search", params={"q": "measurement cycles", "version": 1})
        response.raise_for_status()
        node = next((n for n in response.json()["results"] if n.get("section_number") == "2.1.1.1"), None)
        if not node: raise RuntimeError("Could not find section 2.1.1.1 in version 1")

        response = client.post("/selections", json={"name": "Battery life QA demo", "node_ids": [node["id"]]})
        response.raise_for_status(); selection = response.json(); show("VERSION-PINNED SELECTION", selection)
        response = client.post("/generations", json={"selection_id": selection["selection_id"]})
        response.raise_for_status(); generation = response.json()["generation"]
        show("GENERATED TEST CASES (BEFORE V2)", generation)

        response = client.post("/documents/ingest", json={"file_path": DATA_V2, "document_key": "ct200"})
        response.raise_for_status(); show("INGEST V2", response.json())
        response = client.get("/generations", params={"selection_id": selection["selection_id"]})
        response.raise_for_status(); show("STALE CHECK AFTER V2", response.json())
        response = client.get(f"/nodes/{node['id']}/diff")
        response.raise_for_status(); show("NODE DIFF", response.json())

if __name__ == "__main__": main()
