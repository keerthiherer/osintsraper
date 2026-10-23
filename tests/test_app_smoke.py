from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_renders_all_tabs_without_exception():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    app.run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Business Discovery",
        "Lead Intelligence",
        "Website Audit",
        "Quotation Assistant",
        "Freelance Opportunities",
        "Sales CRM",
        "Settings and Data Sources",
    ]
    assert app.title[0].value == "MindSmiths Sales Intelligence"
    assert len(app.button) > 0
