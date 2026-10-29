import {useSyncExternalStore} from 'react';
import type {WorkspaceSession} from './workspace-session';

/** React observes the session; mounting a presentation does not create one. */
export function useWorkspaceSession(session:WorkspaceSession) {
  return useSyncExternalStore(session.subscribe,session.getSnapshot,session.getSnapshot);
}
