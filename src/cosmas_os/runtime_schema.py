from __future__ import annotations

# Both API and worker readiness must reject a database that has not reached the
# exact application revision shipped in the image.
EXPECTED_SCHEMA_REVISION = "f96b1c4d2357"
