import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BetaSignIn, CLERK_FORGOT_PASSWORD_HASH } from "./beta-sign-in";

const signInProps: Record<string, unknown>[] = [];

vi.mock("@clerk/react", () => ({
  SignIn: (props: Record<string, unknown>) => {
    signInProps.push(props);
    return <div data-testid="clerk-sign-in-mock">Clerk sign in</div>;
  },
}));

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  signInProps.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  window.location.hash = "";
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  window.location.hash = "";
  vi.unstubAllEnvs();
});

it("mounts Clerk SignIn with signup closed and transferable signup off", async () => {
  await act(async () => root.render(<BetaSignIn />));
  expect(signInProps).toHaveLength(1);
  expect(signInProps[0]).toMatchObject({
    routing: "hash",
    withSignUp: false,
    transferable: false,
  });
  expect(host.textContent).toContain("Clerk sign in");
  expect(host.textContent).not.toMatch(/sign up|create account/i);
  expect(host.textContent).toContain("does not offer open signup");
});

it("Forgot password jumps into Clerk hash reset without opening signup", async () => {
  await act(async () => root.render(<BetaSignIn />));
  const button = host.querySelector(".beta-forgot-password") as HTMLButtonElement;
  expect(button.textContent).toBe("Forgot password?");
  await act(async () => button.click());
  expect(window.location.hash).toBe(CLERK_FORGOT_PASSWORD_HASH);
  expect(signInProps.every(props => props.withSignUp === false)).toBe(true);
});

it("renders Privacy Policy and Support under BetaSignIn when configured", async () => {
  vi.stubEnv("VITE_WORKSPACE_HOSTED_CLIENT", "web");
  vi.stubEnv("VITE_PRIVACY_POLICY_URL", "https://cosmas.ai/cosmabot/privacy");
  vi.stubEnv("VITE_SUPPORT_URL", "https://cosmas.ai/cosmabot/support");
  await act(async () => root.render(<BetaSignIn />));
  const links = [...host.querySelectorAll<HTMLAnchorElement>(".beta-sign-in .account-public-links a")];
  expect(links.map(link => link.textContent)).toEqual(["Privacy Policy", "Support"]);
  expect(links[0].href).toBe("https://cosmas.ai/cosmabot/privacy");
  expect(links[1].href).toBe("https://cosmas.ai/cosmabot/support");
  expect(host.querySelector('[data-testid="clerk-sign-in-mock"]')).toBeTruthy();
});

it("keeps Clerk SignIn and hides public links under BetaSignIn when env is unset", async () => {
  vi.stubEnv("VITE_WORKSPACE_HOSTED_CLIENT", "web");
  vi.stubEnv("VITE_PRIVACY_POLICY_URL", undefined);
  vi.stubEnv("VITE_SUPPORT_URL", undefined);
  await act(async () => root.render(<BetaSignIn />));
  expect(host.querySelectorAll(".account-public-links a")).toHaveLength(0);
  expect(host.querySelector('[data-testid="clerk-sign-in-mock"]')).toBeTruthy();
});

it("keeps Clerk SignIn and hides public links under BetaSignIn on Mac desktop", async () => {
  vi.stubEnv("VITE_WORKSPACE_HOSTED_CLIENT", "desktop");
  vi.stubEnv("VITE_PRIVACY_POLICY_URL", "https://cosmas.ai/cosmabot/privacy");
  vi.stubEnv("VITE_SUPPORT_URL", "https://cosmas.ai/cosmabot/support");
  await act(async () => root.render(<BetaSignIn />));
  expect(host.querySelectorAll(".account-public-links a")).toHaveLength(0);
  expect(host.querySelector('[data-testid="clerk-sign-in-mock"]')).toBeTruthy();
});
