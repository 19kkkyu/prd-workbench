"""Strict persistence boundary: no original bytes, parsed text, images, or transcripts."""
from pydantic import BaseModel,ConfigDict


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Overview(Strict):
    title:str
    document_type:str
    summary:str
    background:str
    goals:str
    users:str
    scope:str
    workflow:str
    metrics:str


class SavedRequirement(Strict):
    id:str
    module:str
    title:str
    description:str
    roles:str
    scenario:str
    rules:str
    exceptions:str
    acceptance:str
    priority:str
    sources:list[str]


class ProductReport(Overview):
    requirements:list[SavedRequirement]


class Product(Strict):
    name:str
    document_names:list[str]
    report:ProductReport
    reading_notes:list[str]


class Summary(Strict):
    overview:Overview
    products:list[Product]


class Snapshot(Strict):
    id:str
    project_id:str
    project_name:str
    created:str
    provider:str
    model:str
    report:Summary
    schema_version:int=3


def validate_run(run):
    return Snapshot.model_validate(run).model_dump()
