from cosmas_os.application.practice_profile import FIELDS, context


def test_fields_contract():
    expected = [
        ("practice_name", "Practice name"),
        ("specialty", "Specialty"),
        ("provider_name", "Provider name"),
        ("credentials", "Credentials"),
        ("state", "State"),
        ("note_format", "Default note format"),
        ("language", "Language"),
    ]
    assert list(FIELDS.items()) == expected


def test_context_empty():
    assert context({}) == ""
    assert (
        context({"practice_profile": None, "practice_context": "Direct Primary Care"})
        == "Direct Primary Care"
    )


def test_context_partial_with_extra():
    config = {
        "practice_profile": {
            "practice_name": "Synthetic Clinic",
            "specialty": "Family medicine",
            "language": "English",
        },
        "practice_context": "Extra note",
    }
    expected = (
        "Practice name: Synthetic Clinic\nSpecialty: Family medicine\nLanguage: English\nExtra note"
    )
    assert context(config) == expected


def test_context_all_fields():
    config = {"practice_profile": {k: "v" for k in FIELDS}}
    expected = (
        "Practice name: v\n"
        "Specialty: v\n"
        "Provider name: v\n"
        "Credentials: v\n"
        "State: v\n"
        "Default note format: v\n"
        "Language: v"
    )
    assert context(config) == expected


def test_context_skips_empty_and_unknown():
    config = {
        "practice_profile": {"practice_name": "", "state": "NY", "bogus": "x"},
        "practice_context": "",
    }
    assert context(config) == "State: NY"


def test_context_negative_drop_context():
    # Baseline: {"practice_profile": {"practice_name": "Synthetic Clinic", "specialty": "Family medicine", "language": "English"}, "practice_context": "Extra note"}
    # Change: drop practice_context
    config = {
        "practice_profile": {
            "practice_name": "Synthetic Clinic",
            "specialty": "Family medicine",
            "language": "English",
        }
    }
    expected = "Practice name: Synthetic Clinic\nSpecialty: Family medicine\nLanguage: English"
    assert context(config) == expected


def test_context_negative_empty_field():
    # Baseline: {"practice_profile": {"practice_name": "Synthetic Clinic", "specialty": "Family medicine", "language": "English"}, "practice_context": "Extra note"}
    # Change: practice_name ""
    config = {
        "practice_profile": {
            "practice_name": "",
            "specialty": "Family medicine",
            "language": "English",
        },
        "practice_context": "Extra note",
    }
    expected = "Specialty: Family medicine\nLanguage: English\nExtra note"
    assert context(config) == expected


def test_context_negative_extra_key():
    # Baseline: {"practice_profile": {"practice_name": "Synthetic Clinic", "specialty": "Family medicine", "language": "English"}, "practice_context": "Extra note"}
    # Change: an extra key "bogus"
    config = {
        "practice_profile": {
            "practice_name": "Synthetic Clinic",
            "specialty": "Family medicine",
            "language": "English",
            "bogus": "x",
        },
        "practice_context": "Extra note",
    }
    expected = (
        "Practice name: Synthetic Clinic\nSpecialty: Family medicine\nLanguage: English\nExtra note"
    )
    assert context(config) == expected
