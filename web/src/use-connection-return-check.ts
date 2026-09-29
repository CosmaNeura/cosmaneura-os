import {useCallback, useEffect, useRef} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

type CheckState = 'connected' | 'sign_in_required' | 'sign_in_pending' | 'completing_sign_in' | 'busy' | undefined;
type ReturnCheck = {
  owner: AuthenticatedWorkspaceIdentity;
  deadline: number | null;
  attempts: number;
  running: boolean;
  timer: ReturnType<typeof setTimeout> | null;
};

// Only observe account status after a human opens OAuth and returns. A slow
// callback may still be pending at that first observation. Never read mail,
// restart OAuth, or keep checking indefinitely or while the app is hidden.
export function useConnectionReturnCheck(
  identity: AuthenticatedWorkspaceIdentity,
  check: () => Promise<CheckState>,
  onTimeout: () => void,
) {
  const current = useRef(identity); current.current = identity;
  const callbacks = useRef({check, onTimeout}); callbacks.current = {check, onTimeout};
  const active = useRef<ReturnCheck | null>(null);
  const cancel = useCallback(() => {
    if (active.current && active.current.timer !== null) clearTimeout(active.current.timer);
    active.current = null;
  }, []);
  const begin = useCallback(() => {
    cancel();
    active.current = {owner: identity, deadline: null, attempts: 0, running: false, timer: null};
  }, [identity, cancel]);

  useEffect(() => {
    cancel();
    const poll = async () => {
      const flow = active.current;
      if (!flow || flow.owner !== current.current || flow.running || flow.timer !== null || document.visibilityState === 'hidden') return;
      flow.deadline ??= Date.now() + 30_000;
      if (flow.attempts >= 10 || Date.now() >= flow.deadline) {
        cancel(); callbacks.current.onTimeout(); return;
      }
      flow.running = true;
      flow.attempts++;
      let result: CheckState;
      try { result = await callbacks.current.check(); }
      catch { result = undefined; }
      if (active.current !== flow || flow.owner !== current.current) return;
      flow.running = false;
      if (result === 'sign_in_pending' || result === 'completing_sign_in' || result === 'busy') {
        flow.timer = setTimeout(() => { flow.timer = null; void poll(); }, 3000);
      } else cancel();
    };
    const returned = () => { void poll(); };
    window.addEventListener('focus', returned);
    document.addEventListener('visibilitychange', returned);
    return () => {
      cancel();
      window.removeEventListener('focus', returned);
      document.removeEventListener('visibilitychange', returned);
    };
  }, [identity, cancel]);
  return {begin, cancel};
}
