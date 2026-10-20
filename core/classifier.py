"""
Deterministic Decision & Classification Engine for Competitor Changelog Scout.
Evaluates scraped items strictly according to TC1, TC2, TC3, and TC4 decision gates.
Zero ambiguity, deterministic execution, and cryptographic fingerprinting.
"""

import hashlib
import re
import uuid
from typing import List, Optional, Tuple
from core.schemas import (
    ActionType,
    ExistingFeature,
    FeatureStatus,
    RawScrapedItem,
    StagedProposal,
)

# Deterministic markers for roadmap/marketing classification (TC2)
FUTURE_RELEASE_MARKERS = [
    "coming soon",
    "planned",
    "next quarter",
    "announcing",
    "preview",
    "roadmap",
    "in development",
    "upcoming",
    "beta signup",
    "will be available",
    "private beta",
]

# Deterministic markers for rebrand/rename classification (TC3)
RENAME_MARKERS = [
    "renamed",
    "rebranded",
    "now called",
    "replaces",
    "renaming",
    "formerly known as",
    "successor to",
]


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
    # Cut off cleanly at word boundary
    truncated = cleaned[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 80:
        return truncated[:last_space] + "..."
    return truncated + "..."


def check_rename_match(
    text: str, known_features: List[ExistingFeature]
) -> Optional[Tuple[ExistingFeature, str]]:
    """
    Search for mention of known feature names or aliases coupled with rename markers.
    Returns (matched_feature, new_name_hint) if detected.
    """
    text_lower = text.lower()

    # Verify if any rename token is present
    found_marker = None
    for marker in RENAME_MARKERS:
        if marker in text_lower:
            found_marker = marker
            break

    if not found_marker:
        return None

    # Check each known feature
    for feature in known_features:
        candidates = [feature.name] + feature.aliases
        for candidate in candidates:
            if re.search(rf"\b{re.escape(candidate.lower())}\b", text_lower):
                # Search for new name pattern: e.g. "is now called <New Name>"
                pattern = rf"(?:is now called|replaces|renamed to|now called)\s+([A-Za-z0-9\s\-]+?)(?:\.|\,|\;|\:|\band\b|\bwith\b|\bfor\b|$)"
                match = re.search(pattern, text, re.IGNORECASE)
                new_name = match.group(1).strip() if match else feature.name
                # Clean up new name
                new_name = re.sub(r"\s+", " ", new_name).strip()
                if len(new_name) > 60:
                    new_name = new_name[:60]
                return feature, new_name

    return None


def extract_feature_name_from_title(title: str) -> str:
    """Extract normalized feature name from entry title."""
    # Remove dates, 'Changelog', 'Announcing', etc.
    cleaned = re.sub(r"^(Announcing|Introducing|Shipping|Released?|New:?)\s+", "", title, flags=re.IGNORECASE)
    # Remove trailing subtitles if separated by colons or dashes
    cleaned = cleaned.split(" - ")[0].split(" : ")[0].strip()
    return cleaned or title


def evaluate_scraped_item(
    item: RawScrapedItem,
    competitor_id: str,
    known_features: List[ExistingFeature],
) -> StagedProposal:
    """
    Evaluate raw scraped item against deterministic decision rules:
    - TC4: HTTP Error / 404 / Network Failure -> FLAG_UNCERTAIN (NEVER mark as feature removed)
    - TC3: Feature Renamed / Rebranded -> RENAME_ALIAS
    - TC2: Marketing Post / Future markers -> ADD_ANNOUNCED (NOT shipped)
    - TC1: Changelog Release -> ADD_NEW (shipped)
    """
    content_hash = compute_content_hash(competitor_id, item.title, item.source_url)
    proposal_id = f"prop_{uuid.uuid4().hex[:12]}"

    # -------------------------------------------------------------
    # GATE TC4: Page removed / 404 / network connection error
    # Hard Requirement: EXPLICITLY NEVER mark as "feature removed"
    # -------------------------------------------------------------
    if item.http_status != 200 or item.fetch_error is not None:
        error_detail = item.fetch_error or f"HTTP {item.http_status} Status Error"
        return StagedProposal(
            proposal_id=proposal_id,
            competitor_id=competitor_id,
            action_type=ActionType.FLAG_UNCERTAIN,
            target_feature_id=None,
            feature_name=item.title if item.title and "HTTP" not in item.title else "Unverified Changelog Endpoint",
            status=FeatureStatus.UNCERTAIN,
            confidence=0.95,
            reasoning=(
                f"Source endpoint returned error ({error_detail}). "
                "Classified as UNCERTAIN due to unreachable source. "
                "CRITICAL: Retaining feature registry intact; unreachable page is never marked as deleted or missing."
            ),
            evidence_quote=extract_evidence_quote(error_detail, max_chars=150),
            source_url=item.source_url,
            content_hash=content_hash,
            approved=False,
        )

    full_text = f"{item.title} {item.raw_content}"
    full_text_lower = full_text.lower()

    # -------------------------------------------------------------
    # GATE TC3: Feature Renamed / Rebranded
    # Checks known feature names/aliases against rename markers
    # -------------------------------------------------------------
    rename_result = check_rename_match(full_text, known_features)
    if rename_result is not None:
        matched_feature, new_name_hint = rename_result
        # If item title looks like the new name, prioritize that
        extracted_title_name = extract_feature_name_from_title(item.title)
        effective_new_name = extracted_title_name if len(extracted_title_name) > 3 else new_name_hint

        return StagedProposal(
            proposal_id=proposal_id,
            competitor_id=competitor_id,
            action_type=ActionType.RENAME_ALIAS,
            target_feature_id=matched_feature.id,
            feature_name=effective_new_name,
            status=FeatureStatus.SHIPPED,
            confidence=0.98,
            reasoning=(
                f"Identified rebrand/rename event matching existing feature '{matched_feature.name}' "
                f"(ID: {matched_feature.id}). Mapping new alias '{effective_new_name}' to existing feature ID."
            ),
            evidence_quote=extract_evidence_quote(item.raw_content, max_chars=150),
            source_url=item.source_url,
            content_hash=content_hash,
            approved=False,
        )

    # -------------------------------------------------------------
    # GATE TC2: Marketing post only / Future release roadmap
    # Hard Requirement: Classify as 'announced' (NOT 'shipped')
    # -------------------------------------------------------------
    is_marketing = not item.is_changelog
    has_future_markers = any(marker in full_text_lower for marker in FUTURE_RELEASE_MARKERS)

    if is_marketing or has_future_markers:
        feature_name = extract_feature_name_from_title(item.title)
        matched_markers = [m for m in FUTURE_RELEASE_MARKERS if m in full_text_lower]
        marker_desc = f" (indicators: {', '.join(matched_markers)})" if matched_markers else ""

        return StagedProposal(
            proposal_id=proposal_id,
            competitor_id=competitor_id,
            action_type=ActionType.ADD_ANNOUNCED,
            target_feature_id=None,
            feature_name=feature_name,
            status=FeatureStatus.ANNOUNCED,
            confidence=0.92,
            reasoning=(
                f"Classified as ANNOUNCED (NOT shipped). Source is marketing/blog feed or "
                f"contains forward-looking roadmap markers{marker_desc}."
            ),
            evidence_quote=extract_evidence_quote(item.raw_content, max_chars=150),
            source_url=item.source_url,
            content_hash=content_hash,
            approved=False,
        )

    # -------------------------------------------------------------
    # GATE TC1: New feature in official changelog
    # Hard Requirement: Classify as 'shipped', stage as ADD_NEW
    # -------------------------------------------------------------
    feature_name = extract_feature_name_from_title(item.title)
    return StagedProposal(
        proposal_id=proposal_id,
        competitor_id=competitor_id,
        action_type=ActionType.ADD_NEW,
        target_feature_id=None,
        feature_name=feature_name,
        status=FeatureStatus.SHIPPED,
        confidence=0.99,
        reasoning="Verified production feature release detected in official changelog.",
        evidence_quote=extract_evidence_quote(item.raw_content, max_chars=150),
        source_url=item.source_url,
        content_hash=content_hash,
        approved=False,
    )
