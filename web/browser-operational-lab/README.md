# Browser operational laboratory

This optional test drives the actual encounter workspace in headless Chromium through
six synthetic recording, Chief handoff, specialist revision, human acceptance and
reopening journeys. It reuses the signed local API/PostgreSQL fixture. Generated
PCM and simulated speech/model responses are explicit substitutes. The laboratory
starts worker processing through a test endpoint; it does not qualify hosted
authentication, production worker cadence, physical audio or live delivery.

Supply `COSMAS_PLAYWRIGHT_MODULE_URL` as a file URL to an already installed
Playwright `index.mjs` and `COSMAS_CHROMIUM_EXECUTABLE` as the existing browser
path. No tooling is downloaded. Optionally set
`COSMAS_SCRIBE_SPECIALIST_EVIDENCE_DIR` outside the repository.

Run `scripts/check-backend-local.py` with
`tests/integration/test_scribe_to_specialists_browser_lab.py`, `--profile workspace`,
`--postgres-bin` pointing to the installed PostgreSQL tools and
`--pytest-timeout 360`. The runner uses its own local database and the browser
uses local port 5173 exclusively. Without explicit browser tooling the optional
test skips; a skip does not establish browser acceptance.
