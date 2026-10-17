# CosmaBot desktop UX acceptance preview

From `web/`, run `pnpm ux:acceptance` and open `http://127.0.0.1:5196/`.
Use `pnpm ux:acceptance:build` to build the isolated preview.

This renders the actual workspace, notebook, review, settings and recording
components. Notebook and review services return explicitly scripted synthetic
results. Private recording uses generated PCM through the actual encrypted
recording controller and storage; the physical microphone is never opened.
Unsupported account and service operations fail rather than simulate success.
The fixture keeps notebook state in this tab and encrypted audio on this browser
origin. Enter invented information only. This preview is separate from the
normal application build and has no hosted credentials or deployment settings.

The repository tests provide signed UI-to-server, recovery, authorization and
capture evidence. This preview is for layout and interaction acceptance; it does
not establish live service reliability, clinical/model quality or native device
acceptance. See `docs/ux/2026-10-16-implementation.md` for the implementation and
validation record.
