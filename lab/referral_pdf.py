"""Bounded invented referral-review PDF; generation establishes no delivery.

Courier uses a constant 0.6-em advance, so wrapped lines fit the Letter page's
504-point text region. Unsupported glyphs, excess pages and input drift fail
instead of silently dropping or replacing text. Custody and review are external.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from io import BytesIO
from textwrap import TextWrapper

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

FONT_SIZE = 9
ADVANCE = FONT_SIZE * 0.6
TEXT_WIDTH = 504
COLUMNS = int(TEXT_WIDTH // ADVANCE)
ROWS = 53
MAX_PAGES = 3


def sha(value):
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ReferralPDF:
    data: bytes
    pdf_sha256: str
    extracted_text: str
    extracted_text_sha256: str
    pages: int
    source_sha256: str
    accepted_scribe_sha256: str
    visit_prep_sha256: str


def _text(value, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError("bounded text required")
    if any(ord(character) < 32 and character != "\n" or ord(character) == 127 for character in value):
        raise ValueError("control characters refused")
    try:
        value.encode("cp1252", errors="strict")
    except UnicodeEncodeError:
        raise ValueError("unsupported PDF glyph; preserve text for another renderer") from None
    return value


def _literal(text):
    raw = text.encode("cp1252")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def build_referral_pdf(*, accepted_scribe, visit_prep, owner_label, source_sha256,
                       title="Referral packet for coordinator review", synthetic_only):
    """Return actual PDF bytes and extraction hashes from exact supplied texts.

    source_sha256 is the caller's actual reviewed source commitment, distinct
    from the accepted Scribe answer hash. The helper cannot attest source origin,
    human acceptance, custody, preview, recipient permission or completion.
    """
    if synthetic_only is not True or not re.fullmatch(r"[a-f0-9]{64}", source_sha256 or ""):
        raise ValueError("synthetic scope and source commitment required")
    accepted_scribe = _text(accepted_scribe, 12000)
    visit_prep = _text(visit_prep, 4000)
    owner_label = _text(owner_label, 120)
    title = _text(title, 160)
    if "\n" in owner_label or "\n" in title:
        raise ValueError("single-line label required")
    scribe_sha, prep_sha = sha(accepted_scribe.encode()), sha(visit_prep.encode())
    text = ("SYNTHETIC LOCAL TEST - NOT SENT - HUMAN REVIEW REQUIRED\n" + title
        + "\nReview owner: " + owner_label + "\nReviewed source SHA-256: " + source_sha256
        + "\nAccepted Scribe text SHA-256: " + scribe_sha + "\nVisit Prep text SHA-256: " + prep_sha
        + "\n\nAccepted Scribe text (unchanged facts):\n" + accepted_scribe
        + "\n\nVisit Prep review checklist (unchanged facts):\n" + visit_prep
        + "\n\nPacket preparation does not establish referral delivery, diagnosis, treatment or booking.")
    wrapper = TextWrapper(width=COLUMNS, expand_tabs=False, replace_whitespace=False,
                          drop_whitespace=False, break_long_words=True, break_on_hyphens=False)
    lines = [line for paragraph in text.split("\n") for line in (wrapper.wrap(paragraph) or [""])]
    if len(lines) > ROWS * MAX_PAGES:
        raise ValueError("packet exceeds three pages; no truncation")
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Courier"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding")})
    font_ref = writer._add_object(font)
    for index in range(0, len(lines), ROWS):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): font_ref})})
        stream = DecodedStreamObject()
        commands = [b"BT /F1 9 Tf 12 TL 54 738 Td"]
        for line in lines[index:index + ROWS]:
            if len(line) * ADVANCE > TEXT_WIDTH:
                raise ValueError("text width exceeded")
            commands.extend((_literal(line) + b" Tj", b"T*"))
        commands.append(b"ET")
        stream.set_data(b"\n".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": title, "/Subject": "Synthetic review packet; not a signed or sent referral"})
    target = BytesIO()
    writer.write(target)
    data = target.getvalue()
    reader = PdfReader(BytesIO(data), strict=True)
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    # Every emitted line must survive PDF decoding exactly. Wrapping only adds
    # visible line boundaries; the original inputs retain their own hashes.
    extracted_lines = extracted.splitlines()
    if [line for line in extracted_lines if line] != [line for line in lines if line]:
        raise ValueError("PDF extraction changed content")
    return ReferralPDF(data, sha(data), extracted, sha(extracted.encode()), len(reader.pages),
                       source_sha256, scribe_sha, prep_sha)
