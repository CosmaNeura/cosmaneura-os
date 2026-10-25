"""Pinned SQL/retained-Python Unicode contract; no provider or database calls."""

import re
import unicodedata
from pathlib import Path
from runpy import run_path


def test_sql_category_c_metadata_matches_retained_python_unicode_contract():
    module = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "migrations/versions/p35b1d4f9876_calendar_import_source.py"
        )
    )
    assert module["UNICODE_VERSION"] == unicodedata.unidata_version
    expected = []
    start = None
    for point in range(0x110000):
        excluded = unicodedata.category(chr(point)).startswith("C")
        if excluded and start is None:
            start = point
        if not excluded and start is not None:
            expected.append((start, point))
            start = None
    if start is not None:
        expected.append((start, 0x110000))
    actual = [
        tuple(map(int, pair))
        for pair in re.findall(r"\[([0-9]+),([0-9]+)\)", module["UNICODE_C_RANGES"])
    ]
    assert actual == expected
