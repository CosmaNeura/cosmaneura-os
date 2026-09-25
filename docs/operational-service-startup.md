# Prepare the operational service connections

`scripts/prepare-operational-startup.py` turns one existing operational desktop
identity and explicit public service bindings into matching client and service
inputs. It reuses the native identity validator and workspace identity preparer.
Python 3 and Node.js are required. Run from this client source directory:

Optional Google, Microsoft and managed-service configuration is described in
[operational connectors](operational-connectors.md); supply `--connections` to
include those existing adapters in the generated inputs.

Optional public Research source selection is described in
[operational research](operational-research.md); supply `--research` to include
the existing nine-source reader and its versioned dataset/key references.

```sh
python3 -B scripts/prepare-operational-startup.py \
  --identity /absolute/path/to/reviewed-desktop-identity.json \
  --bindings /absolute/path/to/reviewed-service-bindings.json \
  --output /absolute/path/to/new-startup-directory
```

Start the bindings file from `operational-service-bindings.example.json`. Its
values are invented. Supply actual reviewed origins, API audiences, caller
identities, practice correspondence and immutable secret references before release.
The preparer reads no account, vault, database or provider. It creates a new
directory exclusively and leaves `.incomplete` on partial failure; do not use a
partial output or overwrite an earlier output.

Version 2 bindings require `core.sovereign_client_id` and
`core.scribe_receiver_client_id`. The latter may be an explicit empty string when
no separate Scribe receiver is configured. The OS runtime identity maps to Core's
`companion_client_id`; Sovereign retains `caller_client_id`. All configured caller
identities, including Core's outbound Scribe workflow identity, must be distinct.
Version 1 inputs are refused by this compiler; supply the actual separate caller
identities before upgrading. Previously frozen release inputs remain unchanged.

The output contains twelve service/connection JSON files and eight client identity
files under `clients/`. The twelve-file count printed by the command excludes the
eight files produced by the delegated identity preparer.

## Use with the selected service foundations

These are additional variable files for existing infrastructure roots. They do
not replace network, database, storage, clinic approval, secrets, image registry,
schema, release or private-provider configuration. Combine them with the selected
release image inputs and the service's existing reviewed foundation inputs. They
do not execute a plan, migration, role grant, worker, build or deployment.

| Input | Existing consumer and effect |
| --- | --- |
| `clients/*` | Existing desktop/iPhone/web identity build inputs and OS identity variables; use the separate native release acceptance evidence described in `operational-workspace-identity.md`. |
| `os.services.tfvars.json` | OS beta environment; authenticated Core capture and connection, invited Scheduling connection, first-party operational screens, exact managed identity and immutable secret references. |
| `core.services.tfvars.json` | Core production root; existing capture, encounter, record and appointment receivers, OS caller authorization and Core-to-Scribe workflow configuration. |
| `scribe.service.tfvars.json` | Scribe infrastructure root; authenticated capture API, fixed practice cohort, long visits, source, corrections and recovery. |
| `scheduling.services.tfvars.json` | Scheduling infrastructure root; staff Google login, Calendar, companion connection, availability and appointment operations. |
| `native-connection-arguments.json` | Arguments for the existing native build scripts: Core web origin, upload origins and Scheduling client/callback. Pass these alongside the generated identity; this file does not invoke a build. |
| `service-bindings.json` | Reviewable correspondence across services; all actual acceptance and installation indicators remain false. |

OS-to-Core uses `api://<Core audience>/.default` and requires the existing
`AgentApi.Access` role for the OS runtime identity. Core-to-Scribe uses
`api://<Scribe audience>/.default` and requires `Scribe.Workflow.Access` for Core's
workflow identity. API audiences and caller identities must remain distinct.
The OS guard checks its actual managed identity; the Core guard checks its actual
workflow identity, Entra tenant and existing Clerk issuer. These guards fail
before the corresponding application resource can proceed.

The Core authority tenant reference, Scribe practice UUID and Scheduling practice
UUID represent explicit reviewed correspondence. They are not interchangeable.
Generating the files does not install tenant mappings, invite users, grant
membership, choose a clinician or connect an account. Existing in-app review and
authorization remain required. Scheduling's public application hostname must
match its binding origin. Its Google staff client is shared with the OS login
flow; its Calendar client is independently specified. Register the existing
service callbacks through each provider's normal configuration process.

## Activate workers in separate phases

Apply `scribe.service.tfvars.json` throughout. Add
`scribe.speech-grants.tfvars.json` to prepare the existing speech job, migration
job and configured-capture database permission selection. Keep
`scribe.speech-consumer.tfvars.json` separate until the reviewed migration,
private speech provider and role acceptance have completed. That final layer
enables the continuous speech worker for the same fixed practice.

Similarly, `scribe.translation-grants.tfvars.json` prepares the translation
identity, private provider binding and existing migration permission selection.
It does not turn on the translation consumer. Add
`scribe.translation-consumer.tfvars.json` only after its existing provider/role
acceptance; retain the speech layers when both consumers are wanted. Translation
endpoint, resource and deployment must identify the same existing Azure account.
Private endpoint, encrypted storage and migration invocation are still supplied
and reviewed through the existing Scribe foundation process.

Terraform object inputs replace earlier objects rather than merging them. The
speech-consumer file therefore repeats the complete capture feature object.
Review effective inputs in the existing release process; do not use a wildcard
that silently enables all activation files.

## Athena and other outside services

The baseline leaves Athena off. After the existing private Athena profile and
read-only service credentials have been accepted, add both
`os.athena-readonly.tfvars.json` and `core.athena-readonly.tfvars.json` to their
respective roots. These files preserve the baseline feature maps and enable only
the existing appointment reads and reviewed local visit correspondence. They
create no Athena write capability or credential/profile material.

Google email and Microsoft account connections, managed messaging/fax/finance
execution, and research provider I/O need their own reviewed provider inputs.
Those I/O switches remain off in this baseline. The first-party setup, work,
research and review screens remain available. A prepared configuration is not
evidence of provider acceptance, native signing/device operation or deployment.
