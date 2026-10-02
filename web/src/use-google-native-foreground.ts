import {useLayoutEffect, useRef, useState} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {subscribeNativeWorkspaceForeground} from './native-workspace-foreground';

// Only authentication can issue this identity-scoped hint. Ordinary scene
// suspension does not revoke the capture owner or discard private journals.
export function useGoogleNativeForeground(identity: AuthenticatedWorkspaceIdentity,
  callbacks: {suspended: () => void; resumed: () => void}) {
  const current = useRef({identity, callbacks}); current.current = {identity, callbacks};
  const foreground = useRef(true);
  const [suspendedOwner, setSuspendedOwner] = useState<AuthenticatedWorkspaceIdentity | null>(null);
  useLayoutEffect(() => {
    foreground.current = true;
    setSuspendedOwner(null);
    if (identity.mode !== 'clerk_jwt' || !identity.nativeSession) return;
    let alive = true, last: boolean | undefined;
    const observe = (active: boolean) => {
      if (!alive || current.current.identity !== identity || last === active) return;
      if (active && !identity.nativeSession!.isCurrent()) return;
      last = active;
      foreground.current = active;
      setSuspendedOwner(active ? null : identity);
      if (active) current.current.callbacks.resumed();
      else current.current.callbacks.suspended();
    };
    const remove = subscribeNativeWorkspaceForeground(identity, () => observe(true), () => observe(false));
    return () => {alive = false; remove();};
  }, [identity]);
  return {suspended: suspendedOwner === identity, foreground};
}
