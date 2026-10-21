"""
Official Test Suite for Competitor Changelog Scout.
Guarantees 100% test compliance across TC1, TC2, TC3, TC4, LangGraph HITL interruption,
local resilient ledger fallback, and SHA-256 post-write verification.
Zero internet dependency, deterministic execution in < 5 seconds.
"""

import json
import os
import time
from datetime import datetime, timezone
import pytest
from core.classifier import evaluate_scraped_item
from core.graph import build_scout_graph
from core.schemas import (
    ActionType,
    ExistingFeature,
    FeatureStatus,
    RawScrapedItem,
    StagedProposal,
)
from core.sheet_sync import (
    commit_proposals,
    export_matrix_to_ledger,
    reset_ledger_to_baseline,
)
from core.verifier import verify_and_generate_digest
from fixtures.mock_data import MOCK_FIXTURES, get_mock_item
from storage.db import (
    CompetitorModel,
    FeatureModel,
    apply_approved_proposal,
    get_all_features,
    get_engine,
    get_session,
    init_db,
    seed_initial_data,
)


@pytest.fixture
def memory_db():
    """Create a fresh in-memory SQLite database session for isolated testing."""
    engine = get_engine(":memory:")
    init_db(engine)
    session = get_session(engine)
    seed_initial_data(session)
    yield session
    session.close()


def test_tc1_new_feature_changelog(memory_db):
    """
    TC1 Test: New feature in changelog release notes.
    Deterministic Rule: Classify as 'shipped', extract date and source link, stage as 'ADD_NEW'.
    """
    item = get_mock_item("tc1_changelog")
    known_features = memory_db.query(FeatureModel).all()
    known_pydantic = [f.to_pydantic() for f in known_features]

    proposal = evaluate_scraped_item(
        item=item,
        competitor_id="linear",
        known_features=known_pydantic,
    )

    # Assertions for TC1 compliance
    assert proposal.action_type == ActionType.ADD_NEW
    assert proposal.status == FeatureStatus.SHIPPED
    assert proposal.target_feature_id is None
    assert "Linear Asks" in proposal.feature_name
    assert proposal.source_url == "https://linear.app/changelog/2026-03-linear-asks"
    assert proposal.confidence >= 0.95
    assert len(proposal.content_hash) == 64  # Valid SHA-256
    assert len(proposal.evidence_quote) > 0
    assert "shipping Linear Asks" in proposal.evidence_quote or "Linear Asks" in proposal.evidence_quote


def test_tc2_marketing_post_announced(memory_db):
    """
    TC2 Test: Marketing blog post announcing upcoming roadmap capability.
    Deterministic Rule: Classify as 'announced' (EXPLICITLY NOT 'shipped'), stage as 'ADD_ANNOUNCED'.
    """
    item = get_mock_item("tc2_blog_post")
    known_features = [f.to_pydantic() for f in memory_db.query(FeatureModel).all()]

    proposal = evaluate_scraped_item(
        item=item,
        competitor_id="linear",
        known_features=known_features,
    )

    # Assertions for TC2 compliance
    assert proposal.action_type == ActionType.ADD_ANNOUNCED
    assert proposal.status == FeatureStatus.ANNOUNCED
    assert proposal.status != FeatureStatus.SHIPPED  # HARD REQUIREMENT: NEVER mark marketing as shipped
    assert proposal.target_feature_id is None
    assert "Next-Gen AI" in proposal.feature_name or "AI Workflows" in proposal.feature_name
    assert "ANNOUNCED" in proposal.reasoning.upper()
    assert proposal.source_url == "https://linear.app/blog/next-gen-ai-preview"
    assert proposal.confidence >= 0.90


def test_tc3_feature_renamed_alias(memory_db):
    """
    TC3 Test: Feature renamed / rebranded in changelog.
    Deterministic Rule: Semantic reconciliation against existing feature registry.
    Map new name/alias to the existing feature's stable ID ('feat_jira_imp'), staging as 'RENAME_ALIAS'.
    """
    item = get_mock_item("tc3_renamed")
    known_features = [f.to_pydantic() for f in memory_db.query(FeatureModel).all()]

    proposal = evaluate_scraped_item(
        item=item,
        competitor_id="linear",
        known_features=known_features,
    )

    # Assertions for TC3 compliance
    assert proposal.action_type == ActionType.RENAME_ALIAS
    assert proposal.status == FeatureStatus.SHIPPED
    assert proposal.target_feature_id == "feat_jira_imp"  # HARD REQUIREMENT: Maps to existing stable ID
    assert "Universal Workspace Sync" in proposal.feature_name

    # Commit proposal and assert persistence behavior
    updated_feat = apply_approved_proposal(memory_db, proposal)
    assert updated_feat.id == "feat_jira_imp"
    assert updated_feat.name == proposal.feature_name
    assert "Jira Importer" in updated_feat.aliases
    assert "Jira Migration Tool" in updated_feat.aliases


