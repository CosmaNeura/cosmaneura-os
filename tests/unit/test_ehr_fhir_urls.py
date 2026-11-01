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

PRODUCTION_URLS = (
    "https://fhir.prd.cloud.tebra.com/fhir-request",
    "https://api.prod.example.com/fhir",
    "https://production.ehr.example.com/r4",
    "https://live.vendor.example.com/fhir",
)


@pytest.mark.parametrize("url", SANDBOX_URLS)
def test_sandbox_urls_are_accepted(url: str):
    assert is_sandbox_base_url(url)
    assert assert_allowed_base_url(url) == url.rstrip("/")
    assert production_base_refused(url) is False
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


def test_invalid_base_urls_are_rejected():
    for url in (
        "ftp://sandbox.example.com/fhir",
        "https://user:pass@sandbox.example.com/fhir",
        "https://sandbox.example.com/fhir?x=1",
        "https://sandbox.example.com/fhir#frag",
        "not a url",
    ):
        with pytest.raises(ValueError):
            assert_allowed_base_url(url)
