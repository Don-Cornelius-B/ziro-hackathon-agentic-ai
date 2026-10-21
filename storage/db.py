"""
SQLite repository with SQLAlchemy 2.0 for state, feature registry, proposals, and snapshots.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from core.schemas import ActionType, ExistingFeature, FeatureStatus, StagedProposal

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "scout.db")


class Base(DeclarativeBase):
    pass


class CompetitorModel(Base):
    __tablename__ = "competitors"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    changelog_url = Column(String(512), nullable=False)
    blog_url = Column(String(512), nullable=True)


class FeatureModel(Base):
    __tablename__ = "features"

    id = Column(String(64), primary_key=True)
    name = Column(String(256), nullable=False)
    competitor_id = Column(String(64), ForeignKey("competitors.id"), nullable=False)
    aliases = Column(Text, default="[]", nullable=False)  # JSON-encoded string
    status = Column(String(32), nullable=False)
    source_url = Column(String(512), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_pydantic(self) -> ExistingFeature:
        alias_list = json.loads(self.aliases) if self.aliases else []
        return ExistingFeature(
            id=self.id,
            name=self.name,
            competitor_id=self.competitor_id,
            aliases=alias_list,
            status=FeatureStatus(self.status),
            last_updated=self.updated_at if self.updated_at.tzinfo else self.updated_at.replace(tzinfo=timezone.utc),
            source_url=self.source_url,
        )


class ProposalModel(Base):
    __tablename__ = "proposals"

    proposal_id = Column(String(64), primary_key=True)
    competitor_id = Column(String(64), nullable=False)
    action_type = Column(String(32), nullable=False)
    target_feature_id = Column(String(64), nullable=True)
    feature_name = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    evidence_quote = Column(Text, nullable=False)
    source_url = Column(String(512), nullable=False)
    content_hash = Column(String(64), nullable=False)
    approved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_pydantic(self) -> StagedProposal:
        return StagedProposal(
            proposal_id=self.proposal_id,
            competitor_id=self.competitor_id,
            action_type=ActionType(self.action_type),
            target_feature_id=self.target_feature_id,
            feature_name=self.feature_name,
            status=FeatureStatus(self.status),
            confidence=self.confidence,
            reasoning=self.reasoning,
            evidence_quote=self.evidence_quote,
            source_url=self.source_url,
            content_hash=self.content_hash,
            approved=self.approved,
        )


class WeeklySnapshotModel(Base):
    __tablename__ = "weekly_snapshots"

    snapshot_id = Column(String(64), primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    state_hash = Column(String(64), nullable=False)
    row_count = Column(Integer, nullable=False)
    matrix_json = Column(Text, nullable=False)


def get_engine(db_path: Optional[str] = None):
    """Create SQLite SQLAlchemy engine."""
    path = db_path or DEFAULT_DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        sqlite_url = f"sqlite:///{os.path.abspath(path)}"
    else:
        sqlite_url = "sqlite:///:memory:"
    return create_engine(sqlite_url, echo=False)


def get_session(engine=None) -> Session:
    """Acquire a new SQLAlchemy session."""
    if engine is None:
        engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def init_db(engine=None):
    """Initialize database tables."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(bind=engine)


def seed_initial_data(session: Session):
    """
    Populate standard competitors (Linear, Jira, Supabase) and
    seed feature feat_jira_imp ('Jira Importer') for TC3 rename verification.
    """
    # 1. Seed Competitors
    competitors = [
        CompetitorModel(
            id="linear",
            name="Linear",
            changelog_url="https://linear.app/changelog",
            blog_url="https://linear.app/blog",
        ),
        CompetitorModel(
            id="jira",
            name="Atlassian Jira",
            changelog_url="https://confluence.atlassian.com/jirasoftware/jira-software-release-notes",
            blog_url="https://www.atlassian.com/blog/jira-software",
        ),
        CompetitorModel(
            id="supabase",
            name="Supabase",
            changelog_url="https://supabase.com/changelog",
            blog_url="https://supabase.com/blog",
        ),
    ]

    for comp in competitors:
        existing = session.get(CompetitorModel, comp.id)
        if not existing:
            session.add(comp)

    # 2. Seed Feature feat_jira_imp for TC3 testing
    seed_feature = session.get(FeatureModel, "feat_jira_imp")
    if not seed_feature:
        seed_feature = FeatureModel(
            id="feat_jira_imp",
            name="Jira Importer",
            competitor_id="linear",
            aliases=json.dumps(["Jira Migration Tool"]),
            status=FeatureStatus.SHIPPED.value,
            source_url="https://linear.app/changelog/2023-01-jira-importer",
            updated_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        session.add(seed_feature)

    session.commit()


def reset_db_to_baseline(session: Session):
    """
    Reset SQLite database to clean seed baseline:
    - Clear all proposals from ProposalModel.
    - Clear audit snapshots from WeeklySnapshotModel.
    - Remove all non-seed features from FeatureModel.
    - Restore seed feature 'feat_jira_imp' to clean baseline state.
    - Ensure standard competitors (linear, jira, supabase) are seeded.
    - Explicitly commit and expire all cached instances in the session identity map.
    """
    # 1. Clear rogue test proposals
    session.query(ProposalModel).delete()

    # 2. Clear snapshots
    session.query(WeeklySnapshotModel).delete()

    # 3. Clear non-seed features
    session.query(FeatureModel).filter(FeatureModel.id != "feat_jira_imp").delete()

    # 4. Restore feat_jira_imp to clean baseline state
    seed_feature = session.get(FeatureModel, "feat_jira_imp")
    if seed_feature:
        seed_feature.name = "Jira Importer"
        seed_feature.competitor_id = "linear"
        seed_feature.aliases = json.dumps(["Legacy Importer"])
        seed_feature.status = FeatureStatus.SHIPPED.value
        seed_feature.source_url = "https://linear.app/changelog/legacy-importer"
        seed_feature.updated_at = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
    else:
        seed_feature = FeatureModel(
            id="feat_jira_imp",
            name="Jira Importer",
            competitor_id="linear",
            aliases=json.dumps(["Legacy Importer"]),
            status=FeatureStatus.SHIPPED.value,
            source_url="https://linear.app/changelog/legacy-importer",
            updated_at=datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc),
        )
        session.add(seed_feature)

    # 5. Ensure standard competitors exist
    competitors = [
        CompetitorModel(
            id="linear",
            name="Linear",
            changelog_url="https://linear.app/changelog",
            blog_url="https://linear.app/blog",
        ),
        CompetitorModel(
            id="jira",
            name="Atlassian Jira",
            changelog_url="https://confluence.atlassian.com/jirasoftware/jira-software-release-notes",
            blog_url="https://www.atlassian.com/blog/jira-software",
        ),
        CompetitorModel(
            id="supabase",
            name="Supabase",
            changelog_url="https://supabase.com/changelog",
            blog_url="https://supabase.com/blog",
        ),
    ]

    for comp in competitors:
        existing = session.get(CompetitorModel, comp.id)
        if not existing:
            session.add(comp)

    session.commit()
    session.expire_all()


