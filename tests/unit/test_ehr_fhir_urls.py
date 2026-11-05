"""Sandbox-only base URL gate and production refusal defaults."""

from __future__ import annotations

import pytest

from cosmas_os.plugins.ehr_fhir import (
    FhirR4ReadClient,
    assert_allowed_base_url,
    is_production_base_url,
    is_sandbox_base_url,
    production_base_refused,
)

SANDBOX_URLS = (
    "https://fhir.sandbox.example.com/r4",
    "https://sandbox.fhir.example.org/fhir",
    "https://synthetic.invalid/fhir",
    "https://mock.example.com/r4",
    "http://localhost:8080/fhir",
    "http://127.0.0.1:9443/r4",
)

# Case variants of allowlisted hosts must still pass (exact match is case-insensitive).
SANDBOX_CASE_URLS = (
    "https://FHIR.SANDBOX.EXAMPLE.COM/r4",
    "https://Sandbox.Fhir.Example.Org/fhir",
    "https://MOCK.EXAMPLE.COM/r4",
)

PRODUCTION_URLS = (
    "https://fhir.prd.cloud.tebra.com/fhir-request",
    "https://api.prod.example.com/fhir",
    "https://production.ehr.example.com/r4",
    "https://live.vendor.example.com/fhir",
)

# Look-alike hosts that previously matched substring/word markers must be refused.
LOOKALIKE_REFUSED_URLS = (
    "https://test.evil.com/fhir",
    "https://mock-athena.example.net/r4",
    "https://sandbox.attacker.io/fhir",
    "https://fhir.sandbox.example.com./r4",  # trailing DNS dot
    "https://not-sandbox.example.com/r4",
    "https://api.example.com/fhir",
    "https://something.test.evil.com/r4",
    "https://prefix-mock.example.com/fhir",
)


@pytest.mark.parametrize("url", SANDBOX_URLS)
def test_sandbox_urls_are_accepted(url: str):
    assert is_sandbox_base_url(url)
    assert assert_allowed_base_url(url) == url.rstrip("/")
    assert production_base_refused(url) is False
    client = FhirR4ReadClient(url)
    assert client.base_url == url.rstrip("/")


@pytest.mark.parametrize("url", SANDBOX_CASE_URLS)
def test_allowlisted_hosts_match_case_insensitively(url: str):
    assert is_sandbox_base_url(url)
    assert assert_allowed_base_url(url) == url.rstrip("/")
    client = FhirR4ReadClient(url)
    assert client.base_url == url.rstrip("/")


@pytest.mark.parametrize("url", PRODUCTION_URLS)
def test_production_urls_are_refused_by_default(url: str):
    assert is_production_base_url(url)
    assert production_base_refused(url) is True
    with pytest.raises(ValueError, match="fhir_base_url_production_refused"):
        assert_allowed_base_url(url)
    with pytest.raises(PermissionError, match="fhir_base_url_production_refused"):
        FhirR4ReadClient(url)


@pytest.mark.parametrize("url", PRODUCTION_URLS)
def test_production_urls_require_explicit_opt_in(url: str):
    assert assert_allowed_base_url(url, allow_production=True) == url.rstrip("/")
    client = FhirR4ReadClient(url, allow_production=True)
    assert client.base_url == url.rstrip("/")


def test_ambiguous_non_sandbox_hosts_are_refused():
    url = "https://fhir.vendor.example.net/r4"
    assert is_sandbox_base_url(url) is False
    assert is_production_base_url(url) is False
    with pytest.raises(ValueError, match="fhir_base_url_not_sandbox"):
        assert_allowed_base_url(url)
    with pytest.raises(PermissionError, match="fhir_base_url_not_sandbox"):
        FhirR4ReadClient(url)


@pytest.mark.parametrize("url", LOOKALIKE_REFUSED_URLS)
def test_lookalike_hosts_are_refused(url: str):
    assert is_sandbox_base_url(url) is False
    with pytest.raises(ValueError):
        assert_allowed_base_url(url)
    with pytest.raises((PermissionError, ValueError)):
        FhirR4ReadClient(url)


def test_lookalike_host_with_nondefault_https_port_is_refused():
    url = "https://test.evil.com:8443/fhir"
    assert is_sandbox_base_url(url) is False
    with pytest.raises(ValueError, match="fhir_base_url_invalid"):
        assert_allowed_base_url(url)


def test_uppercase_lookalike_hosts_are_refused():
    for url in (
        "https://TEST.EVIL.COM/fhir",
        "https://MOCK-ATHENA.EXAMPLE.NET/r4",
        "https://SANDBOX.ATTACKER.IO/fhir",
    ):
        assert is_sandbox_base_url(url) is False
        with pytest.raises(ValueError):
            assert_allowed_base_url(url)


def test_invalid_base_urls_are_rejected():
    for url in (
        "ftp://sandbox.example.com/fhir",
        "https://user:pass@fhir.sandbox.example.com/fhir",
        "https://fhir.sandbox.example.com/fhir?x=1",
        "https://fhir.sandbox.example.com/fhir#frag",
        "http://fhir.sandbox.example.com/fhir",  # plain http to non-local host
        "not a url",
    ):
        with pytest.raises(ValueError):
            assert_allowed_base_url(url)


def test_athena_preview_host_refused_by_default_opt_in_only():
    """C7 must not widen the shared sandbox host allowlist for other callers."""
    url = "https://api.preview.platform.athenahealth.com/fhir/r4"
    assert is_sandbox_base_url(url) is False
    assert production_base_refused(url) is True
    with pytest.raises(ValueError, match="fhir_base_url_not_sandbox"):
        assert_allowed_base_url(url)
    with pytest.raises(PermissionError, match="fhir_base_url_not_sandbox"):
        FhirR4ReadClient(url)
    assert is_sandbox_base_url(url, extra_sandbox_hosts={"api.preview.platform.athenahealth.com"})
    assert (
        assert_allowed_base_url(
            url, extra_sandbox_hosts={"api.preview.platform.athenahealth.com"}
        )
        == url
    )
    client = FhirR4ReadClient(
        url, extra_sandbox_hosts={"api.preview.platform.athenahealth.com"}
    )
    assert client.base_url == url
