import { useEffect, useRef, useState } from "react";
import type { BotRole } from "./workspace-api";
import "./bot-motion.css";

const portraits: Record<BotRole, { file: string; initials: string }> = {
  scribe: { file: "scribe", initials: "Sc" },
  visit_prep: { file: "visit-prep", initials: "Vp" },
  follow_up: { file: "follow-up", initials: "Fu" },
  chief: { file: "chief", initials: "Ch" },
  custom: { file: "", initials: "Cb" },
  research: { file: "research", initials: "Re" },
};

// The media itself is 4,060ms long; the supplied demo's 4,380ms timer was inaccurate.
const INTRO_MS = 4060;

// Names and request status remain in adjacent text. Animation never changes request timing,
// represents a completed action, or substitutes for the existing consent/recording indicators.
export function BotAvatar({ role, large = false, active = false, greeting = false, enabled = true }: {
  role: BotRole; large?: boolean; active?: boolean; greeting?: boolean; enabled?: boolean;
}) {
  const portrait = portraits[role];
  const src = `/bots/${portrait.file}.png`;
  const element = useRef<HTMLSpanElement>(null);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const [canMove, setCanMove] = useState(false);
  const [run, setRun] = useState<{role: BotRole; active: boolean; phase: "intro" | "work"} | null>(null);
  const [loadedMotion, setLoadedMotion] = useState<string | null>(null);
  const [failedMotion, setFailedMotion] = useState<string | null>(null);
  const greeted = useRef(new Set<BotRole>());
  // Research has a matching still portrait; request clips only for the supplied motion set.
  const requested = enabled && !!portrait.file && role !== "research" && (active || greeting);

  useEffect(() => {
    setCanMove(false);
    // Conservatively keep stills if visibility or motion preference cannot be observed.
    if (!requested || !element.current || !window.matchMedia || !window.IntersectionObserver) return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    let visible = false;
    const sync = () => setCanMove(visible && !preference.matches && document.visibilityState === "visible");
    const observer = new IntersectionObserver(entries => {
      visible = entries.some(entry => entry.isIntersecting); sync();
    });
    observer.observe(element.current);
    preference.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    return () => { observer.disconnect(); preference.removeEventListener("change", sync); document.removeEventListener("visibilitychange", sync); };
  }, [requested, role]);

  useEffect(() => {
    setLoadedMotion(null);
    if (!canMove || !requested || !active && greeted.current.has(role)) { setRun(null); return; }
    greeted.current.add(role);
    setRun({role, active, phase: "intro"});
  }, [role, active, requested, canMove]);

  const phase = requested && canMove && run?.role === role && run.active === active ? run.phase : "idle";
  const motionSource = phase === "idle" ? null : `/bots/motion/${portrait.file}-${phase}.webp`;
  const motionFailed = failedMotion === portrait.file;
  const playing = !!motionSource && loadedMotion === motionSource && !motionFailed;
  useEffect(() => {
    if (phase !== "intro" || !playing) return;
    const timer = window.setTimeout(() => {
      setLoadedMotion(null);
      setRun(current => current?.role === role && current.active === active ? active ? {...current, phase: "work"} : null : current);
    }, INTRO_MS);
    return () => window.clearTimeout(timer);
  }, [phase, playing, role, active]);

  return <span ref={element} className={`bot-avatar ${role}${large ? " large" : ""}${playing ? " bot-avatar-playing" : ""}`} aria-hidden="true" data-motion-phase={playing ? phase : "idle"}>
    {role === "custom" ? <svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="currentColor" strokeWidth="2"><rect x="10" y="14" width="28" height="24" rx="8"/><path d="M24 8v6M17 31h14"/><circle cx="18" cy="23" r="1.5"/><circle cx="30" cy="23" r="1.5"/></svg> : <>
      <span className="bot-avatar-still">{failedSource === src ? portrait.initials : <img src={src} alt="" width={384} height={384} draggable={false} onError={() => setFailedSource(src)} />}</span>
      {motionSource && !motionFailed && <img key={motionSource} className="bot-avatar-motion" src={motionSource} alt="" width={256} height={256} draggable={false}
        onLoad={() => setLoadedMotion(motionSource)} onError={() => setFailedMotion(portrait.file)} />}
    </>}
  </span>;
}
