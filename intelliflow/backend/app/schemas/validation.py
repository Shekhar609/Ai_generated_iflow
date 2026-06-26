from __future__ import annotations

from pydantic import BaseModel, Field


class ValidateXmlIn(BaseModel):
    xml: str = Field(..., min_length=1)
    xsd_base64: str | None = None
    required_fields: list[str] = Field(default_factory=list)


class ValidationError(BaseModel):
    level: str
    message: str
    xpath: str | None = None
    line: int | None = None


class ValidateXmlOut(BaseModel):
    valid: bool
    errors: list[ValidationError]


class FixXmlIn(BaseModel):
    xml: str = Field(..., min_length=1)
    error_message: str = Field(..., min_length=1)
    xsd_base64: str | None = None


class FixXmlOut(BaseModel):
    root_cause: str
    corrected_xml: str
    diff: str
    citations: list[dict]
    still_invalid: bool = False
    remaining_errors: list[ValidationError] = Field(default_factory=list)
