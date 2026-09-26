import { useEffect, useRef, useState } from "react";
import { readAvailability, type Availability } from "./scheduling-api";
import { WorkspaceApiError, type AuthenticatedWorkspaceIdentity, type CaptureBotSelection } from "./workspace-api";
import { AppointmentPanel } from "./AppointmentPanel";
import { APPOINTMENTS_BUILD } from "./appointment-api";
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; };

export function SchedulingPanel({workspaceId, identity, bot, name, enabled, locked, onAccessLost}: {
  workspaceId: string; identity: AuthenticatedWorkspaceIdentity; bot: CaptureBotSelection;
  name: string; enabled: boolean; locked: boolean;
  onAccessLost?: (cause: WorkspaceApiError) => void;
}) {
  const [value, setValue] = useState<Availability | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<Availability["slots"][number] | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  const [refreshingSelection, setRefreshingSelection] = useState(false);
  const [selectionRefreshStatus, setSelectionRefreshStatus] = useState<"failed" | "unavailable" | undefined>();
  const [day, setDay] = useState(localDate), [count, setCount] = useState(12);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    setValue(null); setSelectedSlot(null); setExpired(false); setMessage(""); setBusy(false); setRefreshingSelection(false); setSelectionRefreshStatus(undefined); setCount(12);
    return () => active.current?.abort();
  }, [workspaceId, identity, bot.address, bot.team_revision, enabled, day]);
  useEffect(() => {
    if (!value) return;
    // Keep the checked list in place: removing it can move another action under a tap.
    const timer = setTimeout(() => setExpired(true),
      Math.max(0, Date.parse(value.valid_until) - Date.now()));
    return () => clearTimeout(timer);
  }, [value]);
  async function read(keepSelection = false) {
    if (!enabled || locked || busy || !day || keepSelection && !selectedSlot) return;
    const previousSlot = keepSelection ? selectedSlot : null;
    const controller = new AbortController(); active.current?.abort(); active.current = controller;
    setBusy(true); setRefreshingSelection(keepSelection);
    if (!keepSelection) {setValue(null); setSelectedSlot(null); setExpired(false); setMessage(""); setSelectionRefreshStatus(undefined); setCount(12);}
    try {
      // Calendar days in the viewer's zone, including DST transitions.
      const start = new Date(`${day}T00:00:00`), end = new Date(start); end.setDate(end.getDate() + 7);
      const result = await readAvailability(workspaceId, identity, bot,
        {starts_at: start.toISOString(), ends_at: end.toISOString()}, controller.signal);
      if (controller.signal.aborted) return;
      if (!(Date.now() < Date.parse(result.valid_until))) throw new Error("Availability expired");
      setValue(result); setExpired(false);
      if (previousSlot) {
        const match = result.slots.find(slot => Date.parse(slot.starts_at) === Date.parse(previousSlot.starts_at) &&
          Date.parse(slot.ends_at) === Date.parse(previousSlot.ends_at));
        setSelectedSlot(match ?? null);
        setSelectionRefreshStatus(match ? undefined : "unavailable");
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        if (cause instanceof WorkspaceApiError && [401, 403].includes(cause.status)) {
          setValue(null); setSelectedSlot(null); setExpired(true); setSelectionRefreshStatus(undefined);
          setMessage("Scheduling access is unavailable."); onAccessLost?.(cause);
        } else if (keepSelection) {setExpired(true); setSelectionRefreshStatus("failed");}
        else setMessage("Availability could not be confirmed. Refresh the encounter and check the calendar connection before trying again.");
      }
    }
    finally { if (!controller.signal.aborted) {setBusy(false); setRefreshingSelection(false);} }
  }
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return <section className="team-prep" aria-label="Follow-up availability">
    <div className="capture-actions"><label>Week starting <input type="date" aria-label="Availability week starting"
      value={day} disabled={busy || locked} onChange={event => setDay(event.target.value)} /></label>
      <button disabled={!enabled || locked || busy || !day} onClick={() => void read()}>
        {busy && !refreshingSelection ? "Checking calendar…" : "Refresh availability"}</button></div>
    <p className="team-fine">{name} · times shown in {zone}. Times can change; refresh before arranging a visit.</p>
    {message && <p role="status">{message}</p>}
    {value && <>
      <p>{value.label} · Google Calendar checked at {new Date(value.checked_at).toLocaleTimeString()}.</p>
      <p role="status" style={{display: "grid"}}>
        <span style={{gridArea: "1 / 1", visibility: expired ? "hidden" : "visible"}} aria-hidden={expired}>Availability checked. Refresh to check for changes.</span>
        <span style={{gridArea: "1 / 1", visibility: expired ? "visible" : "hidden"}} aria-hidden={!expired}>Availability expired. Refresh to choose a time.</span>
      </p>
      {!value.slots.length ? <p>No available times in this week.</p> : <>
        <p className="team-fine">{value.slots.length} checked times. Nothing has been reserved.</p>
        <ul>{value.slots.slice(0, count).map(slot => <li key={`${slot.starts_at}/${slot.ends_at}`}>
          {new Date(slot.starts_at).toLocaleString([], {dateStyle: "medium", timeStyle: "short"})} – {new Date(slot.ends_at).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}
          {APPOINTMENTS_BUILD && <button disabled={!enabled || locked || busy || expired} aria-pressed={selectedSlot?.starts_at === slot.starts_at}
            onClick={() => {if (!expired && Date.now() < Date.parse(value.valid_until)) {setSelectedSlot(slot); setSelectionRefreshStatus(undefined);} else setExpired(true);}}>Choose this time</button>}
        </li>)}</ul>
        {value.slots.length > count && <button disabled={locked || busy || expired} onClick={() => setCount(count + 12)}>Show more times</button>}
      </>}
    </>}
    {APPOINTMENTS_BUILD && <AppointmentPanel workspaceId={workspaceId} identity={identity} bot={bot}
      enabled={enabled} locked={locked || busy} selectedSlot={selectedSlot}
      selectionExpiresAt={expired ? "1970-01-01T00:00:00.000Z" : value?.valid_until}
      onRefreshSelectedTime={() => void read(true)} refreshingSelection={refreshingSelection}
      selectionRefreshStatus={selectionRefreshStatus} onAccessLost={onAccessLost} />}
  </section>;
}
