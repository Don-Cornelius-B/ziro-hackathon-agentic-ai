"""
Deterministic mock fixtures for offline testing of Competitor Changelog Scout.
Guarantees sub-second offline execution for TC1-TC4 without network calls.
"""

from datetime import datetime, timezone
from typing import Dict
from core.schemas import RawScrapedItem

# HTML templates representing realistic competitor pages
TC1_CHANGELOG_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>Changelog - Linear</title></head>
<body>
  <nav><a href="/">Home</a><a href="/pricing">Pricing</a></nav>
  <main>
    <article class="changelog-entry">
      <time datetime="2026-03-15">March 15, 2026</time>
      <h1>Linear Asks - Customer Request Tracking</h1>
      <p>
        Today we are shipping Linear Asks, our new customer request tracking workflow.
        It enables customer-facing teams to submit bug reports and feature requests directly
        from Slack, Zendesk, and Intercom into unified Linear triage queues with automatic bi-directional status updates.
      </p>
      <ul>
        <li>Direct Slack and Zendesk integration for ticketing.</li>
        <li>Bi-directional status synchronization across customer and engineering teams.</li>
        <li>Automated SLA escalation triggers for urgent customer issues.</li>
      </ul>
    </article>
  </main>
  <footer><p>&copy; 2026 Linear Orbit, Inc.</p></footer>
</body>
</html>
"""

TC2_MARKETING_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>Blog - Linear Roadmap</title></head>
<body>
  <nav><a href="/">Home</a><a href="/blog">Blog</a></nav>
  <main>
    <article class="blog-post">
      <time datetime="2026-03-20">March 20, 2026</time>
      <h1>Announcing Next-Gen AI Workflows - Coming Soon in Q3</h1>
      <p>
        Today we are announcing our roadmap preview for Next-Gen Autonomous AI Workflows.
        Coming soon in Q3 2026, this upcoming capability will autonomously triage issues,
        synthesize pull requests from bug reports, and recommend architectural resolutions.
        This feature is currently in planned development and private preview.
      </p>
    </article>
  </main>
  <footer><p>&copy; 2026 Linear Orbit, Inc.</p></footer>
</body>
</html>
"""

TC3_RENAMED_HTML = """
<!DOCTYPE html>
<html lang="en">
<head><title>Changelog - Linear Platform Upgrades</title></head>
<body>
  <nav><a href="/">Home</a></nav>
  <main>
    <article class="changelog-entry">
      <time datetime="2026-04-02">April 2, 2026</time>
      <h1>Universal Workspace Sync: Seamless Migration Engine</h1>
      <p>
        As part of our major platform expansion, Jira Importer is now called Universal Workspace Sync.
        The upgraded engine replaces our legacy Jira migration tool with real-time bidirectional
        syncing, custom field mapping, and complete historical ticket re-indexing across all project workspaces.
      </p>
    </article>
  </main>
  <footer><p>&copy; 2026 Linear Orbit, Inc.</p></footer>
</body>
</html>
"""

# Concrete RawScrapedItem mock fixtures
MOCK_FIXTURES: Dict[str, RawScrapedItem] = {
    "tc1_changelog": RawScrapedItem(
        source_url="https://linear.app/changelog/2026-03-linear-asks",
        title="Linear Asks - Customer Request Tracking",
        raw_content=(
            "March 15, 2026. Today we are shipping Linear Asks, our new customer request tracking workflow. "
            "It enables customer-facing teams to submit bug reports and feature requests directly from Slack, "
            "Zendesk, and Intercom into unified Linear triage queues with automatic bi-directional status updates."
        ),
        is_changelog=True,
        http_status=200,
        fetch_error=None,
        scraped_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
    ),
    "tc2_blog_post": RawScrapedItem(
        source_url="https://linear.app/blog/next-gen-ai-preview",
        title="Announcing Next-Gen AI Workflows - Coming Soon in Q3",
        raw_content=(
            "March 20, 2026. Today we are announcing our roadmap preview for Next-Gen Autonomous AI Workflows. "
            "Coming soon in Q3 2026, this upcoming capability will autonomously triage issues, synthesize changelogs, "
            "and suggest resolution branches. This preview feature is currently in planned development."
        ),
        is_changelog=False,
        http_status=200,
        fetch_error=None,
        scraped_at=datetime(2026, 3, 20, 14, 0, 0, tzinfo=timezone.utc),
    ),
    "tc3_renamed": RawScrapedItem(
        source_url="https://linear.app/changelog/2026-04-workspace-sync",
        title="Universal Workspace Sync: Seamless Migration Engine",
        raw_content=(
            "April 2, 2026. As part of our platform expansion, Jira Importer is now called Universal Workspace Sync. "
            "The upgraded system replaces our legacy Jira migration tool with real-time bidirectional syncing, "
            "custom field preservation, and enhanced attachment migration across all project boards."
        ),
        is_changelog=True,
        http_status=200,
        fetch_error=None,
        scraped_at=datetime(2026, 4, 2, 9, 30, 0, tzinfo=timezone.utc),
    ),
    "tc4_missing": RawScrapedItem(
        source_url="https://linear.app/changelog/broken-endpoint-404",
        title="404 Not Found - Release Notes Endpoint",
        raw_content="",
        is_changelog=True,
        http_status=404,
        fetch_error="HTTP 404 Not Found: Page removed or network connection unavailable",
        scraped_at=datetime(2026, 4, 10, 8, 15, 0, tzinfo=timezone.utc),
    ),
}


def get_mock_item(mock_key: str) -> RawScrapedItem:
    """Retrieve a copy of a deterministic mock item."""
    if mock_key not in MOCK_FIXTURES:
        raise KeyError(f"Mock fixture '{mock_key}' not found. Valid keys: {list(MOCK_FIXTURES.keys())}")
    return MOCK_FIXTURES[mock_key].model_copy(deep=True)
