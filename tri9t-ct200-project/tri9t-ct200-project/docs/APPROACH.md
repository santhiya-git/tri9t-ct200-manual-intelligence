# Approach Document — CT-200 Traceable QA API

## 1. Summary

The service turns the supplied CT-200 PDF into a navigable, versioned hierarchy and creates structured QA test-case ideas from version-pinned selections. FastAPI exposes the workflow; SQLAlchemy/SQLite stores document versions, nodes, selections, and selection items. Generated output is stored in a small JSON document store, a deliberate and justified alternative to running MongoDB for a small single-user assignment demo.

## 2. Extraction approach

PyMuPDF extracts the PDF text layer in page order. A page with almost no usable text is rendered and passed to Tesseract OCR if installed. The parser does not silently switch to OCR for every page because these supplied PDFs contain an extractable text layer; text extraction is more accurate for their selectable text and keeps setup simple. OCR fallback page numbers are returned by the parser so they can be reviewed.

The parser identifies numbered headings using a conservative section-number pattern and treats the initial document title as a root node. It reconstructs parent links by the longest existing numeric section prefix. When an intermediate section is missing, the node attaches to the nearest existing ancestor. Body content is represented as paragraph, list, or heuristic table blocks; plain `body_text` is also retained for searching and prompting. Each node has a SHA-256 hash of normalized body text.

## 3. Structural irregularities and handling

| Observed case | Handling | Test/validation |
|---|---|---|
| `2.1.1.1 Battery Life Under Typical Use` appears without `2.1.1` | Attach it to the nearest existing parent (`2.1 General Specifications`) rather than inventing an absent node | `test_missing_intermediate_heading_attaches_to_nearest_existing_parent` |
| Subsection `3.4` appears before `3.3` | Parent resolution uses section-number prefixes, not a monotonic heading stack, so both attach to section `3` | `test_out_of_order_subsections_keep_correct_parent` |
| “Error Codes” appears as both `4.2` and `7.1` | Numeric section number is part of the node key; distinct headings and parent paths are preserved | `test_duplicate_error_code_headings_are_distinct_and_correctly_parented` |
| Tables wrap values onto following lines | Heuristic table blocks retain source lines; table extraction is explicitly best-effort rather than claiming semantic cell-perfect recovery | Manual inspection and parsed block review |
| v2 inserts `5.3 Data Export` and changes values/text | Version-specific nodes are preserved; new sections appear only in v2 and changed body hashes are visible in diff/staleness API | Versioning test and API integration test |
| PDF line wrapping and ligatures | Unicode normalization and whitespace normalization are applied before hashing; original readable wording remains in extracted body text | Hash and body-text checks |

The PDF's visual tables are not a guaranteed source of perfect rows/cells. For a production-grade extractor, I would use PyMuPDF block coordinates or pdfplumber table extraction with per-page visual comparison, and expose a parse warning when a table cannot be confidently reconstructed.

## 4. Data model

- `DocumentVersion`: immutable ingestion record with document key, sequential version number, source filename, source SHA-256, and timestamp.
- `DocumentNode`: one node per version, with logical ID, version-specific database ID, key, heading, section number, level, parent ID, body text, content hash, structured blocks, and page range.
- `Selection`: named selection created by the caller.
- `SelectionItem`: immutable reference to node + version, plus heading/text/hash snapshots. The snapshot is what generation consumes, not a future latest node.
- JSON generation document: generation ID, selection ID, provider, source snapshots, generated cases, source version, and creation timestamp.

SQLite keeps relational references and version history. JSON is used as the NoSQL-like store for generated output because the assignment permits a well-justified JSON store. Writes use a temporary file and atomic replace. This is adequate for a local demo, not concurrent multi-worker production traffic.

## 5. Version matching strategy and limitations

A logical node ID is deterministic from the document key and a path-like key containing section number and normalized heading. A separate database row exists for each version. This preserves identity when the body changes but the section number/title stay stable. Content hashes are computed from normalized body text; a hash mismatch marks a source as changed. Newly added sections are created in the new version; old version rows are never overwritten.

