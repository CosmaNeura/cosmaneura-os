import { afterEach, describe, expect, it, vi } from "vitest";
import { attachNavClosePolish } from "./attach-nav-close-polish";

const {readFileSync}=await vi.importActual<{readFileSync:(path:string,encoding:"utf8")=>string}>("node:fs");
const {fileURLToPath}=await vi.importActual<{fileURLToPath:(url:string)=>string}>("node:url");

async function flushObserver() {
  await Promise.resolve();
  await new Promise<void>(resolve => queueMicrotask(resolve));
}

describe("attachNavClosePolish", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("marks Close notebook when it appears and leaves other actions alone", async () => {
    const stop = attachNavClosePolish(document);
    const bar = document.createElement("header");
    bar.className = "team-topbar";
    const close = document.createElement("button");
    close.className = "team-subtle";
    close.textContent = "Close notebook";
    const other = document.createElement("button");
    other.textContent = "Team settings";
    bar.append(close, other);
    document.body.append(bar);
    await flushObserver();

    expect(close.dataset.navClosePolish).toBe("true");
    expect(close.getAttribute("aria-label")).toBe("Close notebook");
    expect(other.dataset.navClosePolish).toBeUndefined();

    close.className = "team-subtle";
    await flushObserver();
    expect(close.dataset.navClosePolish).toBe("true");
    stop();
  });

  it("styles active nav and Close notebook to at least 44px in CSS", () => {
    const css = readFileSync(fileURLToPath(import.meta.url).replace(/[^/]+$/, "nav-close-polish.css"), "utf8");
    expect(css).toMatch(/\.team-nav-item\.active/);
    expect(css).toMatch(/aria-current="page"/);
    expect(css).toMatch(/data-nav-close-polish="true"[^}]*min-height:\s*44px/);
    expect(css).toMatch(/box-shadow:\s*inset 0 -3px 0/);
  });

  it("ignores Open execution proof and other topbar actions", () => {
    const proof = document.createElement("button");
    proof.textContent = "Open execution proof";
    document.body.append(proof);
    const stop = attachNavClosePolish(document);
    expect(proof.dataset.navClosePolish).toBeUndefined();
    stop();
  });
});
