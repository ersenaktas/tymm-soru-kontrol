from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import uuid

@dataclass
class ReviewJob:
    path: Path
    # A staged upload has a random on-disk name for isolation.  Keep the
    # teacher-facing source name separately so reports never expose that name.
    display_name: str | None = None
    subject: str = "auto"
    subject_path: Path | None = None
    subject_label: str | None = None
    temporary_input: bool = False
    temporary_subject: bool = False
    # By default an identical input/rules/source combination reuses its
    # verified report.  Teachers can explicitly request a fresh NotebookLM
    # run from the web form when they want a second opinion.
    force_refresh: bool = False
    # V7 performs the complete internal review and exposes one fixed report:
    # actionable findings plus genuinely unreviewable criteria.
    report_mode: str = "issues"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

@dataclass
class ReviewResult:
    job_id: str
    source_name: str
    markdown: str
    docx_path: Path | None = None
    pdf_path: Path | None = None
    markdown_path: Path | None = None
    json_path: Path | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
