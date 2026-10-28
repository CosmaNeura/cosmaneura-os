import {act, createElement, useEffect, type ReactNode} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import type {AuthenticatedWorkspaceIdentity} from "./workspace-api";

type ClerkWorkspaceIdentity = Extract<AuthenticatedWorkspaceIdentity, {mode: "clerk_jwt"}>;
const target = "org_invented_target";
const harness = vi.hoisted(() => ({
  auth: {isLoaded: true, isSignedIn: true, userId: "user_invented", sessionId: "sess_invented",
    orgId: "org_invented_other" as string | null, getToken: vi.fn(async () => "invented-token")},
  user: {id: "user_invented", getOrganizationMemberships: vi.fn()},
  userLoaded: true,
  clerk: {user: {id: "user_invented"}, session: {id: "sess_invented", lastActiveOrganizationId: "org_invented_target"},
    organization: {id: "org_invented_target"}, setActive: vi.fn()},
  identities: [] as ClerkWorkspaceIdentity[],
}));
vi.mock("@clerk/react", () => ({
  useAuth: () => harness.auth,
  useUser: () => ({isLoaded: harness.userLoaded, user: harness.user}),
  useClerk: () => harness.clerk,
  OrganizationSwitcher: () => "Unrestricted organization switcher",
  UserButton: () => "Account menu",
  SignIn: () => "Sign-in form",
}));
vi.mock("./WorkspaceCompatibilityGate", () => ({WorkspaceCompatibilityGate: ({identity, children}: {
  identity: ClerkWorkspaceIdentity; children: ReactNode;
}) => {
  harness.identities.push(identity);
  useEffect(() => { void identity.getToken({skipCache: true}).then(token => {
    if (token) void fetch("https://api.example.invalid/practice-access/compatibility");
  }); }, [identity]);
  return children;
}}));
vi.mock("./PracticeAccessGate", () => ({PracticeAccessGate: ({children}: {children: (access: unknown) => ReactNode}) => children({})}));
vi.mock("./EncounterWorkspace", () => ({EncounterWorkspace: ({accountControls}: {accountControls: ReactNode}) =>
  createElement("section", null, "Admitted workspace", accountControls)}));
import {ClerkBetaApp} from "./App";

let root: Root, container: HTMLDivElement;
function response(orgId = target, name = "Invented Independent Practice") {
  return {data: [{organization: {id: orgId, name}}], total_count: 1};
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (value: unknown) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
  vi.stubEnv("VITE_WORKSPACE_FEATURE_PROFILE", "standalone-practice-v1");
  vi.stubEnv("VITE_WORKSPACE_HOSTED_ENABLED", "true");
  vi.stubEnv("VITE_WORKSPACE_ORGANIZATION_ID", target);
  harness.auth = {isLoaded: true, isSignedIn: true, userId: "user_invented", sessionId: "sess_invented",
    orgId: "org_invented_other", getToken: vi.fn(async () => "invented-token")};
  harness.user = {id: "user_invented", getOrganizationMemberships: vi.fn(async () => response())};
  harness.userLoaded = true;
  harness.clerk = {user: {id: "user_invented"}, session: {id: "sess_invented", lastActiveOrganizationId: target},
    organization: {id: target}, setActive: vi.fn(async () => {})};
  harness.identities = [];
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove();
  vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks();
});
async function render() { await act(async () => root.render(createElement(ClerkBetaApp, {workspace: true}))); }
async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find(item => item.textContent === label);
  expect(button).toBeTruthy(); expect(button!.disabled).toBe(false);
  await act(async () => button!.click());
}
function closed() {
  expect(container.textContent).not.toContain("Admitted workspace");
  expect(harness.auth.getToken).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
}

it("uses practice wording at standalone sign-in and makes no membership or workspace request", async () => {
  harness.auth.isSignedIn = false; await render();
  expect(container.textContent).toContain("CosmaBotSign in to open your practice.");
  expect(container.textContent).not.toContain("Beta Lab");
  expect(harness.user.getOrganizationMemberships).not.toHaveBeenCalled(); closed();
});

