from __future__ import annotations

# Both API and worker readiness must reject a database that has not reached the
# exact application revision shipped in the image.
EXPECTED_SCHEMA_REVISION = "d91e7a3c5b20"
