import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from config import (
    WEBSITE_CHECK_FAILED,
    WEBSITE_NO_WEBSITE,
    WEBSITE_REACHABLE,
    WEBSITE_UNREACHABLE,
)
from mindsmiths.contacts import extract_contacts
from mindsmiths.social import extract_social_links
from mindsmiths.website import check_website

GOOD_PAGE = """<!doctype html>
<html><head>
<title>Studio X Photography</title>
<meta name="description" content="Wedding and portrait photography in Chennai.">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body>
<h1>Studio X Photography</h1>
<p>We photograph weddings, portraits and events across Chennai and Tamil Nadu.
Call us or send an enquiry to plan your next photo session with our team.
Our studio is open Monday to Saturday and we reply to every enquiry within one day.</p>
<a href="https://www.instagram.com/mindsmiths_test_studio/">Instagram</a>
<a href="https://www.facebook.com/sharer.php?u=x">Share</a>
<a href="https://www.facebook.com/mindsmiths.test.studio/">Facebook</a>
<a href="https://www.linkedin.com/company/mindsmiths-test-studio/">LinkedIn</a>
<a href="mailto:hello@studiox.in">Email us</a>
<a href="tel:+919876543210">Call us</a>
<a href="/contact">Contact us</a>
<form action="/enquiry"><input name="message"></form>
</body></html>"""

MINIMAL_PAGE = "<html><head><title>Thin Page</title></head><body><p>Hello</p></body></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/good":
            body = GOOD_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/minimal":
            body = MINIMAL_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/good")
            self.end_headers()
        else:
            self.send_error(404, "Not found")

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_missing_website_is_unknown_not_absence_of_business():
    result = check_website("")
    assert result.status == WEBSITE_NO_WEBSITE
    assert result.error == ""


def test_reachable_website_metadata(server):
    result = check_website(f"{server}/good", timeout=5)
    assert result.status == WEBSITE_REACHABLE
    assert result.http_status == 200
    assert result.title == "Studio X Photography"
    assert result.meta_description.startswith("Wedding and portrait")
    assert result.has_viewport is True
    assert "HTTPS not used" in result.issues


def test_redirect_final_url(server):
    result = check_website(f"{server}/redirect", timeout=5)
    assert result.status == WEBSITE_REACHABLE
    assert result.final_url.endswith("/good")


def test_http_error_is_unreachable(server):
    result = check_website(f"{server}/missing", timeout=5)
    assert result.status == WEBSITE_UNREACHABLE
    assert result.http_status == 404


def test_connection_failure_is_unreachable():
    result = check_website("http://127.0.0.1:1", timeout=2)
    assert result.status == WEBSITE_UNREACHABLE
    assert "Connection failed" in result.error


def test_invalid_url_is_check_failed():
    result = check_website("not a valid url", timeout=2)
    assert result.status == WEBSITE_CHECK_FAILED


def test_lightweight_page_issues(server):
    result = check_website(f"{server}/minimal", timeout=5)
    assert result.status == WEBSITE_REACHABLE
    assert "Missing meta description" in result.issues
    assert "Missing mobile viewport" in result.issues
    assert "Minimal page content" in result.issues


def test_contact_extraction():
    details = extract_contacts(GOOD_PAGE, "https://studiox.in/")
    assert "hello@studiox.in" in details.emails
    assert any("9876543210" in phone for phone in details.phones)
    assert details.contact_page == "https://studiox.in/contact"
    assert details.form_url == "https://studiox.in/enquiry"


def test_social_extraction_skips_share_links():
    socials = extract_social_links(GOOD_PAGE, "https://studiox.in/", "Studio X Photography")
    by_platform = {s.platform: s for s in socials}
    assert set(by_platform) == {"instagram", "facebook", "linkedin"}
    assert "sharer.php" not in by_platform["facebook"].url
    assert by_platform["instagram"].followers is None
    assert by_platform["instagram"].followers_verified is False
    assert by_platform["instagram"].confidence >= 0.9
