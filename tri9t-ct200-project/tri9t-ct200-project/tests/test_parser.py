from app.parser import parse_pdf

def by_number(parsed, number):
    return next(n for n in parsed["nodes"] if n["section_number"] == number)

def test_duplicate_error_code_headings_are_distinct_and_correctly_parented(data_dir):
    parsed = parse_pdf(data_dir / "ct200_manual.pdf")
    error_42 = by_number(parsed, "4.2")
    error_71 = by_number(parsed, "7.1")
    assert error_42["heading"].lower() == error_71["heading"].lower() == "error codes"
    assert error_42["node_key"] != error_71["node_key"]
    by_key = {n["node_key"]: n for n in parsed["nodes"]}
    assert by_key[error_42["parent_key"]]["section_number"] == "4"
    assert by_key[error_71["parent_key"]]["section_number"] == "7"

def test_missing_intermediate_heading_attaches_to_nearest_existing_parent(data_dir):
    parsed = parse_pdf(data_dir / "ct200_manual.pdf")
    battery = by_number(parsed, "2.1.1.1")
    by_key = {n["node_key"]: n for n in parsed["nodes"]}
    parent = by_key[battery["parent_key"]]
    assert parent["section_number"] == "2.1"
    assert parent["heading"] == "General Specifications"

def test_out_of_order_subsections_keep_correct_parent(data_dir):
    parsed = parse_pdf(data_dir / "ct200_manual.pdf")
    by_key = {n["node_key"]: n for n in parsed["nodes"]}
    auto = by_number(parsed, "3.4")
    result = by_number(parsed, "3.3")
    assert parsed["nodes"].index(auto) < parsed["nodes"].index(result)
    assert by_key[auto["parent_key"]]["section_number"] == "3"
    assert by_key[result["parent_key"]]["section_number"] == "3"

def test_v2_changed_thresholds_and_new_section_are_detected(data_dir):
    v1 = parse_pdf(data_dir / "ct200_manual.pdf")
    v2 = parse_pdf(data_dir / "ct200_manual_v2.pdf")
    old = {n["node_key"]: n for n in v1["nodes"]}
    new = {n["node_key"]: n for n in v2["nodes"]}
    battery_key = by_number(v1, "2.1.1.1")["node_key"]
    inflation_key = by_number(v1, "3.2")["node_key"]
    assert old[battery_key]["content_hash"] != new[battery_key]["content_hash"]
    assert old[inflation_key]["content_hash"] != new[inflation_key]["content_hash"]
    assert any(n["section_number"] == "5.3" for n in v2["nodes"])
    assert not any(n["section_number"] == "5.3" for n in v1["nodes"])
