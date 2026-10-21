"""
Deterministic Decision & Classification Engine for Competitor Changelog Scout.
Evaluates scraped items strictly according to TC1, TC2, TC3, and TC4 decision gates.
Zero ambiguity, deterministic execution, and cryptographic fingerprinting.
"""

import hashlib
import re
import uuid
from datetime import datetime
from typing import List, Optional
from core.schemas import (
    ActionType,
    ExistingFeature,
    FeatureStatus,
    RawScrapedItem,
    StagedProposal,
)


def compute_content_hash(competitor_id: str, title: str, source_url: str) -> str:
    """Compute deterministic SHA-256 fingerprint of the item."""
    fingerprint_raw = f"{competitor_id.strip()}:{title.strip()}:{source_url.strip()}"
    return hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()


def extract_evidence_quote(text: str, max_chars: int = 150) -> str:
    """Extract a clean, concise evidence snippet of up to max_chars characters."""
    if not text:
        return "No text snippet available."
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 80:
        return truncated[:last_space] + "..."
    return truncated + "..."


def evaluate_scraped_item(
    item: RawScrapedItem,
    competitor_id: str,
    known_features: List[ExistingFeature],
) -> StagedProposal:
    """
    Evaluate raw scraped item against deterministic decision rules:
    - GATE 1 (TC4): HTTP Error / 404 / Network Failure -> FLAG_UNCERTAIN (never marked as feature removed)
    - GATE 2 (TC3): Feature Renamed / Rebranded -> RENAME_ALIAS
    - GATE 3 (TC2): Non-Changelog (Blog) OR Forward-Looking Announcement -> ADD_ANNOUNCED
    - GATE 4 (TC1): Verified Production Release in Changelog -> ADD_NEW (shipped)
    """
    proposal_id = f"prop_{uuid.uuid4().hex[:10]}"
    title_clean = item.title.strip() if item.title else "Untitled Update"
    content_lower = item.raw_content.lower()
    title_lower = title_clean.lower()

    # Generate stable deterministic content hash
    hash_seed = f"{competitor_id}:{title_clean}:{item.source_url}".encode("utf-8")
    content_hash = hashlib.sha256(hash_seed).hexdigest()

    # Extract 150-char contextual evidence snippet
    raw_snippet = item.raw_content.replace("\n", " ").strip()
    evidence_quote = (raw_snippet[:147] + "...") if len(raw_snippet) > 150 else (raw_snippet or "No text content available.")

    # -------------------------------------------------------------
    # GATE 1 (TC4): HTTP Errors, 404s, or Network Failures
    # -------------------------------------------------------------
    if item.http_status != 200 or item.fetch_error is not None:
        return StagedProposal(
            proposal_id=proposal_id,
            competitor_id=competitor_id,
            action_type=ActionType.FLAG_UNCERTAIN,
            target_feature_id=None,
            feature_name="Source Unavailable / Fetch Failure",
            status=FeatureStatus.UNCERTAIN,
            confidence=0.95,
            reasoning=f"Source returned HTTP {item.http_status} or network error: '{item.fetch_error}'. Marked uncertain per TC4 policy (registry intact; never marked as deleted or missing).",
            evidence_quote=f"Network status: HTTP {item.http_status} - {item.fetch_error or 'Resource missing'}",
            source_url=item.source_url,
            content_hash=content_hash,
            approved=False,
        )

    # -------------------------------------------------------------
    # GATE 2 (TC3): Feature Renamed / Rebranded (Matches Existing Registry)
    # -------------------------------------------------------------
    rename_markers = ["renamed", "rebranded", "now called", "replaces", "renaming", "formerly known as"]
    for feat in known_features:
        if feat.competitor_id.lower() == competitor_id.lower():
            # Check if existing feature name or aliases appear in conjunction with rename markers
            names_to_check = [feat.name.lower()] + [a.lower() for a in feat.aliases]
            for target_name in names_to_check:
                if target_name in content_lower or target_name in title_lower:
                    if any(marker in content_lower for marker in rename_markers):
                        # Extract new proposed name cleanly
                        new_feature_name = title_clean
                        for m in ["rebranding", "renaming", "is now called", "rebranded"]:
                            if m in new_feature_name.lower():
                                parts = re.split(m, new_feature_name, flags=re.IGNORECASE)
                                if len(parts) > 1 and parts[1].strip():
                                    new_feature_name = parts[1].strip(" :-–—")

                        return StagedProposal(
                            proposal_id=proposal_id,
                            competitor_id=competitor_id,
                            action_type=ActionType.RENAME_ALIAS,
                            target_feature_id=feat.id,
                            feature_name=new_feature_name or title_clean,
                            status=FeatureStatus.SHIPPED,
                            confidence=0.98,
                            reasoning=f"Identified rebrand/rename from existing feature '{feat.name}' (ID: {feat.id}). Mapping to existing row per TC3 policy.",
                            evidence_quote=evidence_quote,
                            source_url=item.source_url,
                            content_hash=content_hash,
                            approved=False,
                        )

    # -------------------------------------------------------------
    # GATE 3 (TC2): Non-Changelog (Blog) OR Forward-Looking Announcement
    # -------------------------------------------------------------
    # Forward-looking regex patterns that avoid matching lone words like "roadmap" in navbars
    future_regex = re.compile(r'\b(coming soon|planned for|next quarter|in beta|preview release|will roll out|upcoming)\b', re.IGNORECASE)

    # Condition: Scraped from a blog (is_changelog=False) OR title explicitly states preview/coming soon
    is_marketing_blog = not item.is_changelog or "/blog" in item.source_url.lower()
    has_future_markers = bool(future_regex.search(title_lower)) or (is_marketing_blog and bool(future_regex.search(content_lower)))

    if is_marketing_blog or has_future_markers:
        return StagedProposal(
            proposal_id=proposal_id,
            competitor_id=competitor_id,
            action_type=ActionType.ADD_ANNOUNCED,
            target_feature_id=None,
            feature_name=title_clean,
            status=FeatureStatus.ANNOUNCED,
            confidence=0.92,
            reasoning="Source is a marketing blog post or contains future roadmap promises. Classified as announced, not shipped per TC2 policy.",
            evidence_quote=evidence_quote,
            source_url=item.source_url,
            content_hash=content_hash,
            approved=False,
        )

    # -------------------------------------------------------------
    # GATE 4 (TC1): Verified Production Release in Changelog (SHIPPED)
    # -------------------------------------------------------------
    return StagedProposal(
        proposal_id=proposal_id,
        competitor_id=competitor_id,
        action_type=ActionType.ADD_NEW,
        target_feature_id=None,
        feature_name=title_clean,
        status=FeatureStatus.SHIPPED,
        confidence=0.99,
        reasoning="Verified new feature release published on official changelog feed per TC1 policy.",
        evidence_quote=evidence_quote,
        source_url=item.source_url,
        content_hash=content_hash,
        approved=False,
    )
