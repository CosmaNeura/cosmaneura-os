import {useId, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {PrivatePdfViewer} from './PrivatePdfViewer';
import {requirePdf} from './vendor-api';
import {vendorCanonical} from './vendor-contract';
import type {Document as PdfMetadata} from './vendor-schema';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {validEFaxSourceOffer, type EFaxSourceOffer} from './efax-inbound-source-api';
import {useGoogleNativeForeground} from './use-google-native-foreground';
import './efax-original-pdf.css';

type Props = {identity: AuthenticatedWorkspaceIdentity; owner: object; contextKey: string; offered: EFaxSourceOffer;
  visible: boolean; disabled: boolean; onOpenDocument: (signal: AbortSignal) => Promise<Uint8Array | null>; onFailure: (cause: unknown) => void;
  onOperationBusyChange: (busy: boolean) => void};
type Loaded = {episode: object; bytes: Uint8Array; document: PdfMetadata};

/** Display-only bytes: no PDF object URL, persistence, source mutation or provider acquisition. */
export function EFaxOriginalPdf({identity, owner, contextKey, offered, visible, disabled, onOpenDocument, onFailure, onOperationBusyChange}: Props) {
  const documentKey = vendorCanonical(offered);
  const episode = useMemo(() => ({}), [identity, owner, contextKey, documentKey]);
  const current = useRef({episode, visible, disabled, alive: true, inactive: false});
  current.current = {...current.current, episode, visible, disabled};
  const loader = useRef(onOpenDocument); loader.current = onOpenDocument;
  const request = useRef<{episode: object; controller: AbortController} | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null), [loading, setLoading] = useState<object | null>(null);
  const [error, setError] = useState<{episode: object; text: string} | null>(null), [inactive, setInactive] = useState(false), [stopping, setStopping] = useState(false);
  const regionId = useId();
  function cancel() {request.current?.controller.abort();}
  function close() {cancel(); setLoaded(null); setLoading(request.current?.episode ?? null); setStopping(!!request.current); setError(null);}
  function suspend() {current.current.inactive = true; setInactive(true); close();}
  function resume() {current.current.inactive = document.visibilityState === 'hidden'; setInactive(current.current.inactive);}
  const foreground = useGoogleNativeForeground(identity, {suspended: suspend, resumed: resume});
  useLayoutEffect(() => {
    current.current.alive = true;
    return () => {current.current.alive = false; cancel(); request.current = null;};
  }, [episode]);
  useLayoutEffect(() => {close();}, [episode]);
  useLayoutEffect(() => {if (!visible) close();}, [visible, episode]);
  useLayoutEffect(() => {
    const visibility = () => {if (document.visibilityState === 'hidden') suspend(); else if (foreground.foreground.current) resume();};
    const show = () => {if (foreground.foreground.current) resume();};
    window.addEventListener('pagehide', suspend); window.addEventListener('pageshow', show);
    document.addEventListener('visibilitychange', visibility); visibility();
    return () => {window.removeEventListener('pagehide', suspend); window.removeEventListener('pageshow', show); document.removeEventListener('visibilitychange', visibility);};
  }, [episode]);
  const displayed = visible && !inactive && !foreground.suspended && loaded?.episode === episode ? loaded : null;
  const waiting = visible && !inactive && !foreground.suspended && loading === episode;
  async function open() {
    if (!current.current.alive || !visible || disabled || inactive || !foreground.foreground.current || request.current) return;
    const operation = {episode, controller: new AbortController()}; request.current = operation;
    const notify = onOperationBusyChange; notify(true);
    const valid = () => current.current.alive && current.current.episode === episode && current.current.visible &&
      !current.current.inactive && foreground.foreground.current && request.current === operation && !operation.controller.signal.aborted;
    setError(null); setLoading(episode); setStopping(false);
    try {
      const received = await loader.current(operation.controller.signal); if (!valid()) return;
      if (received === null) throw new WorkspaceApiError(409, 'efax_inbound_source_unavailable');
      if (!(received instanceof Uint8Array) || received.length < 5 || received.length > 1_048_576 || !validEFaxSourceOffer(offered)) throw new Error('Unavailable PDF');
      const bytes = new Uint8Array(received);
      // artifact_id is a local renderer slot only; authority comes from the exact acquired offer and loader.
      const metadata: PdfMetadata = {artifact_id: offered.operation_id, sha256: offered.document_sha256, byte_length: bytes.length, media_type: 'application/pdf'};
      await requirePdf(metadata, bytes); if (!valid()) return;
      setLoaded({episode, bytes, document: metadata});
    } catch (cause) {
      if (valid()) {onFailure(cause); setError({episode, text: 'The exact saved PDF could not be opened. Your passage is unchanged. Try opening the PDF again.'});}
    } finally {
      if (request.current === operation) {request.current = null; if (current.current.alive && current.current.episode === episode) {setLoading(null); setStopping(false);}}
      notify(false);
    }
  }
  return <div className="efax-original-pdf" hidden={!visible || inactive || foreground.suspended}>
    <button type="button" disabled={!displayed && !waiting && disabled} aria-expanded={!!displayed || waiting} aria-controls={regionId}
      onClick={() => {if (displayed || waiting) close(); else void open();}}>{displayed || waiting ? 'Close original PDF' : 'Open original PDF'}</button>
    {waiting && <p role="status">{stopping ? 'Closing the PDF… Waiting for the current request to stop.' : 'Opening the saved PDF… Your passage stays here.'}</p>}
    {error?.episode === episode && <p role="alert">{error.text}</p>}
    {displayed && <div id={regionId}>
      <p>Check the original pages alongside your passage. Page text is available only when you choose it; nothing is copied into your passage automatically.</p>
      <PrivatePdfViewer bytes={displayed.bytes} document={displayed.document} title="Original received fax PDF"/>
      <p>If a page cannot be displayed clearly, do not confirm its contents here. Close the PDF to keep working on your passage, or reopen it to try again.</p>
    </div>}
  </div>;
}
