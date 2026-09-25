# Configure public Research sources

Add `--research /absolute/path/to/reviewed-research.json` to the ordinary
`prepare-operational-startup.py` command. It composes with `--connections` and
preserves all existing account, capture and separate read-only Athena settings.
Omitting the option keeps the original behavior. Python 3 and Node.js suffice;
the preparer imports no service or publisher client.

`operational-research.example.json` shows all nine sources using invented dataset
identities, versions, hashes and a secret reference. Research I/O is false in
that example. Replace the invented inputs with the reviewed source selection
before release. Set `enabled` to true to select I/O for the intended deployment;
generating the files performs no query, deployment or activation.

| Sources | Required preparation |
| --- | --- |
| PubMed, ClinicalTrials.gov, DailyMed, RxNorm, CMS Coverage, NPI Registry | List the desired source IDs. These readers require no key in the current runtime. |
| openFDA | Select `openfda` with a separate immutable Key Vault `openfda_api_key` reference. Never place the key itself in this file. |
| CMS Open Data | Select `cms_open_data` and supply its dataset UUID, column mapping, exact version and release date. |
| Medicare Care Compare | Select `medicare_care_compare` and supply its dataset ID, column mapping, version, release date, distribution index and pinned metadata/schema hashes. |

For a setup without credentials or mapped datasets, select only the first row's
sources, set `openfda_api_key` to null and `dataset_mappings` to `{}`. A mapping
must be present for each selected mapped source and absent for unselected sources.
The pinned `research_contract.py` definitions are copied from the selected OS
reader's `SOURCES` and `DatasetMapping`; they add no new connector implementation.
Dataset field selection, versioning and fixed publisher endpoints retain the
runtime's existing contract. No arbitrary URL, query, encounter or credential
value belongs in this configuration.

The generated `os.services.tfvars.json` contains the complete source/feature maps
and immutable secret references. Apply it with the existing reviewed foundation,
identity and release inputs. Terraform maps replace earlier maps, so retain this
complete file when adding the separate Athena feature layer. The generated
`research-configuration.json` lists the selected sources, documentation links,
mapping digest and I/O selection for review. Both optional profiles together
produce fourteen top-level files plus eight client identity files.

The existing Research bot still requires a deliberately confirmed public query.
Private notebook, encounter and chat context is not inherited. Saved source
selection and explicit consent remain necessary for AI analysis. Source/license,
quota and real publisher acceptance remain release work; configuration validation
does not assert that an invented or reviewed dataset currently exists. Current
CMS Coverage reads exact NCD IDs; full LCD licensing is separate.
