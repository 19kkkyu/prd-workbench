from pydantic import BaseModel, ConfigDict

class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: str
    title: str
    description: str
    roles: str
    scenario: str
    rules: str
    exceptions: str
    acceptance: str
    priority: str
    sources: list[str]
    evidence: str


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    document_type: str
    summary: str
    background: str
    goals: str
    users: str
    scope: str
    workflow: str
    metrics: str
    requirements: list[Requirement]


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    sources: list[str]


class VisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcription: str
    visual_description: str
    limitations: str


