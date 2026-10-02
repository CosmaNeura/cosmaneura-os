import { useEffect, useState } from "react";
import { parseInputSignal, presentInputSignal } from "../../clients/capture/src/native/ios-input-signal";
import type { NativeRecorderSnapshot } from "../../clients/capture/src/native/owned-recorder";
import "./capture-input-signal.css";

/** Advisory display only. Its clock ages retained observations without requesting native work. */
export function CaptureInputSignal({ native, recording }: {
  native: NativeRecorderSnapshot["native"]; recording: boolean;
}) {
  const active = recording && native.phase === "recording";
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(timer);
  }, [active]);
  if (!active) return null;

  let signal: ReturnType<typeof parseInputSignal> = null;
  try { signal = parseInputSignal(native.signal); } catch { /* Never show unvalidated native details. */ }
  const current = Math.max(now, performance.now()), observed = native.signalObservedAtMs;
  const age = typeof observed === "number" && Number.isFinite(observed) && observed >= 0 && observed <= current
    ? current - observed : Infinity;
  const view = presentInputSignal(signal, age);
  return <div className="capture-input-signal" role="group" aria-label="Microphone input">
    <span className="capture-input-route">{view.route}</span>
    <meter min={0} max={1} value={view.level} aria-label="Microphone activity" aria-valuetext={view.message} />
    <span role="status">{view.message}</span>
  </div>;
}
