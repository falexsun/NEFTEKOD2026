"""Training and model metadata schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TrainingRun(BaseModel):
    """Record of a training run."""
    model_version: str
    parent_model_version: str | None = None
    dataset_version: str = "unknown"
    feature_pipeline_version: str = "1.0"
    git_commit_hash: str | None = None
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    random_seed: int = 42
    training_start: datetime | None = None
    training_end: datetime | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    model_type: str = "unknown"
    status: str = "pending"  # pending | running | completed | failed


class ModelMetadata(BaseModel):
    """Metadata for a registered model."""
    model_version: str
    model_type: str  # catboost | lightgbm | xgboost
    alias: str = "candidate"  # champion | candidate | archived
    target: str = "sulfur"
    metrics: dict[str, float] = Field(default_factory=dict)
    training_timestamp: datetime | None = None
    artifact_path: str | None = None
    promoted: bool = False
    promotion_timestamp: datetime | None = None
