import {useEffect,useRef,useState} from 'react';
import {
  CLIPBOARD_CLEAR_TEXT,
  type CopyToEhrAuditMetadata,
  type CopyToEhrPackage,
  type CopyToEhrSection,
} from './copy-to-ehr-api';
import {CopyToEhrPopout} from './CopyToEhrPopout';
import './copy-to-ehr.css';

export type CopyToEhrStripProps={
  pkg:CopyToEhrPackage;
  /** Expected draft revision at open. Mismatch locks the strip. */
  expectedRevision:number;
  locked?:boolean;
  /** Visit-level connector failure: show that the note was not sent. */
  connectionFailed?:boolean;
  onDone?:()=>void;
  onAudit?:(meta:Omit<CopyToEhrAuditMetadata,'correlation_id'|'duration_ms'>&{duration_ms?:number})=>void;
  /** Optional remote highlight (track C). Section key only — never note text. */
  highlightedKey?:string|null;
};

type CopyTarget='full'|CopyToEhrSection|'clear';
type CopyState='idle'|'copying'|'copied'|'manual'|'cleared';

function targetText(target:CopyTarget,pkg:CopyToEhrPackage):string{
  if(target==='clear')return CLIPBOARD_CLEAR_TEXT;
  if(target==='full')return pkg.full_note;
  return target.text;
}

function targetLabel(target:CopyTarget):string{
  if(target==='clear')return 'clipboard clear marker';
  if(target==='full')return 'full note';
  return target.label;
}