def get_known_features(session: Session, competitor_id: Optional[str] = None) -> List[ExistingFeature]:
    """Retrieve known features from registry, optionally filtered by competitor."""
    stmt = select(FeatureModel)
    if competitor_id:
        stmt = stmt.where(FeatureModel.competitor_id == competitor_id)
    models = session.scalars(stmt).all()
    return [m.to_pydantic() for m in models]


def get_all_features(session: Session) -> List[ExistingFeature]:
    """Retrieve all features across all competitors."""
    return get_known_features(session, competitor_id=None)


def save_proposal(session: Session, proposal: StagedProposal):
    """Save or update a staged proposal in database."""
    existing = session.get(ProposalModel, proposal.proposal_id)
    if existing:
        existing.approved = proposal.approved
        existing.status = proposal.status.value
        existing.reasoning = proposal.reasoning
    else:
        model = ProposalModel(
            proposal_id=proposal.proposal_id,
            competitor_id=proposal.competitor_id,
            action_type=proposal.action_type.value,
            target_feature_id=proposal.target_feature_id,
            feature_name=proposal.feature_name,
            status=proposal.status.value,
            confidence=proposal.confidence,
            reasoning=proposal.reasoning,
            evidence_quote=proposal.evidence_quote,
            source_url=proposal.source_url,
            content_hash=proposal.content_hash,
            approved=proposal.approved,
            created_at=datetime.now(timezone.utc),
        )
        session.add(model)
    session.commit()


def get_all_proposals(session: Session, approved_only: bool = False) -> List[StagedProposal]:
    """Retrieve proposals from database."""
    stmt = select(ProposalModel)
    if approved_only:
        stmt = stmt.where(ProposalModel.approved == True)  # noqa: E712
    models = session.scalars(stmt).all()
    return [m.to_pydantic() for m in models]


def apply_approved_proposal(session: Session, proposal: StagedProposal) -> ExistingFeature:
    """
    Commit an approved proposal into the features registry.
    Handles RENAME_ALIAS (preserving stable ID), ADD_NEW, ADD_ANNOUNCED, and FLAG_UNCERTAIN.
    """
    now = datetime.now(timezone.utc)

    if proposal.action_type == ActionType.RENAME_ALIAS and proposal.target_feature_id:
        # Update existing feature: map new alias and update primary name
        target = session.get(FeatureModel, proposal.target_feature_id)
        if target:
            existing_aliases = json.loads(target.aliases) if target.aliases else []
            # Keep previous name in aliases if changing
            if target.name not in existing_aliases and target.name != proposal.feature_name:
                existing_aliases.append(target.name)
            if proposal.feature_name not in existing_aliases:
                existing_aliases.append(proposal.feature_name)

            target.name = proposal.feature_name
            target.aliases = json.dumps(existing_aliases)
            target.status = proposal.status.value
            target.source_url = proposal.source_url
            target.updated_at = now
            session.commit()
            return target.to_pydantic()

    # If ADD_NEW, ADD_ANNOUNCED, or FLAG_UNCERTAIN: create new feature record
    feature_id = proposal.target_feature_id or f"feat_{uuid.uuid4().hex[:10]}"
    new_feat = FeatureModel(
        id=feature_id,
        name=proposal.feature_name,
        competitor_id=proposal.competitor_id,
        aliases=json.dumps([]),
        status=proposal.status.value,
        source_url=proposal.source_url,
        updated_at=now,
    )
    session.add(new_feat)
    session.commit()
    return new_feat.to_pydantic()


def record_snapshot(session: Session, state_hash: str, row_count: int, matrix_json: str) -> str:
    """Record an audit snapshot in weekly_snapshots table."""
    snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
    snap = WeeklySnapshotModel(
        snapshot_id=snapshot_id,
        timestamp=datetime.now(timezone.utc),
        state_hash=state_hash,
        row_count=row_count,
        matrix_json=matrix_json,
    )
    session.add(snap)
    session.commit()
    return snapshot_id
