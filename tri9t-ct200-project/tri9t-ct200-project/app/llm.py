from __future__ import annotations
import json, re
from typing import Any
import httpx
from pydantic import ValidationError
from app.config import settings
from app.schemas import GenerationOutput

SYSTEM_PROMPT = """You are a careful QA engineer for a fictional medical device manual. Create 3 to 5 concrete, repeatable test-case ideas grounded ONLY in supplied source text. Do not invent requirements. Return JSON only with this shape: {\"test_cases\":[{\"title\":str,\"requirement\":str,\"preconditions\":[str],\"steps\":[str],\"expected_result\":str,\"priority\":\"low|medium|high|critical\"}]}. Each case needs actionable steps and an observable expected result. Do not present these as validated clinical tests."""

def _mock_cases(source: str) -> dict[str, Any]:
    # Deterministic, offline-safe mode makes the repository runnable without credentials.
    snippets = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", source) if len(s.strip()) > 25]
    selected = snippets[:5]
    if not selected: selected = [source[:500] or "Selected requirement text"]
    cases = []
    for i, snippet in enumerate(selected[:5]):
        cases.append({
            "title": f"Verify selected requirement {i+1}",
            "requirement": snippet[:700],
            "preconditions": ["Use a controlled test setup and the selected manual version."],
            "steps": ["Prepare the device or test fixture for the stated requirement.", f"Exercise the behavior described by: {snippet[:240]}", "Record the observed result and compare it with the requirement."],
            "expected_result": "Observed behavior matches the cited requirement; any mismatch is recorded as a defect.",
            "priority": "high" if re.search(r"pressure|alarm|error|safety|mmhg|deflat", snippet, re.I) else "medium"
        })
    while len(cases) < 3:
        cases.append({"title": f"Traceability check {len(cases)+1}", "requirement": source[:500] or "Selected source text", "preconditions": ["Selected source version is available."], "steps": ["Retrieve the selected node and its version.", "Compare the stored source snapshot with the selected version."], "expected_result": "The test case points to the exact source version and content hash.", "priority": "medium"})
    return {"test_cases": cases}

def generate_cases(source: str) -> tuple[GenerationOutput, str]:
    if settings.llm_provider.lower() != "groq" or not settings.llm_api_key.strip():
        return GenerationOutput.model_validate(_mock_cases(source)), "mock"
    payload = {"model": settings.llm_model, "temperature": 0.1, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "SOURCE DOCUMENT EXCERPT:\n" + source + "\nReturn only the requested JSON object."}], "response_format": {"type": "json_object"}}
    last_error = None
    for attempt in range(2):
        try:
            response = httpx.post(settings.llm_base_url.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {settings.llm_api_key}"}, json=payload, timeout=45)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            validated = GenerationOutput.model_validate(parsed)
            return validated, "groq"
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, ValidationError, TypeError) as exc:
            last_error = str(exc)
            payload["messages"].append({"role": "user", "content": "Your previous output failed validation. Return corrected JSON only, with 3-5 valid test_cases and all required fields."})
    raise RuntimeError(f"LLM output failed after one retry; no generation was saved. Last error: {last_error}")
