"""Bounded private-draft requirements. These fields never grant tool access."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ShortRequirement = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
]


class TaskRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    missing_facts: list[ShortRequirement] = Field(max_length=6)
    expected_output: str = Field(min_length=1, max_length=600)
    completion_criteria: list[ShortRequirement] = Field(min_length=1, max_length=6)
    independent: Literal[True]

    @field_validator("independent", mode="before")
    @classmethod
    def only_independent_drafts(cls, value):
        if value is not True:
            raise ValueError("task must be independently executable")
        return value