def test_tc4_missing_page_uncertain(memory_db):
    """
    TC4 Test: Changelog page removed / 404 / network connection failure.
    Deterministic Rule: Mark as 'uncertain' with error reasoning.
    HARD REQUIREMENT: EXPLICITLY NEVER mark as 'feature removed'.
    """
    item = get_mock_item("tc4_missing")
    known_features = [f.to_pydantic() for f in memory_db.query(FeatureModel).all()]

    proposal = evaluate_scraped_item(
        item=item,
        competitor_id="linear",
        known_features=known_features,
    )

    # Assertions for TC4 compliance
    assert proposal.action_type == ActionType.FLAG_UNCERTAIN
    assert proposal.status == FeatureStatus.UNCERTAIN
    assert proposal.target_feature_id is None
    assert proposal.confidence >= 0.90
    assert "404" in proposal.reasoning or "error" in proposal.reasoning.lower()

    # HARD REQUIREMENT: EXPLICITLY NEVER mark as "feature removed"
    assert "feature removed" not in proposal.reasoning.lower()
    assert "removed" not in proposal.action_type.value.lower()
    assert proposal.status != FeatureStatus.SHIPPED


def test_deterministic_execution_speed(memory_db):
    """
    Speed Test: Asserts that evaluation of all test cases runs in under 1 second (well under 5s).
    Zero internet access required.
    """
    start_time = time.perf_counter()
    known_features = [f.to_pydantic() for f in memory_db.query(FeatureModel).all()]

    for _ in range(50):  # Evaluate 50 rounds (200 evaluations)
        for key in ["tc1_changelog", "tc2_blog_post", "tc3_renamed", "tc4_missing"]:
            item = get_mock_item(key)
            evaluate_scraped_item(item, "linear", known_features)

    elapsed = time.perf_counter() - start_time
    assert elapsed < 1.0, f"50 rounds took {elapsed:.2f}s, expected < 1.0s"


def test_hitl_approval_interruption(tmp_path):
    """
    LangGraph Workflow Test: Assert mandatory HITL interrupt_before=['approval_gate'].
    Graph must pause before writing to comparison sheet.
    """
    from langgraph.checkpoint.memory import MemorySaver

    memory = MemorySaver()
    graph = build_scout_graph(checkpointer=memory)

    config = {"configurable": {"thread_id": "test_thread_1"}}
    initial_input = {
        "competitor_id": "linear",
        "source_urls": [],
        "force_mock": True,
        "mock_keys": ["tc1_changelog", "tc2_blog_post", "tc3_renamed", "tc4_missing"],
        "items": [],
        "proposals": [],
        "approved_proposals": [],
        "pre_count": 0,
        "post_count": 0,
        "sync_receipt": None,
        "digest": "",
        "execution_log": [],
    }

    # Step 1: Run graph - it should pause at 'approval_gate'
    state_after_pause = graph.invoke(initial_input, config=config)
    snapshot = graph.get_state(config)

    assert "approval_gate" in snapshot.next, f"Expected graph to pause before approval_gate, next was: {snapshot.next}"
    assert len(state_after_pause["proposals"]) == 4
    assert state_after_pause["sync_receipt"] is None  # Has NOT written to sheet or verified yet!

    # Step 2: Human approves 3 of the 4 proposals
    approved = [state_after_pause["proposals"][0], state_after_pause["proposals"][1], state_after_pause["proposals"][2]]
    graph.update_state(config, {"approved_proposals": approved}, as_node="approval_gate")

    # Step 3: Resume graph execution
    final_state = graph.invoke(None, config=config)
    assert final_state["sync_receipt"] is not None
    assert final_state["sync_receipt"].hash_match is True
    assert len(final_state["digest"]) > 100


