from pydantic import BaseModel, Field


class Clause(BaseModel):
    id: str
    heading: str | None = None
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)


class ParsedDocument(BaseModel):
    filename: str
    content_type: str
    text: str
    page_texts: list[str] = Field(default_factory=list)
    clauses: list[Clause] = Field(default_factory=list)
    definitions: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
