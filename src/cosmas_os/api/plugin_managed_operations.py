"""Callable managed-connector operations use existing authenticated handlers.

No operation grants an account, attests new human review, approves work or sends
externally. Read admissions retain their existing exact scope and one-shot rules.
"""

from cosmas_os.api import efax_inbound_schemas as efax
from cosmas_os.api import fax_inbound_schemas as fax
from cosmas_os.api import finance_setup_schemas as finance_setup
from cosmas_os.api import finance_work_schemas as finance
from cosmas_os.api import inbox_handoff_schemas as handoff
from cosmas_os.api import inbox_work_schemas as inbox
from cosmas_os.api import portal_setup_schemas as portal_setup
from cosmas_os.api import portal_work_schemas as portal
from cosmas_os.api.plugin_catalog import Operation
from cosmas_os.api.vendor_work_schemas import BoundCommand, VendorResolve

EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
OWNER = ("current authenticated owner and exact saved account/resource binding",
         "current feature, connector grant and source permissions; no new authority")
SAVED = "Inspect retained state and exact evidence; configured accounts and pending claims are not successful outcomes."
RECOVERY = "Read the retained receipt using the original key/hash; missing or uncertain is not success and never authorizes redispatch."


def operation(plugin, name, title, description, path, header, *, model=None,
              completion="Current retained state and exact evidence only.", recovery=RECOVERY,
              permission=OWNER, tests=(), read_only=True, deadline=45, method="POST"):
    return Operation(
        id=f"{plugin}.{name}", plugin=plugin, title=title, description=description,
        path=path, header=header, request=model.model_json_schema() if model else EMPTY.copy(),
        permission=permission, health_check=SAVED, completion=completion, recovery=recovery,
        tests=tests, read_only=read_only, deadline_seconds=deadline, method=method,
        agent_callable=True,
    )


def fax_operations():
    result = []
    for plugin, prefix, schema, label, tests in (
        ("fax_inbound", "/fax-inbound", fax, "SRFax, Documo or Spruce",
         ("tests/integration/test_fax_inbound_api.py", "tests/unit/test_fax_inbound_providers.py")),
        ("efax_inbound", "/efax-inbound", efax, "eFax Corporate",
         ("tests/integration/test_efax_inbound_api.py", "tests/unit/test_efax_inbound.py")),
    ):
        header = "X-Cosmas-Fax-Inbound" if schema is fax else "X-Cosmas-EFax-Inbound"
        result.extend((
            operation(plugin, "status", f"Check {label} receiving setup",
                      "Read installed receiving accounts and current grant state. The owner must review the account and grant in Settings before a new read.",
                      prefix, header, method="GET", tests=tests),
            operation(plugin, "read_metadata", f"Read received {label} fax metadata",
                      "Perform one explicitly bounded metadata observation with the existing grant, selected dates and limit. No fax image is downloaded or marked read.",
                      prefix + "/observe", header, model=schema.Observe, tests=tests,
                      completion="Retained observation and exact source hashes; empty, failed and unconfirmed stay distinct.",
                      recovery=prefix + "/resolve with the original observation key; never repeat provider I/O to recover a lost reply."),
            operation(plugin, "prepare_image", f"Prepare a received {label} fax for review",
                      "Save an exact image proposal from retained metadata. The owner must review and approve the selected fax in the existing work queue before acquisition.",
                      prefix + "/propose", header, model=schema.Propose, read_only=False, tests=tests,
                      completion="Saved proposal/revision only; no human approval, image download or source sharing.",
                      recovery=prefix + "/resolve with the original proposal key before considering another intent."),
            operation(plugin, "inspect_image_proposal", f"Check saved {label} image work",
                      "Read the saved image proposal and exact approval/acquisition state. This does not approve or execute the proposal.",
                      prefix + ("/proposal/{ticket_id}/{revision_id}" if schema is fax else "/proposals/{ticket_id}"),
                      header, method="GET", tests=tests),
            operation(plugin, "read_saved_document", f"Read an acquired {label} fax PDF",
                      "Read the already acquired private PDF under current account/grant custody. Returns application/pdf bytes; no new provider read or mark-read action.",
                      prefix + ("/document/{operation_id}" if schema is fax else "/documents/{operation_id}"),
                      header, method="GET", tests=tests,
                      completion="Exact retained PDF bytes only; revoked, expired or changed custody withholds access."),
            operation(plugin, "resolve", f"Recover a {label} receiving receipt",
                      "Read the retained command, metadata or acquisition receipt by its original key. Recovery performs no provider request.",
                      prefix + "/resolve", header, model=schema.Resolve, tests=tests),
            operation(plugin, "resolve_reviewed_source", f"Recover a reviewed {label} passage save",
                      "Read a passage-save receipt after the owner reviewed and saved the exact document/text in the encounter. No new review assertion or save is made; source_withheld remains explicit after revocation.",
                      "/workspaces/{workspace_id}" + prefix + "-source/resolve", header,
                      model=fax.Resolve if schema is fax else efax.SourceResolve,
                      tests=("tests/integration/test_fax_inbound_source_api.py",) if schema is fax
                      else ("tests/integration/test_efax_inbound_source_api.py",),
                      completion="Exact saved source receipt, including saved/not_found and source_withheld; saved is not a clinical sign-off."),
        ))
    result.append(operation(
        "fax_inbound", "acquire_approved_image", "Read an approved SRFax or Documo fax image",
        "Acquire the exact already human-approved image once. This does not mark it read. Spruce remains metadata-only while its download host is unverified; an uncertain attempt is not retried.",
        "/fax-inbound/acquire", "X-Cosmas-Fax-Inbound", model=fax.Acquire,
        permission=OWNER + ("existing exact human F-8 approval, current revision/version and approval hash",),
        completion="Retained acquisition state; only acquired establishes a qualified stored PDF.",
        recovery="/fax-inbound/resolve with the original acquisition key; never acquire again to recover a lost response.",
        tests=("tests/integration/test_fax_inbound_api.py",),
    ))
    return result


