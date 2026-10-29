import { afterEach, describe, expect, it, vi } from "vitest";
import { buildShortSha, buildVersionLabel } from "./build-info";
import { attachBuildInfo } from "./attach-build-info";

async function flushObserver() {
  await Promise.resolve();
  await new Promise<void>(resolve => queueMicrotask(resolve));
}

describe("buildShortSha", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("keeps a seven-character lowercase git SHA", () => {
    expect(buildShortSha("B1A76CC")).toBe("b1a76cc");
    expect(buildVersionLabel("b1a76cc5f18a1393c1e6bf84cfa27e9eb9b39f08")).toBe("Build b1a76cc");
  });

  it("falls back to dev for missing or invalid values", () => {
    expect(buildShortSha("")).toBe("dev");
    expect(buildShortSha("not-a-sha")).toBe("dev");
    expect(buildShortSha("pk_test_invented")).toBe("dev");
    vi.stubEnv("VITE_BUILD_SHA", "");
    expect(buildShortSha()).toBe("dev");
    expect(buildVersionLabel()).toBe("Build dev");
  });
});

describe("attachBuildInfo", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("adds the label when Settings appears and keeps a single footer", async () => {
    const stop = attachBuildInfo(document, "Build 87ee9d1");
    expect(document.querySelector(".workspace-build-info")).toBeNull();

    const settings = document.createElement("section");
    settings.className = "settings-hub";
    document.body.append(settings);
    await flushObserver();
    expect(settings.querySelector(".workspace-build-info")?.textContent).toBe("Build 87ee9d1");

    const sidebar = document.createElement("div");
    sidebar.className = "team-sidebar-bottom";
    sidebar.append(Object.assign(document.createElement("small"), { textContent: "Invented data · private to you" }));
    document.body.append(sidebar);
    await flushObserver();
    expect(sidebar.querySelector(".workspace-build-info")?.textContent).toBe("Build 87ee9d1");

    await flushObserver();
    expect(sidebar.querySelectorAll(".workspace-build-info")).toHaveLength(1);
    expect(settings.querySelectorAll(".workspace-build-info")).toHaveLength(1);
    stop();
  });

  it("labels the signed-out shell footer", () => {
    const shell = document.createElement("main");
    shell.className = "shell";
    document.body.append(shell);
    const stop = attachBuildInfo(document, "Build abcdef0");
    expect(shell.querySelector(".workspace-build-info")?.textContent).toBe("Build abcdef0");
    stop();
    const again = attachBuildInfo(document, "Build abcdef0");
    again();
    expect(shell.querySelectorAll(".workspace-build-info")).toHaveLength(1);
  });
});
