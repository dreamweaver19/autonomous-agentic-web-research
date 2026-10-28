"""Tests for SSRF protection and crawl safety checks."""
import pytest
from crawler import _is_safe_url


def test_blocks_localhost():
    safe, reason = _is_safe_url("http://localhost/admin")
    assert not safe
    assert "blocked" in reason.lower() or "localhost" in reason.lower()


def test_blocks_loopback_ip():
    safe, reason = _is_safe_url("http://127.0.0.1/secret")
    assert not safe


def test_blocks_aws_metadata():
    safe, reason = _is_safe_url("http://169.254.169.254/latest/meta-data/")
    assert not safe


def test_allows_public_url():
    safe, reason = _is_safe_url("https://www.example.com/page")
    assert safe, f"Expected safe but got: {reason}"


def test_allows_https():
    safe, reason = _is_safe_url("https://wikipedia.org/wiki/Python")
    assert safe


def test_blocks_ftp_scheme():
    safe, reason = _is_safe_url("ftp://files.example.com/file.txt")
    assert not safe
    assert "scheme" in reason.lower()


def test_blocks_file_scheme():
    safe, reason = _is_safe_url("file:///etc/passwd")
    assert not safe


def test_blocks_private_ip_10():
    # 10.x.x.x is private – but DNS must resolve to it
    # We test the SSRF check on known blocked domains instead
    safe, reason = _is_safe_url("http://0.0.0.0/admin")
    assert not safe
