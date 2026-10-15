from pydantic import BaseModel, Field


class ProjectInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    file_count: int = 0
    created_at: float
    last_analysis: str | None = None


class SmellItem(BaseModel):
    type: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str = ""


class ReadabilityBreakdown(BaseModel):
    metric: str
    score: float
    weight: int
    detail: str = ""


class ReadabilityReport(BaseModel):
    total: float
    grade: str
    breakdown: list[ReadabilityBreakdown] = []


class ProjectStats(BaseModel):
    total_files: int
    total_lines: int
    total_functions: int
    total_classes: int
    avg_complexity: float
    comment_ratio: float


class AnalysisResult(BaseModel):
    project_id: str
    project_name: str
    stats: ProjectStats
    readability: ReadabilityReport
    smells: list[SmellItem]
    analyzed_at: str


class FileNode(BaseModel):
    rel_path: str
    size: int = 0


class GenerateTestsRequest(BaseModel):
    file: str
    functions: list[str] = Field(default_factory=list)


class AdviceRequest(BaseModel):
    file: str
    smell_types: list[str] = Field(default_factory=list)


class RunTestsRequest(BaseModel):
    project_id: str
    test_file: str = ""

class FixRequest(BaseModel):
    file: str
    apply: bool = False


class SingleFileAnalysisRequest(BaseModel):
    file: str


class SecurityIssue(BaseModel):
    type: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str = ""


class FunctionComplexityItem(BaseModel):
    name: str
    file: str
    line: int
    complexity: int
    length: int
    nesting: int
    bucket: str