def work_operations(plugin, prefix, header, schema, tests, *, read_action):
    result = [operation(
        plugin, "prepare", f"Prepare {plugin} work for review",
        "Save a private proposal using an already reviewed note and exact current setup/account mappings. Human approval and external submission remain separate in the existing work queue.",
        prefix, header, model=schema.FinanceProposal if schema is finance else schema.Proposal,
        tests=tests, read_only=False, completion="Exact saved proposal and request hash only; no external submission or successful outcome.",
        recovery=prefix + "/resolve with the exact original proposal key/hash.",
    )]
    for name, suffix, title in (("list_work", "", "List saved work"),
                                ("inspect_work", "/{ticket_id}", "Read saved work"),
                                ("read_observations", "/{ticket_id}/observations", "Read retained observations")):
        result.append(operation(plugin, name, title,
                                "Read saved local state and evidence. This is not a fresh provider status request or approval.",
                                prefix + suffix, header, tests=tests, method="GET"))
    result.extend((
        operation(plugin, "read_provider_status", f"Read current {plugin} status",
                  "Perform a deliberate read for the exact saved operation/reference under current read permission. No submission, confirmation, capture or other external mutation is requested.",
                  prefix + "/{ticket_id}/" + read_action, header, model=BoundCommand if schema is finance else portal.Bound,
                  tests=tests, completion="Saved read claim; inspect retained observations for the provider outcome. Pending or unknown is not success.",
                  recovery=prefix + "/resolve with the original read key/hash; never poll automatically or resubmit."),
        operation(plugin, "resolve", f"Recover {plugin} work",
                  "Read a retained command receipt by exact original kind, key and request hash without provider I/O.",
                  prefix + "/resolve", header, model=schema.FinanceResolve if schema is finance else schema.Resolve, tests=tests),
    ))
    return result


def setup_reads(plugin, prefix, header, schema, id_name, tests):
    result = []
    for name, suffix, title in (("setup_status", "", "Check installed setup and review state"),
                                ("inspect_setup", "/{" + id_name + "}", "Read exact saved setup"),
                                ("setup_history", "/{" + id_name + "}/history", "Read setup history")):
        result.append(operation(plugin, name, title,
                                "Read installed account/profile metadata and owner review state. New account selection, credentials and activation require the existing Settings workflow.",
                                prefix + suffix, header, method="GET", tests=tests))
    result.append(operation(plugin, "resolve_setup", "Recover a saved setup receipt",
                            "Read the exact prior setup receipt. No new setup proposal, review, activation or revoke command is performed.",
                            prefix + "/resolve", header, model=schema.Resolve, tests=tests))
    return result