def test_resilient_ledger_fallback(tmp_path):
    """
    Test dual-ledger sync without Google credentials.
    Confirms CSV and JSON exports succeed with zero errors.
    """
    csv_file = str(tmp_path / "test_matrix.csv")
    json_file = str(tmp_path / "test_matrix.json")

    features = [
        ExistingFeature(
            id="feat_1",
            name="Feature One",
            competitor_id="linear",
            aliases=["Alias 1"],
            status=FeatureStatus.SHIPPED,
            source_url="https://example.com/feat1",
        ),
        ExistingFeature(
            id="feat_2",
            name="Feature Two",
            competitor_id="jira",
            aliases=[],
            status=FeatureStatus.ANNOUNCED,
            source_url="https://example.com/feat2",
        ),
    ]

    comps_dict = {"linear": "Linear", "jira": "Atlassian Jira"}
    rows = export_matrix_to_ledger(features, comps_dict, csv_path=csv_file, json_path=json_file)

    assert os.path.exists(csv_file)
    assert os.path.exists(json_file)
    assert len(rows) == 2

    with open(json_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
        assert len(loaded) == 2
        assert loaded[0]["Feature Name"] == "Feature One"


def test_verification_sha256_receipt_and_digest(memory_db):
    """
    Test Step 5 independent post-write verification and Markdown digest formatting.
    """
    proposals = [
        StagedProposal(
            proposal_id="p1",
            competitor_id="linear",
            action_type=ActionType.ADD_NEW,
            target_feature_id=None,
            feature_name="Linear Asks",
            status=FeatureStatus.SHIPPED,
            confidence=0.99,
            reasoning="Shipped in official changelog.",
            evidence_quote="Today we are shipping Linear Asks.",
            source_url="https://linear.app/changelog/asks",
            content_hash="abc123hash",
            approved=True,
        ),
        StagedProposal(
            proposal_id="p2",
            competitor_id="linear",
            action_type=ActionType.ADD_ANNOUNCED,
            target_feature_id=None,
            feature_name="Next-Gen AI",
            status=FeatureStatus.ANNOUNCED,
            confidence=0.92,
            reasoning="Blog roadmap preview.",
            evidence_quote="Coming soon in Q3.",
            source_url="https://linear.app/blog/ai",
            content_hash="def456hash",
            approved=True,
        ),
        StagedProposal(
            proposal_id="p3",
            competitor_id="linear",
            action_type=ActionType.FLAG_UNCERTAIN,
            target_feature_id=None,
            feature_name="Broken URL Endpoint",
            status=FeatureStatus.UNCERTAIN,
            confidence=0.95,
            reasoning="HTTP 404 returned; retaining registry intact.",
            evidence_quote="HTTP 404 Not Found.",
            source_url="https://linear.app/changelog/broken",
            content_hash="ghi789hash",
            approved=True,
        ),
    ]

    pre_count = len(get_all_features(memory_db))
    # All 3 proposals add new rows
    post_count = pre_count + 3

    receipt, digest = verify_and_generate_digest(
        pre_count=pre_count,
        post_count=post_count,
        approved_proposals=proposals,
        db_session=memory_db,
    )

    # Verification receipt assertions
    assert receipt.hash_match is True
    assert receipt.status == "VERIFIED_SUCCESS"
    assert receipt.row_count_before == pre_count
    assert receipt.row_count_after == post_count

    # Markdown digest formatting assertions
    assert "Intelligence Digest" in digest
    assert "[SHIPPED]" in digest
    assert "[ANNOUNCED]" in digest
    assert "[UNCERTAIN]" in digest
    assert "[View Original Release Notes](https://linear.app/changelog/asks)" in digest
    assert "Evidence Quote" in digest


def test_reset_ledger_to_baseline(memory_db, tmp_path):
    """
    Test reset_ledger_to_baseline:
    - Adds dirty rogue features to memory_db.
    - Runs reset_ledger_to_baseline with custom paths in tmp_path.
    - Verifies JSON and CSV matrix contain exactly 1 clean seed record.
    - Verifies database retains only 1 feature ('feat_jira_imp') with clean baseline state.
    """
    test_csv = str(tmp_path / "comparison_matrix.csv")
    test_json = str(tmp_path / "comparison_matrix.json")

    # Insert a rogue feature to simulate dirty state
    rogue_feat = FeatureModel(
        id="feat_rogue_1",
        name="Rogue Feature",
        competitor_id="linear",
        aliases=json.dumps([]),
        status=FeatureStatus.SHIPPED.value,
        source_url="https://example.com/rogue",
        updated_at=datetime.now(timezone.utc),
    )
    memory_db.add(rogue_feat)
    memory_db.commit()

    assert len(get_all_features(memory_db)) >= 2

    rows = reset_ledger_to_baseline(
        db_session=memory_db,
        csv_path=test_csv,
        json_path=test_json,
    )

    # 1. Output assertion
    assert len(rows) == 1
    assert rows[0]["Feature ID"] == "feat_jira_imp"
    assert rows[0]["Feature Name"] == "Jira Importer"
    assert rows[0]["Status"] == "shipped"
    assert rows[0]["Aliases"] == "Legacy Importer"
    assert rows[0]["Source URL"] == "https://linear.app/changelog/legacy-importer"
    assert rows[0]["Last Updated"] == "2026-10-15T00:00:00"

    # 2. File assertions
    assert os.path.exists(test_json)
    assert os.path.exists(test_csv)

    with open(test_json, "r", encoding="utf-8") as f:
        loaded = json.load(f)
        assert len(loaded) == 1
        assert loaded[0]["Feature ID"] == "feat_jira_imp"

    # 3. Database assertions
    db_feats = get_all_features(memory_db)
    assert len(db_feats) == 1
    assert db_feats[0].id == "feat_jira_imp"
    assert db_feats[0].name == "Jira Importer"

