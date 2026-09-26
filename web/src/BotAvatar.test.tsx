import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BotAvatar } from "./BotAvatar";
import type { BotRole } from "./workspace-api";

describe("bot motion follows real activity and accessibility preferences", () => {
  let container: HTMLDivElement, root: Root, reduced: boolean, visible: boolean;
  let preference: EventTarget;
  let intersections: Array<(visible: boolean) => void>;
  beforeEach(() => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
    vi.useFakeTimers(); reduced = false; visible = true; intersections = [];
    preference = new EventTarget();
    Object.defineProperty(preference, "matches", {configurable: true, get: () => reduced});
    vi.stubGlobal("matchMedia", () => preference);
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visible ? "visible" : "hidden");
    vi.stubGlobal("IntersectionObserver", class {
      emit: (visible: boolean) => void;
      constructor(callback: IntersectionObserverCallback) {
        this.emit = showing => callback([{isIntersecting: showing} as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
      observe() {intersections.push(this.emit); this.emit(true);}
      disconnect() {intersections = intersections.filter(emit => emit !== this.emit);}
    });
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  });
  async function show(props: {role?: BotRole; active?: boolean; greeting?: boolean; enabled?: boolean} = {}) {
    await act(async () => root.render(<BotAvatar role="scribe" {...props} />));
  }
  function motion() {return container.querySelector<HTMLImageElement>(".bot-avatar-motion");}
  async function loaded() {await act(async () => motion()!.dispatchEvent(new Event("load")));}

  it.each([['scribe','scribe'],['visit_prep','visit-prep'],['follow_up','follow-up'],['chief','chief']] as const)("uses the validated %s greeting then working clip while a request is active", async (role, file) => {
    await show({role, active: true});
    expect(motion()!.getAttribute("src")).toBe(`/bots/motion/${file}-intro.webp`);
    expect(container.querySelector(".bot-avatar-playing")).toBeNull();
    await loaded();
    expect(container.querySelector("[data-motion-phase=intro]")).not.toBeNull();
    await act(async () => vi.advanceTimersByTime(4060));
    expect(motion()!.getAttribute("src")).toBe(`/bots/motion/${file}-work.webp`);
    await loaded();
    expect(container.querySelector("[data-motion-phase=work]")).not.toBeNull();
    await show({role, active: false});
    expect(motion()).toBeNull();
    expect(container.querySelector(".bot-avatar-still img")!.getAttribute("src")).toBe(`/bots/${file}.png`);
  });

  it("does not hold a fast result or failed request until an animation finishes", async () => {
    await show({active: true}); await loaded();
    await act(async () => vi.advanceTimersByTime(30));
    await show({active: false});
    expect(motion()).toBeNull(); expect(vi.getTimerCount()).toBe(0);
  });

  it("greets once without implying continuing work and keeps decorative portraits out of announcements", async () => {
    await show({greeting: true}); await loaded();
    expect(container.querySelector(".bot-avatar")!.getAttribute("aria-hidden")).toBe("true");
    expect([...container.querySelectorAll("img")].every(img => img.alt === "")).toBe(true);
    await act(async () => vi.advanceTimersByTime(4060));
    expect(motion()).toBeNull();
    await show({greeting: false}); await show({greeting: true});
    expect(motion()).toBeNull();
  });

  it("does not request animation for idle or disabled bots, or replace custom bot identity", async () => {
    await show(); expect(motion()).toBeNull(); expect(intersections).toHaveLength(0);
    await show({active: true, enabled: false}); expect(motion()).toBeNull();
    await show({role: "research", active: true, greeting: true});
    expect(motion()).toBeNull();
    expect(container.querySelector(".bot-avatar-still img")!.getAttribute("src")).toBe("/bots/research.png");
    await show({role: "custom", active: true, greeting: true});
    expect(motion()).toBeNull(); expect(container.querySelector("svg")).not.toBeNull();
  });

  it("honors reduced motion before fetching a clip and stops immediately when the preference changes", async () => {
    reduced = true; await show({active: true}); expect(motion()).toBeNull();
    reduced = false; await act(async () => preference.dispatchEvent(new Event("change")));
    await loaded(); expect(motion()).not.toBeNull();
    reduced = true; await act(async () => preference.dispatchEvent(new Event("change")));
    expect(motion()).toBeNull(); expect(vi.getTimerCount()).toBe(0);
  });

  it("removes decoding media when its panel or app is hidden", async () => {
    await show({active: true}); await loaded();
    await act(async () => intersections.forEach(emit => emit(false)));
    expect(motion()).toBeNull(); expect(vi.getTimerCount()).toBe(0);
    await act(async () => intersections.forEach(emit => emit(true))); expect(motion()).not.toBeNull();
    visible = false; await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(motion()).toBeNull();
  });

  it("retains the existing still if animation cannot load, with initials as the final fallback", async () => {
    await show({active: true});
    await act(async () => motion()!.dispatchEvent(new Event("error")));
    expect(motion()).toBeNull(); expect(container.querySelector(".bot-avatar-still img")).not.toBeNull();
    await act(async () => container.querySelector(".bot-avatar-still img")!.dispatchEvent(new Event("error")));
    expect(container.textContent).toBe("Sc");
  });

  it("never flashes a previous bot's animation when selection changes", async () => {
    await show({active: true}); await loaded();
    await show({role: "chief", active: true});
    expect(motion()!.getAttribute("src")).toBe("/bots/motion/chief-intro.webp");
    expect(container.querySelector(".bot-avatar-playing")).toBeNull();
    await loaded(); expect(container.querySelector(".bot-avatar-playing.chief")).not.toBeNull();
  });

  it("keeps the static experience when visibility observation is unavailable", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    await show({active: true, greeting: true}); expect(motion()).toBeNull();
  });
});