def definitions() -> tuple[Operation, ...]:
    result = fax_operations()
    portal_tests = ("tests/integration/test_portal_work.py", "tests/integration/test_portal_work_runtime.py")
    finance_tests = ("tests/integration/test_finance_api.py", "tests/integration/test_finance_settings_runtime_guard.py")
    result.extend(work_operations("portal", "/workspaces/{workspace_id}/portal-work",
                                  "X-Cosmas-Portal-Work-Contract", portal, portal_tests, read_action="status"))
    result.extend(work_operations("stripe", "/workspaces/{workspace_id}/finance-work",
                                  "X-Cosmas-Finance-Contract", finance, finance_tests, read_action="reconcile"))
    result.extend(setup_reads("portal", "/portal-setup", "X-Cosmas-Portal-Contract", portal_setup,
                              "connection_id", ("tests/integration/test_portal_setup.py",)))
    result.extend(setup_reads("stripe", "/finance-setup", "X-Cosmas-Finance-Setup-Contract", finance_setup,
                              "setup_id", ("tests/integration/test_finance_settings.py",)))
    result.append(operation(
        "stripe", "read_options", "Read reviewed payment account/customer choices",
        "Read current reviewed account/customer choices for the encounter. Preparing an unconfirmed PaymentIntent is not payment; confirmation and capture are not exposed.",
        "/workspaces/{workspace_id}/finance-work/options", "X-Cosmas-Finance-Contract", method="GET", tests=finance_tests,
    ))
    inbox_tests = ("tests/integration/test_inbox_main_app.py", "tests/integration/test_inbox_review_options.py")
    for name, suffix in (("list_inbox", ""), ("inspect_inbox", "/{item_id}"),
                          ("inbox_history", "/{item_id}/history"),
                          ("read_inbox_source", "/{item_id}/sources/{source_id}"),
                          ("inbox_review_options", "/{item_id}/review-options")):
        result.append(operation(
            "spruce", name, "Read retained Spruce inbox work",
            "Read retained owner inbox state/source or current human review choices. This does not fetch a new provider item, assert human review, send a reply or publish a handoff; an installed current inbox registry is required.",
            "/inbox" + suffix, "X-Cosmas-Inbox-Contract", method="GET", deadline=15, tests=inbox_tests,
        ))
    result.append(operation(
        "spruce", "resolve_inbox", "Recover a Spruce local inbox receipt",
        "Read the retained local review command receipt without repeating a source read or attesting a new review.",
        "/inbox/resolve", "X-Cosmas-Inbox-Contract", model=inbox.Resolve, deadline=15, tests=inbox_tests,
    ))
    for name, path, model in (
        ("list_handoffs", "/inbox-handoffs", None),
        ("inspect_handoff", "/inbox-handoffs/{ticket_id}", None),
        ("resolve_handoff", "/inbox-handoffs/{ticket_id}/resolve", handoff.Resolve),
    ):
        result.append(operation(
            "spruce", name, "Read saved inbox handoff responsibility",
            "Read a saved human-reviewed handoff or its original command receipt. No offer, acceptance, human publication approval or external action is performed.",
            path, "X-Cosmas-Inbox-Handoff-Contract", model=model, method="POST" if model else "GET", deadline=15,
            tests=("tests/integration/test_inbox_handoff_main_app.py",),
        ))
    for name, suffix, model in (("read_options", "/options", None), ("list_work", "", None),
                                ("inspect_work", "/{ticket_id}", None),
                                ("read_observations", "/{ticket_id}/observations", None),
                                ("resolve", "/resolve", VendorResolve),
                                ("read_provider_status", "/{ticket_id}/reconcile", BoundCommand)):
        result.append(operation(
            "vendor_work", name, "Read or recover saved messaging and fax delivery work",
            "Inspect exact SRFax, Documo, eFax or Spruce saved work. Reconcile deliberately reads the saved provider reference under current read authority; no send or publication is performed.",
            "/workspaces/{workspace_id}/vendor-work" + suffix, "X-Cosmas-Vendor-Contract",
            model=model, method="POST" if model else "GET", deadline=120,
            tests=("tests/integration/test_vendor_work.py", "tests/integration/test_vendor_process.py"),
        ))
    return tuple(result)


def configured(operation, settings, runtime, *, managed=None, portal=None):
    """Feature/supplier availability only; never current account or read authority."""
    if not getattr(settings, "workspace_available", False):
        return False
    name, plugin = operation.id.split(".", 1)[1], operation.plugin
    if plugin == "fax_inbound":
        return bool(getattr(settings, "fax_inbound_enabled", False)
                    and managed is not None and getattr(managed, "has_credentials", False))
    if plugin == "efax_inbound":
        return bool(getattr(settings, "efax_inbound_enabled", False)
                    and (name != "read_metadata" or managed is not None and getattr(managed, "has_credentials", False)))
    if plugin == "portal":
        setup = name in {"setup_status", "inspect_setup", "setup_history", "resolve_setup"}
        return bool(getattr(settings, "portal_setup_enabled" if setup else "portal_work_enabled", False)
                    and (name != "read_provider_status" or getattr(settings, "portal_io_enabled", False)
                         and portal is not None and getattr(portal, "has_execution", False)))
    if plugin == "stripe":
        setup = name in {"setup_status", "inspect_setup", "setup_history", "resolve_setup"}
        return bool(getattr(settings, "finance_setup_enabled" if setup else "finance_work_enabled", False)
                    and (name != "read_provider_status" or getattr(settings, "finance_io_enabled", False)
                         and managed is not None and getattr(managed, "has_credentials", False)))
    if plugin == "spruce":
        handoffs = name in {"list_handoffs", "inspect_handoff", "resolve_handoff"}
        return bool(getattr(settings, "inbox_work_enabled", False)
                    and (not handoffs or getattr(settings, "inbox_handoff_enabled", False)))
    if plugin == "vendor_work":
        return bool(getattr(settings, "vendor_work_enabled", False)
                    and (name != "read_provider_status" or getattr(settings, "vendor_io_enabled", False)
                         and managed is not None and getattr(managed, "has_credentials", False)))
    return False
