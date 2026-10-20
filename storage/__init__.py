"""
Competitor Changelog Scout - Storage Package
SQLAlchemy Database Repository for Features, Proposals, and State Snapshots
"""

from storage.db import (
    get_engine,
    get_session,
    init_db,
    seed_initial_data,
    get_known_features,
    get_all_features,
    save_proposal,
    apply_approved_proposal,
    record_snapshot,
    CompetitorModel,
    FeatureModel,
    ProposalModel,
    WeeklySnapshotModel,
)

__all__ = [
    "get_engine",
    "get_session",
    "init_db",
    "seed_initial_data",
    "get_known_features",
    "get_all_features",
    "save_proposal",
    "apply_approved_proposal",
    "record_snapshot",
    "CompetitorModel",
    "FeatureModel",
    "ProposalModel",
    "WeeklySnapshotModel",
]
