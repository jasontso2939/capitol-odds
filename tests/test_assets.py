"""Every page loads the shared stylesheet and script with the same version tag, so a browser
picks up a new design right after a deploy instead of using a cached copy."""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"


def test_shared_assets_are_versioned_alike():
    tags = set()
    for page in SITE.glob("*.html"):
        html = page.read_text()
        if 'common.js' not in html:
            continue
        found = re.findall(r'(?:href|src)="common\.(?:css|js)\?v=([\w.-]+)"', html)
        assert len(found) >= 1 and 'common.js"' not in html and 'common.css"' not in html, page.name
        tags.update(found)
    assert len(tags) == 1, tags
