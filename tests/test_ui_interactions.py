"""
Automated End-to-End Streamlit UI Verification Suite.
Validates all interactive controls in app.py using Streamlit's native
headless testing framework (streamlit.testing.v1.AppTest) to ensure zero
runtime exceptions (TypeError, AttributeError, unhandled exceptions).
"""

import json
import os
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from core.sheet_sync import reset_ledger_to_baseline

APP_PATH = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure clean baseline ledger and SQLite state before and after each test."""
    reset_ledger_to_baseline()
    yield
    reset_ledger_to_baseline()


def test_ui_sidebar_reset_button():
    """
    Sidebar Control: Reset Matrix Action
    - Click '🧹 Reset Matrix to Clean Baseline' button
    - Assert app.exception is empty (zero unhandled exceptions)
    - Assert success notification is triggered
    - Assert data/comparison_matrix.json and .csv exist and reflect the 1-row baseline
    """
    at = AppTest.from_file(APP_PATH, default_timeout=15.0).run()
    assert not at.exception

    # Locate reset button by key
    reset_btn = at.sidebar.button(key="reset_matrix_baseline_btn")
    reset_btn.click().run()
    assert not at.exception

    # Assert success notification is triggered and visible in sidebar
    assert any("baseline" in s.value.lower() for s in at.sidebar.success)

    # Assert data/comparison_matrix.json and .csv exist and reflect the 1-row baseline
    assert os.path.exists("data/comparison_matrix.json")
    assert os.path.exists("data/comparison_matrix.csv")

    with open("data/comparison_matrix.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["Feature ID"] == "feat_jira_imp"
    assert data[0]["Competitor ID"] == "linear"


def test_ui_dynamic_url_sync():
    """
    Tab 1: Dynamic Competitor Selector & URL Sync
    - Select 'JIRA - Official Feeds' -> Assert Atlassian release notes URL
    - Select 'SUPABASE - Official Feeds' -> Assert https://supabase.com/changelog
    - Select 'LINEAR - Official Feeds' -> Assert https://linear.app/changelog
    - Assert zero exceptions occur throughout
    """
    at = AppTest.from_file(APP_PATH, default_timeout=15.0).run()
    assert not at.exception

    comp_select = at.selectbox("competitor_selector")

    # 1. Jira sync
    comp_select.select("JIRA - Official Feeds").run()
    assert not at.exception
    assert "confluence.atlassian.com" in at.session_state.custom_scrape_url
    assert "confluence.atlassian.com" in at.text_input(key="custom_scrape_url").value

    # 2. Supabase sync
    comp_select.select("SUPABASE - Official Feeds").run()
    assert not at.exception
    assert "supabase.com" in at.session_state.custom_scrape_url
    assert "https://supabase.com/changelog" == at.text_input(key="custom_scrape_url").value

    # 3. Linear sync
    comp_select.select("LINEAR - Official Feeds").run()
    assert not at.exception
    assert "linear.app" in at.session_state.custom_scrape_url
    assert "https://linear.app/changelog" == at.text_input(key="custom_scrape_url").value


def test_ui_launch_scan_staged_proposals():
    """
    Tab 1: Scan Execution (Mock Mode)
    - Select Mock Scenario: 'TC1: New Feature in Changelog (Shipped)'
    - Click '🚀 Run Agentic Scout Pipeline'
    - Assert zero exceptions occur during graph initialization or execution
    - Assert proposals are populated in st.session_state.pending_proposals
    """
    at = AppTest.from_file(APP_PATH, default_timeout=15.0).run()
    assert not at.exception

    scenario_select = at.selectbox("test_scenario_choice")
    scenario_select.select("TC1: New Feature in Changelog (Shipped)").run()
    assert not at.exception

    launch_btn = at.button("launch_scan_btn")
    launch_btn.click().run()
    assert not at.exception

    # Verify proposals staged
    assert len(at.session_state.pending_proposals) > 0
    assert "Linear Asks" in at.session_state.pending_proposals[0].feature_name
    assert at.session_state.pending_proposals[0].status.value == "shipped"


def test_ui_hitl_approval_and_sync_flow():
    """
    Tab 2: Human Approval Gate (HITL) - Proposal Selection & Sync Action
    - Stage proposals from TC1 scan
    - Verify proposal checkbox is rendered and can be toggled
    - Click '✅ Approve & Sync Selected Changes'
    - Assert zero exceptions occur during LangGraph resume
    - Assert sync finishes, advances state, and updates latest_digest and latest_receipt
    """
    at = AppTest.from_file(APP_PATH, default_timeout=15.0).run()
    assert not at.exception

    # Stage TC1 proposals
    at.selectbox("test_scenario_choice").select("TC1: New Feature in Changelog (Shipped)").run()
    at.button("launch_scan_btn").click().run()
    assert not at.exception
    assert len(at.session_state.pending_proposals) > 0

    # Test proposal checkbox toggle
    cb = at.checkbox("check_prop_0")
    assert cb.value is True
    cb.uncheck().run()
    assert not at.exception
    assert at.checkbox("check_prop_0").value is False
    at.checkbox("check_prop_0").check().run()
    assert at.checkbox("check_prop_0").value is True

    # Click Approve & Sync
    approve_btn = at.button("approve_sync_btn")
    approve_btn.click().run()
    assert not at.exception

    # Verify post-approval state
    assert at.session_state.latest_digest is not None
    assert at.session_state.latest_receipt is not None
    assert at.session_state.latest_receipt.status == "VERIFIED_SUCCESS"
    assert len(at.session_state.pending_proposals) == 0


def test_ui_hitl_discard_flow():
    """
    Tab 2: Discard Action
    - In a state with pending proposals, click '❌ Discard All Proposals'
    - Assert proposals list is cleared and zero exceptions occur
    - Assert warning notification is displayed
    """
    at = AppTest.from_file(APP_PATH, default_timeout=15.0).run()
    assert not at.exception

    # Stage TC1 proposals
    at.selectbox("test_scenario_choice").select("TC1: New Feature in Changelog (Shipped)").run()
    at.button("launch_scan_btn").click().run()
    assert len(at.session_state.pending_proposals) > 0

    # Discard proposals
    discard_btn = at.button("discard_all_btn")
    discard_btn.click().run()
    assert not at.exception

    # Assert proposals cleared and notification displayed
    assert len(at.session_state.pending_proposals) == 0
    assert any("discarded" in w.value.lower() for w in at.warning)


def test_ui_tab3_matrix_and_download_payloads():
    """
    Tab 3: Matrix & Weekly Digest
    - Assert the dataframe table renders without error
    - Assert both CSV and JSON download buttons are present and have valid download endpoints
    - Assert the underlying matrix data payloads are valid
    """
    at = AppTest.from_file(APP_PATH, default_timeout=15.0).run()
    assert not at.exception

    # Dataframe rendering
    assert len(at.dataframe) > 0
    df = at.dataframe[0].value
    assert "Competitor ID" in df.columns
    assert "Feature ID" in df.columns
    assert len(df) >= 1

    # CSV download button
    dl_csv = at.download_button("download_csv_btn")
    assert dl_csv is not None
    assert "Download Comparison Matrix (CSV)" in dl_csv.label
    assert dl_csv.url.endswith(".csv") or "media" in dl_csv.url or "_stcore" in dl_csv.url
    assert not dl_csv.disabled

    # JSON download button
    dl_json = at.download_button("download_json_btn")
    assert dl_json is not None
    assert "Download Comparison Matrix (JSON)" in dl_json.label
    assert dl_json.url.endswith(".json") or "media" in dl_json.url or "_stcore" in dl_json.url
    assert not dl_json.disabled

    # Verify data payloads in comparison matrix files
    assert os.path.exists("data/comparison_matrix.csv")
    with open("data/comparison_matrix.csv", "r", encoding="utf-8") as f:
        csv_text = f.read()
    assert "Competitor ID" in csv_text
    assert "feat_jira_imp" in csv_text

    assert os.path.exists("data/comparison_matrix.json")
    with open("data/comparison_matrix.json", "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert isinstance(json_data, list)
    assert any(row.get("Feature ID") == "feat_jira_imp" for row in json_data)


def test_ui_tab4_test_runner():
    """
    Tab 4: Official Test Runner (TC1–TC4)
    - Locate and click '🧪 Run Official Test Suite (TC1–TC4)'
    - Run app.run()
    - Assert test execution triggers without crashing the Streamlit app
    - Assert the test results/output component renders
    """
    at = AppTest.from_file(APP_PATH, default_timeout=30.0).run()
    assert not at.exception

    test_btn = at.button("run_official_tests_btn")
    test_btn.click().run()
    assert not at.exception

    # Assert output component rendered and success banner displayed
    assert any("ALL TESTS PASSED" in s.value for s in at.success)
    assert len(at.code) > 0
    assert "test session starts" in at.code[0].value or "passed" in at.code[0].value
