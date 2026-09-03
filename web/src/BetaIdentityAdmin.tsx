import { type FormEvent, useState } from "react";
import { api, type ApiIdentity, type BetaIdentitySummary } from "./api";

type BetaIdentity = Extract<ApiIdentity, { mode: "early_adopter_beta" }>;

export function BetaIdentityAdmin({ identity }: { identity: BetaIdentity }) {
  const [open, setOpen] = useState(false);
  const [roster, setRoster] = useState<BetaIdentitySummary[]>([]);
  const [subject, setSubject] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [pending, setPending] = useState(false);
  const [ownerAccessConfirmed, setOwnerAccessConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadRoster() {
    setError(null);
    setNotice(null);
    setPending(true);
    setOwnerAccessConfirmed(false);
    try {
      setRoster(await api.listBetaIdentities(identity));
      setOwnerAccessConfirmed(true);
    } catch (cause) {
      setRoster([]);
      setError(cause instanceof Error ? cause.message : "Access management is unavailable");
    } finally {
      setPending(false);
    }
  }

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) await loadRoster();
  }

  async function bind(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setError(null);
    setNotice(null);
    setPending(true);
    try {
      await api.bindBetaIdentity(identity, {
        clerk_subject: subject,
        display_name: displayName,
        evidence_ref: evidenceRef,
      });
      setSubject("");
      setDisplayName("");
      setEvidenceRef("");
      setNotice("Tester bound to this Cosmas Beta Lab.");
      setRoster(await api.listBetaIdentities(identity));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Tester could not be bound");
    } finally {
      setPending(false);
    }
  }

  async function change(
    member: BetaIdentitySummary,
    operation: "deactivate" | "reactivate" | "transfer",
  ) {
    if (pending || !evidenceRef) return;
    const destructive = operation === "deactivate" || operation === "transfer";
    if (
      destructive &&
      !window.confirm(
        operation === "transfer"
          ? `Transfer ownership to ${member.display_name}? You will immediately lose owner access.`
          : `Deactivate ${member.display_name} in Cosmas OS?`,
      )
    ) {
      return;
    }

    setError(null);
    setNotice(null);
    setPending(true);
    try {
      const body = { clerk_subject: member.clerk_subject, evidence_ref: evidenceRef };
      if (operation === "deactivate") await api.deactivateBetaIdentity(identity, body);
      if (operation === "reactivate") await api.reactivateBetaIdentity(identity, body);
      if (operation === "transfer") await api.transferBetaOwnership(identity, body);
      if (operation === "transfer") {
        setEvidenceRef("");
        setRoster([]);
        setOwnerAccessConfirmed(false);
        setNotice("Ownership transferred. This session no longer has owner authority.");
        return;
      }
      setEvidenceRef("");
      setNotice(operation === "deactivate" ? "Tester deactivated." : "Tester reactivated.");
      setRoster(await api.listBetaIdentities(identity));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Identity change failed");
    } finally {
      setPending(false);
    }
  }

  async function purgeRetention() {
    if (
      pending ||
      !window.confirm(
        "Run the owner-only physical purge for every due synthetic artifact in this Box? " +
          "This removes application references and requires no recoverable Blob object, " +
          "version, or snapshot to remain through Azure APIs. It cannot be undone.",
      )
    ) {
      return;
    }

    setError(null);
    setNotice(null);
    setPending(true);
    try {
      const result = await api.purgeRetention(identity);
      const count = result.receipts.length;
      setNotice(`Retention purge complete. ${count} due artifact${count === 1 ? "" : "s"} purged.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Retention purge failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      className="panel identity-admin"
      aria-busy={pending}
      aria-labelledby="identity-admin-heading"
    >
      <div className="row identity-admin-heading">
        <div>
          <h2 id="identity-admin-heading">Beta Lab access</h2>
          <p className="meta">Cosmas owner controls for reviewed Clerk identities.</p>
        </div>
        <button
          type="button"
          aria-controls="identity-admin-controls"
          aria-expanded={open}
          disabled={pending}
          onClick={toggle}
        >
          {open ? "Hide access" : "Manage access"}
        </button>
      </div>

      {open ? (
        <div id="identity-admin-controls">
          <p className="meta">
            Invite the tester to Cosmas Beta Lab in Clerk first, then bind the exact Clerk
            user ID here. Never enter an email address, clinic name, or patient information.
          </p>
          {error ? (
            <p className="error" role="alert">
              {error}
            </p>
          ) : null}
          {notice ? (
            <p className="notice" role="status">
              {notice}
            </p>
          ) : null}

          {pending && !ownerAccessConfirmed ? <p role="status">Checking owner access…</p> : null}

          {ownerAccessConfirmed ? (
            <>
              <form className="identity-form" onSubmit={bind}>
                <label>
                  Clerk user ID
                  <input
                    aria-label="Clerk user ID"
                    autoComplete="off"
                    maxLength={255}
                    pattern="user_[A-Za-z0-9]+"
                    placeholder="user_…"
                    required
                    spellCheck={false}
                    value={subject}
                    onChange={(event) => setSubject(event.target.value)}
                  />
                </label>
                <label>
                  Display name
                  <input
                    aria-label="Display name"
                    autoComplete="off"
                    maxLength={200}
                    required
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                  />
                </label>
                <label>
                  Opaque evidence reference
                  <input
                    aria-label="Opaque evidence reference"
                    autoComplete="off"
                    maxLength={255}
                    required
                    spellCheck={false}
                    value={evidenceRef}
                    onChange={(event) => setEvidenceRef(event.target.value)}
                  />
                </label>
                <button className="primary" type="submit" disabled={pending}>
                  Bind invited tester
                </button>
              </form>

              <div className="identity-roster" aria-label="Beta Lab identity roster">
                {roster.map((member) => (
                  <article className="identity-member" key={member.clerk_subject}>
                    <div>
                      <strong>{member.display_name}</strong>
                      <div className="meta identity-subject">{member.clerk_subject}</div>
                      <div className="meta">
                        {member.is_owner ? "Owner" : "Tester"} ·{" "}
                        {member.active ? "active" : "inactive"}
                      </div>
                    </div>
                    <div className="row">
                      {!member.is_owner && member.active ? (
                        <button
                          type="button"
                          disabled={pending || !evidenceRef}
                          onClick={() => change(member, "deactivate")}
                        >
                          Deactivate
                        </button>
                      ) : null}
                      {!member.is_owner && !member.active ? (
                        <button
                          type="button"
                          disabled={pending || !evidenceRef}
                          onClick={() => change(member, "reactivate")}
                        >
                          Reactivate
                        </button>
                      ) : null}
                      {!member.is_owner && member.active ? (
                        <button
                          type="button"
                          disabled={pending || !evidenceRef}
                          onClick={() => change(member, "transfer")}
                        >
                          Transfer ownership
                        </button>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
              <p className="meta">
                Deactivating here blocks Cosmas immediately. Also remove the Clerk Organization
                membership and revoke its sessions in the Clerk dashboard.
              </p>

              <section className="retention-admin" aria-labelledby="retention-admin-heading">
                <h3 id="retention-admin-heading">Retention</h3>
                <p className="meta">
                  Owner-only synthetic D3 action. Artifact storage versioning and soft delete are
                  disabled, so deleted objects cannot be recovered through Azure APIs. Never use
                  PHI here; authorized-beta retention requires a separate reviewed design.
                </p>
                <button type="button" disabled={pending} onClick={purgeRetention}>
                  Run retention purge
                </button>
              </section>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