it.each([undefined, "", "org_", target + "\n", " " + target, "org_" + "x".repeat(252)])(
  "refuses malformed target configuration %j before membership or token work", async value => {
    vi.stubEnv("VITE_WORKSPACE_ORGANIZATION_ID", value); await render();
    expect(container.textContent).toContain("Your practice is not configured");
    expect(harness.user.getOrganizationMemberships).not.toHaveBeenCalled(); closed();
  });

it("shows only the exact membership and requires observed active org after explicit selection", async () => {
  await render(); closed();
  expect(container.textContent).toContain("Open Invented Independent Practice");
  expect(container.textContent).not.toContain("Unrestricted organization switcher");
  expect(harness.clerk.setActive).not.toHaveBeenCalled();
  await click("Continue to Invented Independent Practice");
  expect(harness.clerk.setActive).toHaveBeenCalledExactlyOnceWith({session: "sess_invented", organization: target});
  closed(); // A resolved SDK promise is not proof that auth changed.
  harness.auth.orgId = target; await render();
  expect(container.textContent).toContain("Admitted workspaceInvented Independent PracticeAccount menu");
  expect(harness.user.getOrganizationMemberships).toHaveBeenCalledTimes(2);
  expect(harness.auth.getToken).toHaveBeenCalledExactlyOnceWith({skipCache: true});
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("waits for fresh membership even when the target organization is already active", async () => {
  harness.auth.orgId = target;
  const pending = deferred<ReturnType<typeof response>>();
  harness.user.getOrganizationMemberships.mockReturnValue(pending.promise);
  await render(); closed();
  expect(container.textContent).toContain("Checking your practice");
  await act(async () => pending.resolve(response()));
  expect(container.textContent).toContain("Admitted workspace");
  expect(harness.clerk.setActive).not.toHaveBeenCalled();
});

it("does not substitute a different organization with the same name", async () => {
  harness.user.getOrganizationMemberships.mockResolvedValue(response("org_other", "Invented Independent Practice"));
  await render(); closed();
  expect(container.textContent).toContain("This account cannot open this practice");
  expect(harness.clerk.setActive).not.toHaveBeenCalled();
});

it("reads later membership pages without selecting or provisioning any organization", async () => {
  harness.user.getOrganizationMemberships.mockResolvedValueOnce({...response("org_other"), total_count: 2}).mockResolvedValueOnce(response());
  await render(); closed();
  expect(harness.user.getOrganizationMemberships.mock.calls).toEqual([
    [{initialPage: 1, pageSize: 100}], [{initialPage: 2, pageSize: 100}]]);
  expect(container.textContent).toContain("Open Invented Independent Practice");
  expect(harness.clerk.setActive).not.toHaveBeenCalled();
});

it("recovers a failed membership read without exposing provider error details", async () => {
  harness.user.getOrganizationMemberships.mockRejectedValueOnce(new Error("private-provider-detail"));
  await render(); closed();
  expect(container.textContent).toContain("Your practice could not be checked");
  expect(container.textContent).not.toContain("private-provider-detail");
  await click("Try again"); closed();
  expect(container.textContent).toContain("Open Invented Independent Practice");
});

it("ignores old membership completion after the signed-in user/session changes", async () => {
  const old = deferred<ReturnType<typeof response>>();
  harness.user.getOrganizationMemberships.mockReturnValueOnce(old.promise);
  await render(); closed();
  harness.auth = {...harness.auth, userId: "user_new", sessionId: "sess_new", orgId: target};
  harness.user = {id: "user_new", getOrganizationMemberships: vi.fn(async () => ({data: [], total_count: 0}))};
  harness.clerk = {...harness.clerk, user: {id: "user_new"}, session: {id: "sess_new", lastActiveOrganizationId: target}};
  await render(); await act(async () => old.resolve(response())); closed();
  expect(container.textContent).toContain("This account cannot open this practice");
});

it("ignores old target membership results and requires the new configured target", async () => {
  const old = deferred<ReturnType<typeof response>>();
  harness.user.getOrganizationMemberships.mockReturnValueOnce(old.promise).mockResolvedValueOnce(response("org_newtarget", "Invented Second Practice"));
  await render(); vi.stubEnv("VITE_WORKSPACE_ORGANIZATION_ID", "org_newtarget"); await render();
  await act(async () => old.resolve(response())); closed();
  expect(container.textContent).toContain("Open Invented Second Practice");
  expect(container.textContent).not.toContain("Open Invented Independent Practice");
});

it("ignores a late failed organization selection after sign-out", async () => {
  const pending = deferred<void>(); harness.clerk.setActive.mockReturnValue(pending.promise);
  await render(); await click("Continue to Invented Independent Practice");
  expect(container.textContent).toContain("Opening practice…");
  harness.auth.isSignedIn = false; await render();
  await act(async () => pending.reject(new Error("private-selection-detail"))); closed();
  expect(container.textContent).toContain("Sign-in form");
  expect(container.textContent).not.toContain("did not open");
});

it("retries a rejected selection without treating the rejection as admission", async () => {
  harness.clerk.setActive.mockRejectedValueOnce(new Error("private-selection-detail"));
  await render(); await click("Continue to Invented Independent Practice"); closed();
  expect(container.textContent).toContain("Your practice did not open");
  expect(container.textContent).not.toContain("private-selection-detail");
  await click("Continue to Invented Independent Practice"); closed();
  expect(harness.clerk.setActive).toHaveBeenCalledTimes(2);
});

it("closes a mounted workspace and invalidates its token getter when active organization changes", async () => {
  harness.auth.orgId = target; await render();
  const oldIdentity = harness.identities.at(-1)!;
  harness.auth.getToken.mockClear(); vi.mocked(fetch).mockClear();
  harness.auth.orgId = "org_other"; await render(); closed();
  await expect(oldIdentity.getToken({skipCache: true})).resolves.toBeNull();
  expect(harness.auth.getToken).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Open Invented Independent Practice");
});

it.each(["user", "session", "organization", "session organization"])(
  "refuses a stale workspace token when live Clerk %s changes before React rerenders", async change => {
    harness.auth.orgId = target; await render();
    const identity = harness.identities.at(-1)!;
    harness.auth.getToken.mockClear(); vi.mocked(fetch).mockClear();
    if (change === "user") harness.clerk.user.id = "user_new";
    if (change === "session") harness.clerk.session.id = "sess_new";
    if (change === "organization") harness.clerk.organization.id = "org_new";
    if (change === "session organization") harness.clerk.session.lastActiveOrganizationId = "org_new";
    await expect(identity.getToken({skipCache: true})).resolves.toBeNull();
    expect(harness.auth.getToken).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  });

it("discards an in-flight token when the live Clerk organization changes before completion", async () => {
  harness.auth.orgId = target; await render();
  const identity = harness.identities.at(-1)!;
  const pending = deferred<string>(); harness.auth.getToken.mockReturnValueOnce(pending.promise);
  const token = identity.getToken({skipCache: true});
  harness.clerk.organization.id = "org_new";
  pending.resolve("invented-new-context-token");
  await expect(token).resolves.toBeNull();
});

it("leaves the existing operational organization flow unchanged", async () => {
  vi.stubEnv("VITE_WORKSPACE_FEATURE_PROFILE", "operational-beta-v1");
  harness.auth.orgId = "org_operational"; await render();
  expect(container.textContent).toContain("Admitted workspaceUnrestricted organization switcher");
  expect(harness.user.getOrganizationMemberships).not.toHaveBeenCalled();
  expect(harness.clerk.setActive).not.toHaveBeenCalled();
});
