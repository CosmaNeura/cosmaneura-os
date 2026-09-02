# Codex bundle — validate Cosmas_OS against Azure ground truth
**Date:** 1 Sep 2026  
**Job:** Inspect live Azure + `cosmaneura-master` and say what is **true**, what the spec **assumed**, and what would **break** if we stood `cosmaneura-os` beside it. Do not merge to prod. Do not use prod credentials in a swarm. Do not copy PHI into fixtures.

## What to read
1. This brief
2. `Cosmas_OS_codex_pack.json` v1.8 (machine spec)
3. `Cosmas_OS_Product_Technical_Specs_and_Roadmap.pdf` v1.8
4. `cosmaneura-grok-context-pack.md` §2 stack, §4 INV-6, §5 repos

## Ground truth the spec now claims (confirm or file a CH)
| Claim | Expected if master is healthy |
|---|---|
| Runtime | Python FastAPI + **Celery** + **Postgres** + **Redis** on Azure |
| Models | Azure OpenAI gpt-4.1 (BAA) |
| Capture | AssemblyAI; Recall.ai on telehealth path |
| Identity | **Clerk** users exist; map `clerk_user_id` → Seat — do not add Entra |
| Billing | Stripe; SKU must be **$60** not $89 |
| Notes | Upload → SOAP already live |
| Security | BAA path; hash-binding + immutable records somewhere in master |
| Credits | ~$100k Azure, expire Jan 2027 |
| IAM defect | `cosmaneura-gha-prod` PR-subject federation over prod RG + Terraform-state RG (**INV-6 still open**) |

## Environments you must keep separate
1. **synth** — `cosmaneura-os` + Docker Compose + seed fixtures. Swarm OK. Zero prod secrets.
2. **early-adopter beta** — dedicated RG, clinic BAA, Clerk org, human deploy, L0. No swarm.
3. **prod** — `cosmaneura-master` / MCD. OS code enters only by human PR after INV-6.

## Validate inside Azure (read-only first)
Produce a short inventory. Do not apply Terraform.

- Resource groups, App Services / Container Apps, Postgres flexible server, Redis, Storage accounts, Key Vaults, Service Bus vs Redis-as-broker, OpenAI resource, Clerk instance (config only).
- Which identities can deploy (GitHub OIDC subjects). Flag any `pull_request` subject that can touch prod.
- Network: public endpoints vs VNet/private endpoints (`cosmaneura-scribe` was the pattern repo).
- Celery workers: queues named, concurrency, dead-letter story.
- Blob containers that would hold streams / card copies / workbook backups; lifecycle rules if any.
- Existing Clerk application IDs / orgs (no user dumps).
- Stripe mode (test vs live) and current price IDs.
- Athena / Acuity: are there any live credentials, sandbox only, or none?

## Design checks (code + config, no new features)
- Can FastAPI grow a first-party MCP tool list (`soap.draft`, `stream.append`) without a new language?
- Where would `ToggleFile` live today (env flags vs DB)? Spec wants **Postgres per Org**.
- Where would F-8 tickets live? If anything feature-local exists, mark it as a defect-to-fold.
- Audio artifacts: current TTL. Spec: raw audio **72h**; transcript **max(final submit, 1 year)**.
- Idempotency: any existing `Idempotency-Key` on writes?
- Multi-tenant isolation today: one DB + `org_id` vs one DB per gym? Early-adopter beta needs isolation from MCD.
- WorkbookPort: is there anywhere a writable disk that is **not** ephemeral app-service local disk? Spec requires Blob copy-on-write.

## What to emit
For each item use:

```
CHECK: <name>
STATUS: confirmed | missing | contradicts-spec | blocked-INV-6
EVIDENCE: <resource or file path, no secrets>
SPEC_REF: <pack key or spec section>
NEXT: <one action, human-only if prod>
```

Also emit:
- A proposed **beta RG sketch** (resource list only, no apply) that copies master’s shapes.
- A **fixture kit list** for synth (no PHI): seed Org, Clerk test users, canned transcript, `LabBook.xlsx` headers for RRM demo (EPIC-16).
- INV-6 closeout steps if still open (federation subjects, split plan/apply).

## Hard stops
- No prod PHI in the OS repo or in this bundle’s outputs.
- No FRAGILE browser jobs.
- No Composio.
- No second IdP.
- Do not “fix” INV-6 by widening the existing SP.
