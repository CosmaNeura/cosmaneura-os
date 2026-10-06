"""Actual PDF text extraction, measured bounds and fail-closed input handling."""
from io import BytesIO

import pytest
from lab.referral_pdf import build_referral_pdf, sha
from pypdf import PdfReader


def packet(**extra):
    return build_referral_pdf(accepted_scribe='Patient reports left ankle pain and a purple brace.\n'
        '“I do not remember the name of the medicine I reacted to.”\n'
        'Examination, imaging, diagnosis and medication dose are unverified.',
        visit_prep='Confirm the unknown allergy medicine; retain missing facts.\nNo referral has been sent or consultation booked.',
        owner_label='Virtual referral coordinator', source_sha256='a' * 64, synthetic_only=True, **extra)


def test_real_pdf_extracts_missing_facts_and_preserves_unknown_allergy():
    result = packet()
    reader = PdfReader(BytesIO(result.data), strict=True)
    assert 1 <= len(reader.pages) == result.pages <= 3
    assert result.pdf_sha256 == sha(result.data)
    assert result.extracted_text_sha256 == sha(result.extracted_text.encode())
    assert 'SYNTHETIC LOCAL TEST - NOT SENT' in result.extracted_text
    assert 'I do not remember the name of the medicine I reacted to.' in result.extracted_text
    assert 'Examination, imaging, diagnosis and medication dose are unverified.' in result.extracted_text
    assert 'No referral has been sent or consultation booked.' in result.extracted_text
    assert reader.pages[0].mediabox.width == 612 and reader.pages[0].mediabox.height == 792
    assert not reader.trailer['/Root'].get('/AcroForm') and not reader.trailer['/Root'].get('/Names')


def test_three_page_bound_refuses_silent_truncation():
    with pytest.raises(ValueError, match='three pages'):
        build_referral_pdf(accepted_scribe=('missing facts remain unknown\n' * 170), visit_prep='review only',
            owner_label='Synthetic owner', source_sha256='a' * 64, synthetic_only=True)


@pytest.mark.parametrize('text', ['unsafe\x00text', 'unexpected\tcontrol', 'unsupported emoji 🦴', ''])
def test_controls_or_unsupported_glyphs_are_not_replaced(text):
    with pytest.raises(ValueError):
        build_referral_pdf(accepted_scribe=text, visit_prep='review only', owner_label='Synthetic owner',
            source_sha256='a' * 64, synthetic_only=True)


def test_literal_pdf_operators_stay_plain_text():
    result = packet(title=r'Packet (review) \ no operators')
    assert r'Packet (review) \ no operators' in result.extracted_text


def test_non_synthetic_or_unknown_source_commitment_refused():
    with pytest.raises(ValueError):
        build_referral_pdf(accepted_scribe='reported facts', visit_prep='review only', owner_label='owner',
            source_sha256='not-a-hash', synthetic_only=True)
