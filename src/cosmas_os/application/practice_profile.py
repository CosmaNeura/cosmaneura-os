"""Structured preferences rendered into the existing bounded helper context."""
FIELDS = {"practice_name": "Practice name", "specialty": "Specialty", "provider_name": "Provider name",
    "credentials": "Credentials", "state": "State", "note_format": "Default note format", "language": "Language"}


def context(configuration):
    profile = configuration.get("practice_profile") or {}
    lines = [f"{label}: {profile[key]}" for key, label in FIELDS.items() if profile.get(key)]
    if configuration.get("practice_context"):
        lines.append(configuration["practice_context"])
    return "\n".join(lines)
