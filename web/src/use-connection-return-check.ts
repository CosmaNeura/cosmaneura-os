import {useCallback, useLayoutEffect, useRef} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

type CheckState = 'connected' | 'sign_in_required' | 'sign_in_pending' | 'completing_sign_in' | 'busy' | undefined;
type ReturnCheck = {
  owner: AuthenticatedWorkspaceIdentity;
  deadline: number | null;
  attempts: number;
  running: boolean;
  timer: ReturnType<typeof setTimeout> | null;
  lastState: CheckState;
  epoch: number;
};

// Only observe account status after a human opens OAuth and returns. A slow
// callback may still be pending at that first observation. Never read mail,
// restart OAuth, or keep checking indefinitely or while the app is hidden.
export function useConnectionReturnCheck(
  identity: AuthenticatedWorkspaceIdentity,
  check: () => Promise<CheckState>,
  onTimeout: (lastState: CheckState) => void,
  authenticatedNative = false,
) {
  const current = useRef(identity); current.current = identity;
  const callbacks = useRef({check, onTimeout}); callbacks.current = {check, onTimeout};
  const active = useRef<ReturnCheck | null>(null);
  const paused = useRef(false);
  const pollCurrent = useRef<() => void>(() => {});
  const cancel = useCallback(() => {
    if (active.current && active.current.timer !== null) clearTimeout(active.current.timer);
    active.current = null;
  }, []);
  const begin = useCallback(() => {
    cancel();
    active.current = {owner: identity, deadline: null, attempts: 0, running: false, timer: null, lastState: undefined, epoch: 0};
  }, [identity, cancel]);
  const suspend = useCallback(() => {
    paused.current = true;
    const flow = active.current;
    if (flow) {
      flow.epoch++;
      if (flow.timer !== null) clearTimeout(flow.timer);
      flow.timer = null;
    }
  }, []);
  const resume = useCallback(() => {paused.current = false; pollCurrent.current();}, []);
  const hasActive = useCallback(() => active.current !== null, []);

  useLayoutEffect(() => {
    cancel();
    paused.current = false;
    const poll = async () => {
      const flow = active.current;
      if (!flow || flow.owner !== current.current || flow.running || flow.timer !== null || paused.current ||
        !authenticatedNative && document.visibilityState === 'hidden') return;
      flow.deadline ??= Date.now() + 30_000;
      if (flow.attempts >= 10 || Date.now() >= flow.deadline) {
        cancel(); callbacks.current.onTimeout(flow.lastState); return;
      }
      flow.running = true;
      flow.attempts++;
      const epoch = flow.epoch;
      let result: CheckState;
      try { result = await callbacks.current.check(); }
      catch { result = undefined; }
      if (active.current !== flow || flow.owner !== current.current) return;
      flow.running = false;
      if (flow.epoch !== epoch) {if (!paused.current) void poll(); return;}
      flow.lastState = result;
      if (result === 'sign_in_pending' || result === 'completing_sign_in' || result === 'busy') {
        flow.timer = setTimeout(() => { flow.timer = null; void poll(); }, 3000);
      } else cancel();
    };
    const returned = () => {if (!authenticatedNative) void poll();};
    pollCurrent.current = () => {void poll();};
    window.addEventListener('focus', returned);
    document.addEventListener('visibilitychange', returned);
    return () => {
      cancel();
      pollCurrent.current = () => {};
      window.removeEventListener('focus', returned);
      document.removeEventListener('visibilitychange', returned);
    };
  }, [identity, cancel, authenticatedNative]);
  return {begin, cancel, suspend, resume, hasActive};
}
