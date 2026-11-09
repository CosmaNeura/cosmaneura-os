import {useEffect,useRef,useState} from 'react';
import {
  fetchCopyToEhrPackage,
  type CopyToEhrAuditMetadata,
  type CopyToEhrPackage,
} from './copy-to-ehr-api';
import {CopyToEhrStrip} from './CopyToEhrStrip';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import './copy-to-ehr.css';

export type CopyToEhrMountProps={
  /** copy_to_ehr_enabled — default false keeps live users unchanged. */
  enabled?:boolean;
  /** Visit-level connector failure offer (track D). Never silent. */
  fallbackOffer?:boolean;
  identity:AuthenticatedWorkspaceIdentity;
  draftId:string;
  /** When set, sent as ?revision= and used for stale lock. Omit until the host knows it. */
  expectedRevision?:string;
  profileId?:string;
  locked?:boolean;
  highlightedKey?:string|null;
  loadPackage?:typeof fetchCopyToEhrPackage;
  onAudit?:(meta:Omit<CopyToEhrAuditMetadata,'correlation_id'|'duration_ms'>&{duration_ms?:number})=>void;
  onDone?:()=>void;
};

/**
 * Flagged mount for reviewed notes. Renders nothing when disabled and no
 * fallback offer. Connection failures must show that the note was not sent.
 */
export function CopyToEhrMount({
  enabled=false,
  fallbackOffer=false,
  identity,
  draftId,
  expectedRevision,
  profileId='atlas_md',
  locked=false,
  highlightedKey=null,
  loadPackage=fetchCopyToEhrPackage,
  onAudit,
  onDone,
}:CopyToEhrMountProps){
  const active=enabled||fallbackOffer;
  const [pkg,setPkg]=useState<CopyToEhrPackage|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [dismissed,setDismissed]=useState(false);
  const request=useRef<AbortController|null>(null);
  const mounted=useRef(false);

  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;request.current?.abort();};},[]);

  useEffect(()=>{
    if(!active||dismissed){setPkg(null);setError('');return;}
    request.current?.abort();
    const controller=new AbortController();
    request.current=controller;
    setBusy(true);setError('');setPkg(null);
    void loadPackage(identity,draftId,profileId,expectedRevision,controller.signal)
      .then(value=>{if(mounted.current&&!controller.signal.aborted)setPkg(value);})
      .catch(cause=>{
        if(!mounted.current||controller.signal.aborted)return;
        if(cause instanceof WorkspaceApiError&&cause.status===404){setError('');setPkg(null);return;}
        if(cause instanceof WorkspaceApiError&&cause.status===409){
          setError('This draft changed. Reopen Copy to EHR on the current reviewed version.');
          return;
        }
        setError('Copy to EHR could not load. Your note is still here. Try again, or continue the visit without copying.');
      })
      .finally(()=>{if(mounted.current&&!controller.signal.aborted)setBusy(false);});
    return()=>controller.abort();
  },[active,dismissed,identity,draftId,profileId,expectedRevision,loadPackage]);

  if(!active||dismissed)return null;

  const notSent=fallbackOffer||pkg?.visit_copy_to_ehr_status==='not_sent_copy_instead';

  return <div className="copy-to-ehr-mount">
    {notSent&&!pkg&&!busy&&<p className="copy-to-ehr-not-sent" role="status">
      This note was not sent. Copy to EHR is available when the package loads, or continue the visit without copying.
    </p>}
    {busy&&<p role="status">Opening Copy to EHR…</p>}
    {error&&<p className="copy-to-ehr-lock" role="alert">{error}</p>}
    {pkg&&<CopyToEhrStrip
      pkg={pkg}
      expectedRevision={expectedRevision??pkg.draft_revision}
      locked={locked}
      connectionFailed={fallbackOffer}
      highlightedKey={highlightedKey}
      onAudit={onAudit}
      onDone={()=>{setDismissed(true);onDone?.();}}
    />}
  </div>;
}
