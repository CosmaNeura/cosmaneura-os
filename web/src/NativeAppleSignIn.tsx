import {useClerk} from '@clerk/react';
import {useEffect, useRef, useState} from 'react';
import {AppleSignIn, type AppleSignInPlugin} from '../../clients/capture/src/native/apple-sign-in-plugin';
import {APPLE_ERROR_MESSAGE, completeAppleSignIn} from './apple-sign-in';

/** A real ASAuthorizationAppleIDButton overlays this reserved WebView slot. */
export function NativeAppleSignIn({onBusy, onReset, onEnabled, plugin = AppleSignIn}: {
  onBusy: (busy: boolean) => void; onReset: () => void; onEnabled: (enabled: boolean) => void;
  plugin?: AppleSignInPlugin;
}) {
  const clerk = useClerk();
  const [enabled, setEnabled] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const slot = useRef<HTMLDivElement>(null);
  const callbacks = useRef({onBusy,onReset,onEnabled});
  callbacks.current = {onBusy,onReset,onEnabled};
  useEffect(() => {
    let active = true;
    setEnabled(false); callbacks.current.onEnabled(false);
    if (!clerk.loaded) return;
    // The native read uses the bundle's validated realm and checks this browser key.
    void plugin.environment({publishableKey: clerk.publishableKey}).then(value => {
      if (active && value.enabled === true) { setEnabled(true); callbacks.current.onEnabled(true); }
    }).catch(() => {}); // Loading/error/timeout leaves no slot or changed Clerk appearance.
    return () => { active = false; };
  }, [clerk, clerk.loaded, clerk.publishableKey, plugin]);

  useEffect(() => {
    if (!enabled || !slot.current) return;
    let active = true, busy = false;
    const id = crypto.randomUUID();
    let remove: (() => Promise<void>) | undefined;
    const position = () => {
      if (!active || !slot.current) return;
      const frame = slot.current.getBoundingClientRect();
      // CSS pixels map to WebView points at the app's fixed viewport scale.
      void plugin.mount({id, x: frame.x, y: frame.y, width: frame.width, height: frame.height}).catch(() => {
        if (active) { setMessage(APPLE_ERROR_MESSAGE); setEnabled(false); callbacks.current.onEnabled(false); }
      });
    };
    void plugin.addListener('appleTapped', value => {
      if (!active || busy || value.id !== id) return;
      busy = true; callbacks.current.onBusy(true); setMessage(null);
      void completeAppleSignIn({credential: () => plugin.credential({id}),
        client: () => {
          if (!clerk.client) throw new Error('Sign-in unavailable');
          return clerk.client;
        }, setActive: options => clerk.setActive(options), isCurrent: () => active && !clerk.session,
      }).then(result => { if (active) setMessage(result); }).catch(() => {
        if (active) setMessage(APPLE_ERROR_MESSAGE);
      }).finally(async () => {
        busy = false;
        await plugin.finish({id}).catch(() => {});
        if (active) { callbacks.current.onBusy(false); callbacks.current.onReset(); position(); }
      });
    }).then(handle => {
      if (!active) return handle.remove();
      remove = () => handle.remove(); position();
    }).catch(() => { if (active) { setEnabled(false); callbacks.current.onEnabled(false); } });
    const observer = new ResizeObserver(position);
    observer.observe(slot.current);
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    return () => {
      active = false; observer.disconnect();
      window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true);
      callbacks.current.onBusy(false);
      void remove?.(); void plugin.unmount({id});
    };
  }, [enabled, clerk, plugin]);
  return <>
    {enabled && <div ref={slot} aria-hidden="true" style={{height: 44, maxWidth: 400, marginBottom: 12}} />}
    {message && <p role="alert">{message}</p>}
  </>;
}
