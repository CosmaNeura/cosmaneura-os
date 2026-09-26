import { expect, it, vi } from "vitest";
import { createWorkspaceLifecycleNotifier } from "./workspace-lifecycle";

const generation = "11111111-2222-4333-8444-555555555555";
function fixture(href = "capacitor://localhost/index.html", token: unknown = generation) {
  const postMessage = vi.fn(), notify = vi.fn();
  const send = createWorkspaceLifecycleNotifier({
    location: { href } as Location,
    __cosmasWorkspaceGeneration: token,
    webkit: { messageHandlers: { cosmasWorkspaceLifecycle: { postMessage } } },
    cosmasWorkspaceLifecycle: { notify },
  });
  return { send, postMessage, notify };
}

it("sends only the current native generation and latches a failure against late ready", () => {
  const { send, postMessage, notify } = fixture();
  send("ready"); send("failed"); send("ready"); send("failed");
  expect(postMessage.mock.calls).toEqual([[{ kind: "ready", generation }], [{ kind: "failed", generation }]]);
  expect(notify).not.toHaveBeenCalled();
});

it("uses the exact desktop page and sends no native token or payload", () => {
  const { send, postMessage, notify } = fixture("app://cosmas/index.html");
  send("ready"); send("failed"); send("ready");
  expect(notify.mock.calls).toEqual([["ready"], ["failed"]]);
  expect(postMessage).not.toHaveBeenCalled();
});

it.each([
  "https://localhost/index.html", "http://127.0.0.1:8195/", "capacitor://other/index.html",
  "capacitor://localhost:88/index.html", "capacitor://user@localhost/index.html",
  "capacitor://localhost/index.html?private=1", "app://cosmas/other.html",
])("does not use a native recovery bridge from %s", href => {
  const { send, postMessage, notify } = fixture(href);
  send("ready"); send("failed");
  expect(postMessage).not.toHaveBeenCalled(); expect(notify).not.toHaveBeenCalled();
});

it.each([undefined, "", "private error", 123])("rejects an absent or malformed generation %s", token => {
  const { send, postMessage } = fixture("capacitor://localhost/index.html", token === undefined ? null : token);
  send("ready"); expect(postMessage).not.toHaveBeenCalled();
});

it("keeps failure latched if native notification itself throws", () => {
  const { send, postMessage } = fixture();
  postMessage.mockImplementation(() => { throw Error("private native detail"); });
  expect(() => send("failed")).not.toThrow(); send("ready");
  expect(postMessage).toHaveBeenCalledOnce();
});
