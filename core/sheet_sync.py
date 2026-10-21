"""
Action Execution & Dual-Ledger Sync Engine for Competitor Changelog Scout.
Batch writes approved proposals to SQLite and Google Sheets (gspread)
with resilient, automated fallback to local CSV/JSON matrix.
"""

import csv
import json
import logging
import os
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from core.schemas import StagedProposal
from storage.db import (
    CompetitorModel,
    apply_approved_proposal,
    get_all_features,
    get_session,
    reset_db_to_baseline,
    save_proposal,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DEFAULT_CSV_PATH = os.path.join(DEFAULT_DATA_DIR, "comparison_matrix.csv")
DEFAULT_JSON_PATH = os.path.join(DEFAULT_DATA_DIR, "comparison_matrix.json")
SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "service_account.json")


def export_matrix_to_ledger(
    features,
    competitors_dict: Dict[str, str],
    csv_path: str = DEFAULT_CSV_PATH,
    json_path: str = DEFAULT_JSON_PATH,
) -> List[Dict[str, Any]]:
    """Export the feature comparison matrix to CSV and JSON ledgers."""
    os.makedirs("data", exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for f in features:
        comp_name = competitors_dict.get(f.competitor_id, f.competitor_id.capitalize())
        row = {
            "Competitor ID": f.competitor_id,
            "Competitor Name": comp_name,
            "Feature ID": f.id,
            "Feature Name": f.name,
            "Status": f.status.value if hasattr(f.status, "value") else str(f.status),
            "Aliases": ", ".join(f.aliases) if f.aliases else "",
            "Source URL": f.source_url,
            "Last Updated": f.last_updated.isoformat() if hasattr(f.last_updated, "isoformat") else str(f.last_updated),
        }
        rows.append(row)

    # 1. Write CSV
    fieldnames = [
        "Competitor ID",
        "Competitor Name",
        "Feature ID",
        "Feature Name",
        "Status",
        "Aliases",
        "Source URL",
        "Last Updated",
    ]
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # 2. Write JSON
    with open(json_path, mode="w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    return rows


def sync_to_google_sheets(
    rows: List[Dict[str, Any]],
    spreadsheet_title: str = "Competitor Comparison Matrix",
    service_account_file: str = SERVICE_ACCOUNT_PATH,
) -> bool:
    """
    Attempt to sync rows to Google Sheets via gspread.
    Resiliently catches missing credentials or network errors and falls back to local ledger.
    """
    if not os.path.exists(service_account_file):
        logger.info(
            f"Google credentials not found at {service_account_file}. "
            "Operating in resilient local-ledger mode (CSV/JSON active)."
        )
        return False

    try:
        import gspread

        gc = gspread.service_account(filename=service_account_file)
        try:
            sh = gc.open(spreadsheet_title)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(spreadsheet_title)

        worksheet = sh.sheet1
        worksheet.clear()

        if rows:
            headers = list(rows[0].keys())
            values = [headers] + [[r[h] for h in headers] for r in rows]
            worksheet.update("A1", values)

        logger.info(f"Successfully synced {len(rows)} records to Google Sheet: '{spreadsheet_title}'.")
        return True
    except Exception as exc:
        logger.warning(
            f"Google Sheets sync encountered exception: {exc}. "
            "Operating in resilient local-ledger mode (CSV/JSON active)."
        )
        return False


def commit_proposals(
    approved_proposals: List[StagedProposal],
    db_session: Session,
    csv_path: str = DEFAULT_CSV_PATH,
    json_path: str = DEFAULT_JSON_PATH,
    spreadsheet_title: str = "Competitor Comparison Matrix",
) -> int:
    """
    Batch commit approved proposals:
    1. Updates local SQLite database features and proposals tables.
    2. Exports updated matrix to data/comparison_matrix.csv and data/comparison_matrix.json.
    3. Attempts Google Sheets sync with automatic local-ledger fallback.
    """
    if not approved_proposals:
        logger.info("No approved proposals provided for sync.")
        return 0

    # 1. Update SQLite records
    for prop in approved_proposals:
        prop.approved = True
        save_proposal(db_session, prop)
        apply_approved_proposal(db_session, prop)

    # 2. Fetch updated features and competitor dictionary
    all_features = get_all_features(db_session)
    comps = db_session.query(CompetitorModel).all()
    competitors_dict = {c.id: c.name for c in comps}

    # 3. Export to CSV & JSON ledger
    rows = export_matrix_to_ledger(
        features=all_features,
        competitors_dict=competitors_dict,
        csv_path=csv_path,
        json_path=json_path,
    )

    # 4. Attempt Google Sheets sync
    sync_to_google_sheets(rows, spreadsheet_title=spreadsheet_title)

    logger.info(f"Committed {len(approved_proposals)} approved proposals to local matrix.")
    return len(approved_proposals)


def reset_ledger_to_baseline(
    db_session: Optional[Session] = None,
    csv_path: str = DEFAULT_CSV_PATH,
    json_path: str = DEFAULT_JSON_PATH,
) -> List[Dict[str, Any]]:
    """
    Reset feature comparison matrix and database to clean seed baseline:
    1. Ensures data/ directory exists.
    2. Writes clean baseline entry into data/comparison_matrix.json and data/comparison_matrix.csv.
    3. Clears rogue test proposals and non-seed features in SQLite storage,
       leaving only standard competitors and the single seed feature 'feat_jira_imp'.
    """
    # 1. Ensure data directories exist
    os.makedirs("data", exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)

    # 2. Write clean baseline entry to JSON and CSV
    baseline_rows: List[Dict[str, Any]] = [
        {
            "Competitor ID": "linear",
            "Competitor Name": "Linear",
            "Feature ID": "feat_jira_imp",
            "Feature Name": "Jira Importer",
            "Status": "shipped",
            "Aliases": "Legacy Importer",
            "Source URL": "https://linear.app/changelog/legacy-importer",
            "Last Updated": "2026-10-15T00:00:00",
        }
    ]

    fieldnames = [
        "Competitor ID",
        "Competitor Name",
        "Feature ID",
        "Feature Name",
        "Status",
        "Aliases",
        "Source URL",
        "Last Updated",
    ]

    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(baseline_rows)

    with open(json_path, mode="w", encoding="utf-8") as f:
        json.dump(baseline_rows, f, indent=2, ensure_ascii=False)

    # 3. Clean SQLite database
    close_after = False
    session = db_session
    if session is None:
        session = get_session()
        close_after = True

    try:
        reset_db_to_baseline(session)
    finally:
        if close_after:
            session.close()

    logger.info("Successfully reset ledger and database to clean seed baseline.")
    return baseline_rows
