from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class IngestRequest(BaseModel):
    file_path: str = Field(description="Path to a PDF accessible to the API process")
    document_key: str = "ct200"

class SelectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    node_ids: list[int] = Field(min_length=1)

class TestCase(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    requirement: str = Field(min_length=3)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=3)
    priority: Literal["low", "medium", "high", "critical"] = "medium"

class GenerationOutput(BaseModel):
    test_cases: list[TestCase] = Field(min_length=3, max_length=5)

class GenerateRequest(BaseModel):
    selection_id: int
    force_new: bool = False

class SelectionItemOut(BaseModel):
    node_id: int
    version_id: int
    logical_id: str
    heading: str
    content_hash: str
