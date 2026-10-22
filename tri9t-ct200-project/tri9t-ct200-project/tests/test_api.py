def test_end_to_end_versioning_selection_generation_and_staleness(client, data_dir):
    first = client.post("/documents/ingest", json={"file_path": str(data_dir / "ct200_manual.pdf")})
    assert first.status_code == 200, first.text
    assert first.json()["version_number"] == 1
    search = client.get("/search", params={"q": "300 measurement cycles", "version": 1})
    assert search.status_code == 200
    assert search.json()["count"] >= 1
    node = next(n for n in search.json()["results"] if n["section_number"] == "2.1.1.1")
    selection = client.post("/selections", json={"name": "Battery QA", "node_ids": [node["id"]]})
    assert selection.status_code == 201, selection.text
    selection_id = selection.json()["selection_id"]
    generated = client.post("/generations", json={"selection_id": selection_id})
    assert generated.status_code == 201, generated.text
    generation = generated.json()["generation"]
    assert 3 <= len(generation["test_cases"]) <= 5
    assert generation["stale"] is False
    second = client.post("/documents/ingest", json={"file_path": str(data_dir / "ct200_manual_v2.pdf")})
    assert second.status_code == 200, second.text
    assert second.json()["version_number"] == 2
    fetched = client.get("/generations", params={"selection_id": selection_id})
    assert fetched.status_code == 200
    assert fetched.json()["generations"][0]["stale"] is True
    diff = client.get(f"/nodes/{node['id']}/diff")
    assert diff.status_code == 200
    assert diff.json()["changed"] is True

def test_same_selection_generation_is_idempotent(client, data_dir):
    ing = client.post("/documents/ingest", json={"file_path": str(data_dir / "ct200_manual.pdf")})
    assert ing.status_code == 200
    result = client.get("/search", params={"q": "Bluetooth Sync", "version": 1}).json()
    node = next(n for n in result["results"] if n["section_number"] == "5.2")
    selection = client.post("/selections", json={"name": "sync", "node_ids": [node["id"]]}).json()
    a = client.post("/generations", json={"selection_id": selection["selection_id"]}).json()
    b = client.post("/generations", json={"selection_id": selection["selection_id"]}).json()
    assert a["generation"]["generation_id"] == b["generation"]["generation_id"]
    assert b["policy"] == "idempotent"
