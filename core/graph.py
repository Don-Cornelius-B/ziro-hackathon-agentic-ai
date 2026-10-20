"""
LangGraph Orchestration State Machine with Human-in-the-Loop (HITL) Gate.
Coordinates Ingestion -> Classification -> Human Gate (Pause) -> Sheet Sync -> Verification.
Compiled with MemorySaver and interrupt_before=['approval_gate'].
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from core.classifier import evaluate_scraped_item
from core.ingestion import fetch_page
from core.schemas import RawScrapedItem, StagedProposal, VerificationReceipt
from core.sheet_sync import commit_proposals
from core.verifier import verify_and_generate_digest
from storage.db import (
    get_all_features,
    get_known_features,
    get_session,
    init_db,
    seed_initial_data,
)

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """Execution state schema for the LangGraph agent."""
    competitor_id: str
    source_urls: List[str]
    force_mock: bool
    mock_keys: List[str]
    items: List[RawScrapedItem]
    proposals: List[StagedProposal]
    approved_proposals: List[StagedProposal]
    pre_count: int
    post_count: int
    sync_receipt: Optional[VerificationReceipt]
    digest: str
    execution_log: List[str]


def node_ingest(state: AgentState) -> Dict[str, Any]:
    """Ingest competitor changelog entries and blog feeds."""
    logs = list(state.get("execution_log", []))
    competitor_id = state.get("competitor_id", "linear")
    force_mock = state.get("force_mock", False)
    mock_keys = state.get("mock_keys", [])
    source_urls = state.get("source_urls", [])

    logs.append(f"📡 [Ingestion] Starting intake for competitor '{competitor_id}' (mock_mode={force_mock})")

    scraped_items: List[RawScrapedItem] = []

    if force_mock:
        if not mock_keys:
            mock_keys = ["tc1_changelog", "tc2_blog_post", "tc3_renamed", "tc4_missing"]
        for key in mock_keys:
            item = fetch_page(url="", is_changelog=True, force_mock=True, mock_key=key)
            scraped_items.append(item)
            logs.append(f"  └── Loaded mock fixture '{key}': '{item.title}' (status={item.http_status})")
    else:
        for url in source_urls:
            is_changelog = "blog" not in url.lower()
            item = fetch_page(url=url, is_changelog=is_changelog, force_mock=False)
            scraped_items.append(item)
            logs.append(f"  └── Ingested '{url}': '{item.title}' (HTTP {item.http_status})")

    logs.append(f"✅ [Ingestion] Completed. Ingested {len(scraped_items)} raw items.")
    return {
        "items": scraped_items,
        "execution_log": logs,
    }


def node_classify(state: AgentState) -> Dict[str, Any]:
    """Apply deterministic decision rules (TC1-TC4) to all scraped items."""
    logs = list(state.get("execution_log", []))
    competitor_id = state.get("competitor_id", "linear")
    items = state.get("items", [])

    logs.append(f"🧠 [Classifier] Evaluating {len(items)} items using deterministic decision engine...")

    session = get_session()
    init_db()
    seed_initial_data(session)

    try:
        known_features = get_known_features(session, competitor_id)
        proposals: List[StagedProposal] = []

        for item in items:
            proposal = evaluate_scraped_item(item, competitor_id, known_features)
            proposals.append(proposal)
            logs.append(
                f"  ├── Rule applied: [{proposal.action_type.value}] -> '{proposal.feature_name}' "
                f"(Status: {proposal.status.value}, Confidence: {proposal.confidence * 100:.1f}%)"
            )

        logs.append(f"✅ [Classifier] Evaluation complete. Staged {len(proposals)} proposals.")
        return {
            "proposals": proposals,
            "execution_log": logs,
        }
    finally:
        session.close()


def node_approval_gate(state: AgentState) -> Dict[str, Any]:
    """Human-in-the-Loop pause gate. Pipeline interrupts here for explicit review."""
    logs = list(state.get("execution_log", []))
    proposals = state.get("proposals", [])
    logs.append(
        f"⏸️ [HITL Gate] Pausing execution for human review of {len(proposals)} staged proposals. "
        "Awaiting user confirmation before committing updates."
    )
    return {"execution_log": logs}


def node_sync_sheet(state: AgentState) -> Dict[str, Any]:
    """Batch-write approved proposals to SQLite and sheets/local matrix."""
    logs = list(state.get("execution_log", []))
    approved_proposals = state.get("approved_proposals", [])

    session = get_session()
    try:
        pre_count = len(get_all_features(session))
        logs.append(f"💾 [Action Engine] Committing {len(approved_proposals)} approved proposals (pre_count={pre_count})...")

        commit_proposals(approved_proposals, session)
        post_count = len(get_all_features(session))

        logs.append(f"✅ [Action Engine] Sync successful. Feature matrix updated (post_count={post_count}).")
        return {
            "pre_count": pre_count,
            "post_count": post_count,
            "execution_log": logs,
        }
    finally:
        session.close()


def node_verify(state: AgentState) -> Dict[str, Any]:
    """Step 5 Independent Verification and Markdown Weekly Digest compilation."""
    logs = list(state.get("execution_log", []))
    pre_count = state.get("pre_count", 0)
    post_count = state.get("post_count", 0)
    approved_proposals = state.get("approved_proposals", [])

    logs.append("🔍 [Verification] Executing independent Step 5 post-write integrity audit...")

    session = get_session()
    try:
        receipt, digest = verify_and_generate_digest(
            pre_count=pre_count,
            post_count=post_count,
            approved_proposals=approved_proposals,
            db_session=session,
        )

        status_msg = "SUCCESS" if receipt.hash_match else "FAILED"
        logs.append(
            f"✅ [Verification] Audit completed [{status_msg}]. "
            f"Row count verified ({receipt.row_count_before} -> {receipt.row_count_after}). "
            f"Weekly digest compiled ({len(digest)} chars)."
        )

        return {
            "sync_receipt": receipt,
            "digest": digest,
            "execution_log": logs,
        }
    finally:
        session.close()


def build_scout_graph(checkpointer: Optional[Any] = None):
    """
    Construct the interruptible LangGraph workflow.
    Configured with interrupt_before=['approval_gate'] to enforce mandatory HITL.
    """
    builder = StateGraph(AgentState)

    # Add workflow nodes
    builder.add_node("ingest", node_ingest)
    builder.add_node("classify", node_classify)
    builder.add_node("approval_gate", node_approval_gate)
    builder.add_node("sync_sheet", node_sync_sheet)
    builder.add_node("verify", node_verify)

    # Establish linear deterministic DAG
    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "classify")
    builder.add_edge("classify", "approval_gate")
    builder.add_edge("approval_gate", "sync_sheet")
    builder.add_edge("sync_sheet", "verify")
    builder.add_edge("verify", END)

    memory = checkpointer or MemorySaver()
    return builder.compile(
        checkpointer=memory,
        interrupt_before=["approval_gate"],
    )