**Known limitation:** a heading rename or section renumbering changes the logical ID and can look like a removed node plus a new node, even when the content is semantically equivalent. Repeated identical section numbers/titles in a malformed source could also collide under the unique key constraint. A more advanced matcher could use parent-path similarity, heading embeddings, and text similarity, but fuzzy matching can wrongly merge two similar requirements. This implementation prefers transparent false negatives over silently merging distinct requirements.

## 6. Selection, generation, and malformed LLM output

A selection is constrained to one document version. It stores exact text/hash snapshots for each selected node. Generation reconstructs the source from those snapshots, not from the current latest version. The default generator is deterministic and offline so reviewers can execute the project without credentials. Optional Groq-compatible mode uses a strict JSON prompt, Pydantic validation, and one retry with a correction instruction. If the provider still returns malformed/incomplete JSON, the endpoint returns HTTP 502 and does not persist the invalid output.

Repeated generation for the same selection is idempotent by default: it returns the most recent generation. `force_new=true` explicitly requests a new generation. This avoids accidentally creating duplicate outputs during retries while preserving an escape hatch for intentional regeneration.

The generated cases are suggestions, not validated test protocols. A qualified engineer should review each one, especially those involving safety thresholds.

## 7. Staleness / impact detection

At retrieval time, each generation source snapshot is compared with the latest node having the same logical ID. If the latest node is absent or its body hash differs, the generation is marked stale and a reason is returned. This makes the status visible on `/generations`, `/generations/{generation_id}`, and the node-based retrieval route. The original source snapshot remains attached to the generation regardless of re-ingestion.

This is a conservative binary signal: a one-word wording change and a changed numeric threshold both trigger staleness. It does not decide clinical significance. A future enhancement could classify semantic impact and highlight changed numeric values, units, thresholds, and negation words; the binary hash check should still remain as a reliable baseline.

## 8. Validation and debugging process

1. Inspected the text layer of both PDFs and compared their section order/content.
2. Added explicit parser tests for missing intermediate heading, out-of-order subsection numbering, and repeated heading labels.
3. Added version-difference assertions for battery life, cuff inflation increments, and the v2-only `5.3 Data Export` section.
4. Added API integration tests that ingest v1, create a selection, generate test ideas, ingest v2, and assert that the earlier generation is marked stale.
5. Exposed content hashes, version numbers, page ranges, and diff lines through the API to make parser and matching behavior inspectable instead of hiding uncertainty.

## 9. Required decision log

1. **Most likely silent failure:** incorrect parent assignment or a table value accidentally attached to the wrong section can produce valid-looking output. I would catch this with structural invariants, page-by-page source comparison, explicit edge-case tests, and a review screen/report for ambiguous table blocks.
2. **Simplicity chosen over full correctness:** the table recognizer and logical-node matcher are intentionally heuristic. A production document with a renamed/renumbered section or a multi-column table could be misclassified; visual-layout-aware extraction and a human review queue should be the first upgrades.
3. **Unhandled input:** a scanned page where Tesseract is missing or OCR confidence is poor is not guaranteed to parse correctly. The parser tries OCR, records pages where OCR was used, and leaves an empty page visible in diagnostics rather than claiming full fidelity.

## 10. What I would do with more time

- Extract tables with coordinate-aware row/cell detection and add golden-file assertions for key table values.
- Add OCR confidence and extraction warnings per page/node.
- Improve logical-node matching with parent path + token similarity and require human confirmation for ambiguous matches.
- Add concurrency-safe document storage and migrations, audit events, pagination, and API-level size limits.
- Add a richer semantic impact classifier for thresholds/units/negation, while retaining exact hashes as the source-of-truth change signal.
- Add a reviewed test-case schema with unique case IDs, severity rationale, source citations, and validation against actual requirements.
