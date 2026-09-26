import { parseNativeAuthState, parseNativeToken, sameNativeState, type NativeAuthState } from "../../../../web/src/native-auth";
import type { WorkspaceAuthPlugin } from "./workspace-auth-plugin";

const MAX_UNSETTLED = 8, MAX_WAITERS = 32;
const unavailable = () => new Error("Native session unavailable");
type Flight = {
  epoch: number; state: NativeAuthState; waiters: number;
  result: Promise<string>; invalidated: Promise<never>; invalidate: () => void;
};

/**
 * Share only an outstanding native acquisition for the exact observed session.
 * No completed token cache, queue, retry, new timer or caller cancellation policy.
 * The native interface has no cancellation operation: abandoned acquisitions
 * retain their slot until native settlement, including after a session change.
 */
export function coalesceNativeWorkspaceAuth(native: WorkspaceAuthPlugin): WorkspaceAuthPlugin {
  let state: NativeAuthState | null = null, epoch = 0;
  const unsettled = new Set<Flight>(), active = new Map<string, Flight>(), mutations = new Set<symbol>();
  const invalidate = () => {
    epoch++; state = null;
    for (const flight of active.values()) flight.invalidate();
    active.clear();
  };
  const observe = (raw: unknown): NativeAuthState => {
    const next = parseNativeAuthState(raw);
    if (state?.revision === next.revision && !sameNativeState(state, next)) throw unavailable();
    if (!state || !sameNativeState(state, next)) { invalidate(); state = parseNativeAuthState(next); }
    return next;
  };
  const current = (flight: Flight) => epoch === flight.epoch && mutations.size === 0 &&
    state?.phase === "ready" && sameNativeState(state, flight.state);

  function acquire(expected: NativeAuthState): Flight {
    let rejectInvalidated!: (error: Error) => void;
    const invalidated = new Promise<never>((_resolve, reject) => { rejectInvalidated = reject; });
    let flight!: Flight;
    const result = Promise.resolve().then(async () => {
      if (!current(flight)) throw unavailable();
      const value = await native.getToken({ expectedRevision: expected.revision });
      if (!current(flight)) throw unavailable();
      return parseNativeToken(value, expected.revision);
    }).catch(() => { throw unavailable(); }).finally(() => {
      // Invalidation never releases a native slot early, even if nobody waits.
      unsettled.delete(flight);
      if (active.get(expected.revision) === flight) active.delete(expected.revision);
    });
    flight = { epoch, state: expected, waiters: 0, result, invalidated,
      invalidate: () => rejectInvalidated(unavailable()) };
    unsettled.add(flight); active.set(expected.revision, flight);
    // Native can reject after every renderer waiter has been invalidated.
    void result.catch(() => {}); void invalidated.catch(() => {});
    return flight;
  }

  async function mutate(kind: "signIn" | "signOut"): Promise<unknown> {
    invalidate();
    const mutation = Symbol(); mutations.add(mutation);
    try { return await native[kind](); }
    catch { invalidate(); throw unavailable(); }
    finally { mutations.delete(mutation); }
  }

  return {
    async getState() {
      const started = epoch;
      try {
        const value = await native.getState();
        if (started !== epoch) {
          const next = parseNativeAuthState(value);
          // Two initial state reads can complete together. An identical current
          // snapshot is safe; an older read cannot undo any observed transition.
          if (!state || !sameNativeState(state, next)) throw unavailable();
          return next;
        }
        return observe(value);
      } catch {
        if (started === epoch) invalidate();
        throw unavailable();
      }
    },
    signIn: () => mutate("signIn"),
    signOut: () => mutate("signOut"),
    async getToken(options) {
      if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).join(",") !== "expectedRevision" ||
          typeof options.expectedRevision !== "string" || mutations.size !== 0 || state?.phase !== "ready" ||
          options.expectedRevision !== state.revision) throw unavailable();
      const prior = active.get(state.revision);
      if (prior && prior.waiters >= MAX_WAITERS || !prior && unsettled.size >= MAX_UNSETTLED) throw unavailable();
      const flight = prior ?? acquire(state);
      flight.waiters++;
      try {
        const token = await Promise.race([flight.result, flight.invalidated]);
        if (!current(flight)) throw unavailable();
        // Separate closed response objects prevent cross-caller mutation.
        return { token, revision: flight.state.revision };
      } finally { flight.waiters--; }
    },
    async addListener(event, listener) {
      if (event !== "authStateChanged") throw unavailable();
      try {
        return await native.addListener(event, value => {
          let next: NativeAuthState | null;
          try { next = observe(value); }
          catch { invalidate(); next = null; }
          listener(next);
        });
      } catch { invalidate(); throw unavailable(); }
    },
  };
}
