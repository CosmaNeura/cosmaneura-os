export type NativeAuthState = {
  phase: "disabled" | "loading" | "signedOut" | "signingIn" | "ready" | "signOutPending" | "unavailable";
  revision: string;
  identity: { userId: string; sessionId: string; organizationId: string } | null;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const phases = new Set(["disabled", "loading", "signedOut", "signingIn", "ready", "signOutPending", "unavailable"]);
function record(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== keys.length || !keys.every(key => Object.hasOwn(value, key))) {
    throw new Error("Native session unavailable");
  }
  return value as Record<string, unknown>;
}

export function parseNativeAuthState(value: unknown): NativeAuthState {
  const state = record(value, ["phase", "revision", "identity"]);
  if (typeof state.phase !== "string" || !phases.has(state.phase) ||
      typeof state.revision !== "string" || !UUID.test(state.revision)) throw new Error("Native session unavailable");
  let parsedIdentity: NativeAuthState["identity"] = null;
  if (state.phase === "ready") {
    const identity = record(state.identity, ["userId", "sessionId", "organizationId"]);
    for (const [field, prefix] of [["userId", "user_"], ["sessionId", "sess_"], ["organizationId", "org_"]]) {
      const id = identity[field];
      if (typeof id !== "string" || id.length > 255 || !id.startsWith(prefix) ||
          id.length <= prefix.length || !/^[A-Za-z0-9_]+$/.test(id)) throw new Error("Native session unavailable");
    }
    parsedIdentity = { userId: identity.userId as string, sessionId: identity.sessionId as string,
      organizationId: identity.organizationId as string };
  } else if (state.identity !== null) throw new Error("Native session unavailable");
  return { phase: state.phase as NativeAuthState["phase"], revision: state.revision, identity: parsedIdentity };
}

export function sameNativeState(left: NativeAuthState, right: NativeAuthState): boolean {
  return left.phase === right.phase && left.revision === right.revision &&
    left.identity?.userId === right.identity?.userId && left.identity?.sessionId === right.identity?.sessionId &&
    left.identity?.organizationId === right.identity?.organizationId;
}

export function parseNativeToken(value: unknown, revision: string): string {
  const response = record(value, ["token", "revision"]);
  if (response.revision !== revision || typeof response.token !== "string" || response.token.length > 8192 ||
      !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(response.token)) {
    throw new Error("Native session unavailable");
  }
  return response.token;
}
