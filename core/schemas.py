"""
Data contracts and strict Pydantic v2 models for Competitor Changelog Scout.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class FeatureStatus(str, Enum):
    """Lifecycle status of a competitor feature."""
    SHIPPED = "shipped"
    ANNOUNCED = "announced"
    UNCERTAIN = "uncertain"


class ActionType(str, Enum):
    """Categorized action proposal evaluated by deterministic decision rules."""
    ADD_NEW = "ADD_NEW"
    ADD_ANNOUNCED = "ADD_ANNOUNCED"
    RENAME_ALIAS = "RENAME_ALIAS"
    FLAG_UNCERTAIN = "FLAG_UNCERTAIN"


class Competitor(BaseModel):
    """Competitor entity configuration."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    changelog_url: str
    blog_url: Optional[str] = None


class ExistingFeature(BaseModel):
    """Feature entity stored in historical registry."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    competitor_id: str
    aliases: List[str] = Field(default_factory=list)
    status: FeatureStatus
    last_updated: datetime = Field(default_factory=utc_now)
    source_url: str


class RawScrapedItem(BaseModel):
    """Raw scraped content from competitor changelog or marketing feed."""
    model_config = ConfigDict(from_attributes=True)

    source_url: str
    title: str
    raw_content: str
    is_changelog: bool = True
    http_status: int = 200
    fetch_error: Optional[str] = None
    scraped_at: datetime = Field(default_factory=utc_now)


class StagedProposal(BaseModel):
    """Evaluated proposal staged for human review before execution."""
    model_config = ConfigDict(from_attributes=True)

    proposal_id: str
    competitor_id: str
    action_type: ActionType
    target_feature_id: Optional[str] = None
    feature_name: str
    status: FeatureStatus
    confidence: float
    reasoning: str
    evidence_quote: str
    source_url: str
    content_hash: str
    approved: bool = False


class VerificationReceipt(BaseModel):
    """Independent post-write cryptographic state verification receipt."""
    model_config = ConfigDict(from_attributes=True)

    verification_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    row_count_before: int
    row_count_after: int
    hash_match: bool
    verified_features: List[str] = Field(default_factory=list)
    status: str