export function CopyToEhrStrip({
  pkg,expectedRevision,locked=false,connectionFailed=false,onDone,onAudit,highlightedKey,
}:CopyToEhrStripProps){
  const stale=expectedRevision!==pkg.draft_revision;
  const expired=Date.parse(pkg.expires_at)<=Date.now();
  const disabled=locked||stale||expired;
  const [index,setIndex]=useState(0);
  const [state,setState]=useState<CopyState>('idle');
  const [manual,setManual]=useState<{label:string;text:string}|null>(null);
  const [open,setOpen]=useState(true);
  const started=useRef(Date.now());
  const textRef=useRef<HTMLTextAreaElement>(null);
  const flight=useRef(false);
  const activeKey=highlightedKey&&pkg.sections.some(section=>section.key===highlightedKey)
    ?highlightedKey
    :pkg.sections[Math.min(index,pkg.sections.length-1)]?.key;
  const active=pkg.sections.find(section=>section.key===activeKey)??pkg.sections[0];

  useEffect(()=>{
    onAudit?.({event:connectionFailed?'copy_to_ehr.fallback_shown':'copy_to_ehr.opened',profile_id:pkg.profile_id,outcome:'ok'});
  // Open once per package identity.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[pkg.draft_id,pkg.payload_hash,connectionFailed]);

  useEffect(()=>{
    if(!highlightedKey)return;
    const next=pkg.sections.findIndex(section=>section.key===highlightedKey);
    if(next>=0)setIndex(next);
  },[highlightedKey,pkg.sections]);

  async function copy(target:CopyTarget){
    if(disabled||flight.current||!open)return;
    if(stale||expired){
      onAudit?.({event:'copy_to_ehr.blocked',profile_id:pkg.profile_id,outcome:stale?'stale':'expired',duration_ms:Date.now()-started.current});
      return;
    }
    const text=targetText(target,pkg);
    flight.current=true;
    setState('copying');
    setManual(null);
    try{
      if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      if(!open)return;
      setState(target==='clear'?'cleared':'copied');
      onAudit?.({
        event:target==='clear'?'copy_to_ehr.cleared':'copy_to_ehr.copied',
        profile_id:pkg.profile_id,
        outcome:'ok',
        duration_ms:Date.now()-started.current,
      });
    }catch{
      if(!open)return;
      if(target==='clear'){
        setState('idle');
        onAudit?.({event:'copy_to_ehr.blocked',profile_id:pkg.profile_id,outcome:'denied',duration_ms:Date.now()-started.current});
      }else{
        setManual({label:targetLabel(target),text});
        setState('manual');
        onAudit?.({event:'copy_to_ehr.blocked',profile_id:pkg.profile_id,outcome:'denied',duration_ms:Date.now()-started.current});
      }
    }finally{
      flight.current=false;
      // Clear only an unresolved in-flight marker; keep copied/manual/cleared results.
      if(open)setState(current=>current==='copying'?'idle':current);
    }
  }

  function nextSection(){
    if(disabled||!open)return;
    setIndex(current=>(current+1)%pkg.sections.length);
    setState('idle');
    setManual(null);
  }

  function finish(){
    if(!open)return;
    setOpen(false);
    setManual(null);
    setState('idle');
    onAudit?.({event:'copy_to_ehr.done',profile_id:pkg.profile_id,outcome:'ok',duration_ms:Date.now()-started.current});
    onDone?.();
  }

  if(!open)return null;

  const extras=Object.entries(pkg.extras).filter(([,value])=>typeof value==='string'&&value.length>0) as [string,string][];

  return <section className="copy-to-ehr-strip" aria-label="Copy to EHR">
    <header>
      <h3>Copy to EHR</h3>
      <p className="team-fine">Copy plain text, then paste in the chart yourself. CosmaBot never types into the chart.</p>
    </header>
    {connectionFailed&&<p className="copy-to-ehr-not-sent" role="status">
      This note was not sent. Use Copy to EHR below, or continue the visit without copying.
    </p>}
    {stale&&<p className="copy-to-ehr-lock" role="alert">This draft changed. Reopen Copy to EHR on the current reviewed version. Buttons stay locked.</p>}
    {expired&&!stale&&<p className="copy-to-ehr-lock" role="alert">This copy session expired. Reopen Copy to EHR from the reviewed note.</p>}
    <p className="team-fine">Next section: <strong>{active.label}</strong> ({pkg.sections.findIndex(s=>s.key===active.key)+1} of {pkg.sections.length})</p>
    <div className="copy-to-ehr-actions">
      <button type="button" className="team-primary" disabled={disabled||state==='copying'} onClick={()=>void copy('full')}>Copy full note</button>
      <button type="button" disabled={disabled||state==='copying'} onClick={()=>void copy(active)}>Copy this section</button>
      <button type="button" disabled={disabled} onClick={nextSection}>Next highlight</button>
      <button type="button" disabled={disabled||state==='copying'} onClick={()=>void copy('clear')}>Clear clipboard</button>
      <CopyToEhrPopout disabled={disabled} sectionLabel={active.label} sectionIndex={pkg.sections.findIndex(s=>s.key===active.key)} sectionCount={pkg.sections.length}/>
      <button type="button" disabled={locked} onClick={finish}>Done</button>
    </div>
    {extras.length>0&&<div className="copy-to-ehr-extras" aria-label="Separate outputs">
      <p className="team-fine">These stay out of the full note. Copy them only when you need them.</p>
      {extras.map(([key,text])=><button key={key} type="button" disabled={disabled||state==='copying'}
        onClick={()=>void copy({key,label:key.replaceAll('_',' '),text})}>Copy {key.replaceAll('_',' ')}</button>)}
    </div>}
    {state==='copying'&&<p role="status">Copying…</p>}
    {state==='copied'&&<p role="status">Copied. Paste in the chart, then review before saving there.</p>}
    {state==='cleared'&&<p role="status">Clipboard cleared with a single space.</p>}
    {state==='manual'&&manual&&<>
      <p role="status">Clipboard copy is blocked here. Select the text below and copy it yourself.</p>
      <label>{manual.label}<textarea ref={textRef} readOnly value={manual.text} disabled={locked}/></label>
      <button type="button" disabled={locked} onClick={()=>{
        const field=textRef.current;
        if(field?.isConnected&&!field.disabled){field.focus({preventScroll:true});field.select();}
      }}>Select and copy</button>
    </>}
  </section>;
}
