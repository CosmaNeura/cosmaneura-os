# Prescription and eFax sandbox scaffolds (Track 3)

Tonight for existing live users: nothing changes. These packages are
mock-placeholder contracts and stubs only. Send and read gates stay off.

## What already existed for fax / eFax

Reuse these paths. Do not invent a second fax stack:

- `src/cosmas_os/adapters/vendor_connectors/{efax,srfax,documo,spruce}*`
- `src/cosmas_os/ports/efax_inbound.py`, `ports/fax_inbound.py`
- Existing EFax / Fax inbound UI review panels under `web/src/`

## What this change adds

| Piece | Path | Role |
| --- | --- | --- |
| Rx plugin contract | `src/cosmas_os/plugins/rx/` | Fail-closed send/target/read gates; vendor id is only `unspecified` |
| Rx port | `src/cosmas_os/ports/rx.py` | Closed synthetic status shape |
| Rx adapter stub | `src/cosmas_os/adapters/rx_sandbox.py` | Synthetic observe only when sandbox flag is on |
| eFax plugin contract | `src/cosmas_os/plugins/efax/` | Fail-closed gates over existing provider ids |
| eFax sandbox port | `src/cosmas_os/ports/efax_sandbox.py` | Closed synthetic fax status shape |
| eFax adapter stub | `src/cosmas_os/adapters/efax_sandbox.py` | Synthetic observe only; never calls live connectors |
| Flags | `WORKSPACE_RX_SANDBOX_ENABLED`, `WORKSPACE_EFAX_SANDBOX_ENABLED` | Default false; refused when hosted |
| UI labels | `web/src/connection-guides.ts` | Label strings only; not live catalog actions |

## What must not be added here

- A named prescribing vendor (Surescripts, DoseSpot, or any other)
- Live fax or prescription send
- C8 / C9 EHR wiring
- Infra or deploy flips
- Secrets, vendor accounts, or vendor outreach

## Fail-closed rules

1. **Send.** Always raises `RxSendRefused` / `EFaxSendRefused`.
2. **Production / hosted.** Always refused.
3. **Sandbox read.** Allowed only when the matching sandbox flag is true and
   hosted is false. Returns invented labels only.
4. **Flags off.** Default Settings leave both sandbox flags false, so observe
   refuses with the sandbox-flag message.
