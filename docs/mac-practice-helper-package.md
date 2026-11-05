# Mac practice-helper package (one path)

Use this when a practice finishes CosmaBot signup and needs the Mac helper so
**Open Chief** can run in the signed desktop app. Packaging and Infos only —
this path does **not** sign, notarize, upload to App Store Connect, or flip
production DNS/Clerk.

## One command

From tip of `main`, after you already have a compiled/packaged auth helper (or
Swift compiler products) and a matching desktop renderer dist:

```sh
python3 scripts/compose-mac-practice-helper.py \
  --native-practice-config /absolute/path/to/reviewed-public-native-practice.json \
  --native-identity-config /absolute/path/to/retained-startup/clients/desktop-identity.json \
  --native-auth-helper /absolute/path/to/CosmasAuth.app \
  --web-dist /absolute/path/to/desktop-renderer/dist \
  --output /absolute/path/to/fresh-mac-practice-helper-package
```

Or package the helper from compiler products in the same command:

```sh
python3 scripts/compose-mac-practice-helper.py \
  --native-practice-config /absolute/path/to/reviewed-public-native-practice.json \
  --native-identity-config /absolute/path/to/retained-startup/clients/desktop-identity.json \
  --products /absolute/path/to/new-native-auth-build/products \
  --qualification /absolute/path/to/native-auth-qualification \
  --compiler-receipt /absolute/path/to/new-native-auth-build/compiler-receipt.json \
  --web-dist /absolute/path/to/desktop-renderer/dist \
  --output /absolute/path/to/fresh-mac-practice-helper-package
```

## One artifact

Open `<output>/package-manifest.json`. That file is the canonical pointer:

| Path | Role |
| --- | --- |
| `package-manifest.json` | Canonical artifact inventory |
| `AFTER-SIGNUP-OPEN-CHIEF.md` | Signup-finished → install → Open Chief |
| `CosmasAuth.app/` | Auth helper (Infos embedded when packaged here) |
| `composed-desktop/` | Electron composition bound to Infos |

Do not hunt older zip trees or CFBundleVersion 1107 leftovers.

## Infos + fail-closed rules (unchanged)

| Infos profile | Default hosted origin | Default data mode | Fake host (`--enable-fake-practice-host`) |
| --- | --- | --- | --- |
| `operational-beta-v1` | `https://enrollment-api.cosmas.ai` | `authorized_beta` | **Refused** |
| `operational-staging-v1` | Infos `accountOrigin` (staging enrollment API) | `synthetic` | Allowed for local L0 only |

Production Infos still fail-close Clerk account sign-in / Open Chief until a
**signed** CosmasNativePracticeConnection helper exists on John's Mac. This
script never signs.

Never combine production Infos with `--enable-fake-practice-host` or
`--data-mode synthetic`.

## After signup (operator)

1. Practice reaches CosmaBot signup **ready**.
2. John signs/notarizes the Mac package from this directory on a Mac (`.p8`
   stays on the Mac; agents do not sign).
3. Install the notarized app.
4. Open the Mac helper, sign in with the same CosmaBot account, then **Open Chief**.

Open Chief is not the install step. Browser Open Chief remains available for
already-supported hosted paths; Mac real-data Open Chief needs the signed helper.

## Related

- Multi-step composers: `docs/operational-native-build.md`
- Desktop ASAR/fuse packaging (still unsigned): `docs/desktop-release-packaging.md`
- Enrollment UI install + Open Chief: CosmaBot signup **ready** stage
