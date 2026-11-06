from __future__ import annotations

# Both API and worker readiness must reject a database that has not reached the
# exact application revision shipped in the image.
EXPECTED_SCHEMA_REVISION = "a46f2c09d853"
