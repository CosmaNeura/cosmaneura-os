import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { EnrollmentError, BAA, ENROLLMENT_CONTACT, type EnrollmentConfig, type EnrollmentDocument, type EnrollmentInvitation,
  type EnrollmentPractices,type EnrollmentReceipt, type EnrollmentStage, type EnrollmentStatus, type PracticeInput } from './enrollment-contract';
import { stripeDestination, workspaceDestination, type EnrollmentApi, type EnrollmentIdentity } from './enrollment-api';
import { dollars, EnrollmentPricing, initialSeatSelection, selectionForSeats, type SeatSelection } from './EnrollmentPricing';
import './enrollment.css';

type PracticeDraft = { legal_name:string;display_name:string;address_line1:string;address_line2:string;city:string;
  region:string;postal_code:string;administrative_email:string };
type Operation = { key:string;revision:number;replayable?:boolean;run:(key:string,signal:AbortSignal)=>Promise<OperationResult> };
type OperationResult = { enrollment:EnrollmentStatus;available?:EnrollmentPractices;url?:string|null;invitation?:EnrollmentInvitation;invitationPurpose?:'team'|'signer';joined?:boolean };
type Errors = Record<string,string>;
const emptyPractice:PracticeDraft = {legal_name:'',display_name:'',address_line1:'',address_line2:'',city:'',region:'',postal_code:'',administrative_email:''};
const steps = ['Account','Practice','Agreement','Trial','Chief'];
function stageIndex(stage:EnrollmentStage) { return stage==='account'?0:stage==='practice'?1:stage==='agreement'?2:stage==='ready'?4:3; }
const formatDate = (date:string|null) => date ? new Intl.DateTimeFormat('en-US',{dateStyle:'long'}).format(new Date(date)) : 'Not started';
const validEmail = (value:string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) && value.length<=320;
function failure(error:unknown):string {
  if (error instanceof EnrollmentError) {
    if (error.code==='enrollment_signer_required') return 'An authorized representative must sign for this practice. Your progress is saved.';
    if (error.code==='enrollment_human_seat_limit') return 'Every invited person needs a purchased human seat. Your practice has no available seat; contact us to change your seat count.';
    if (error.code==='enrollment_trial_already_received') return 'This practice already received its trial. Manage the saved subscription or contact us.';
    if (error.code==='enrollment_document_changed') return 'The agreement changed. Reload the agreement and review it before accepting.';
    if (error.code==='enrollment_agreement_eligibility') return 'This agreement requires a HIPAA covered entity. Contact us for the appropriate agreement.';
    if (error.status===401 || error.status===403) return 'Your account cannot access this enrollment. Sign in again or contact the practice owner.';
    if (error.status===409) return 'Your saved setup changed. Check progress before continuing.';
    if (error.status===422) return 'Review the information and required confirmations before continuing.';
  }
  return 'The result could not be confirmed. Check saved progress before trying again.';
}
function Field({name,label,value,onChange,error,autoComplete,type='text',required=true,disabled=false}:{
  name:string;label:string;value:string;onChange:(value:string)=>void;error?:string;autoComplete?:string;type?:string;required?:boolean;disabled?:boolean;
}) { return <label className="enrollment-field" htmlFor={`enrollment-${name}`}>{label}
  <input id={`enrollment-${name}`} name={name} value={value} type={type} autoComplete={autoComplete} required={required}
    maxLength={name.includes('email')?320:name.includes('title')?120:['name','signature_name','legal_name','display_name'].includes(name)?160:200} disabled={disabled} aria-invalid={error?true:undefined}
    aria-describedby={error?`enrollment-error-${name}`:undefined} onChange={event=>onChange(event.target.value)}/>
  {error&&<span id={`enrollment-error-${name}`} className="enrollment-field-error">{error}</span>}</label>; }
function AgreementDocument({document}:{document:EnrollmentDocument}) {
  const src = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'"><meta name="referrer" content="no-referrer">${document.html}`;
  return <><p>Customer Business Associate Agreement · {document.doc_id} v{document.version}</p>
    <iframe className="enrollment-baa-frame" title="Full Customer Business Associate Agreement version 2.3" sandbox="" srcDoc={src}/>
    <p><a href={document.pdf_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Download the full agreement (PDF)</a></p></>;
}
function Receipt({value}:{value:EnrollmentReceipt}) { const r=value.receipt; return <section className="enrollment-receipt" aria-label="Agreement acceptance receipt">
  <h2>Agreement acceptance receipt</h2><dl className="enrollment-summary">
    <dt>Legal practice</dt><dd>{r.covered_entity_legal_name}</dd><dt>Signed by</dt><dd>{r.accepted_by_name}, {r.accepted_by_title}</dd>
    <dt>Verified email</dt><dd>{r.accepted_by_email}</dd><dt>Accepted</dt><dd>{formatDate(r.accepted_at)}</dd>
    <dt>Agreement</dt><dd>{r.doc_id} v{r.version}</dd><dt>Receipt</dt><dd>{r.id}</dd><dt>Authority</dt><dd>{r.authority_statement}</dd>
  </dl><a href={value.document.pdf_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Download agreement</a></section>; }

export function EnrollmentFlow({api,identity,config,accountControls,initialName='',initialEmail='',search=window.location.search,
  navigate=url=>window.location.assign(url),openWorkspace,prepareWorkspaceToken}:{
  api:EnrollmentApi;identity:EnrollmentIdentity;config:EnrollmentConfig;accountControls?:ReactNode;initialName?:string;initialEmail?:string;search?:string;
  navigate?:(url:string)=>void;openWorkspace?:(status:EnrollmentStatus,url:string)=>Promise<void>;
  prepareWorkspaceToken?:(status:EnrollmentStatus,signal:AbortSignal)=>Promise<string>;
}) {
  const [status,setStatus]=useState<EnrollmentStatus|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[errors,setErrors]=useState<Errors>({});
  const [name,setName]=useState(initialName),[title,setTitle]=useState(''),[practice,setPractice]=useState<PracticeDraft>({...emptyPractice,administrative_email:initialEmail});
  const [seats,setSeats]=useState<SeatSelection>(()=>initialSeatSelection(search)),[covered,setCovered]=useState(false);
  const [choice,setChoice]=useState<'create'|'join'>(()=>new URLSearchParams(search).has('invite')?'join':'create');
  const [inviteToken,setInviteToken]=useState(()=>new URLSearchParams(search).get('invite')?.slice(0,1024)??'');
  const [document,setDocument]=useState<EnrollmentDocument|null>(null),[receipt,setReceipt]=useState<EnrollmentReceipt|null>(null);
  const [signatureName,setSignatureName]=useState(''),[signatureTitle,setSignatureTitle]=useState(''),[accepted,setAccepted]=useState(false),[authority,setAuthority]=useState(false);
  const [needsSigner,setNeedsSigner]=useState(false),[signerEmail,setSignerEmail]=useState(''),[invitation,setInvitation]=useState<EnrollmentInvitation|null>(null);
  const [teamOpen,setTeamOpen]=useState(false),[teamEmail,setTeamEmail]=useState(''),[teamRole,setTeamRole]=useState<'admin'|'staff'>('staff'),[teamCanSign,setTeamCanSign]=useState(false);
  const [review,setReview]=useState<'account'|'practice'|null>(null),[uncertain,setUncertain]=useState(false);
  const [practices,setPractices]=useState<EnrollmentPractices|null>(null),[chosenPractice,setChosenPractice]=useState('');
  const pending=useRef<Operation|null>(null),request=useRef<AbortController|null>(null),mounted=useRef(false),currentStatus=useRef(status);currentStatus.current=status;
  const [checkedPending,setCheckedPending]=useState(false),documentRequested=useRef(false),inviteReviewed=useRef(false);
  const accept=useCallback((next:EnrollmentStatus)=>{
    const previous=currentStatus.current;
    const samePractice=(previous?.practice?.id??null)===(next.practice?.id??null);
    if (previous && samePractice && next.revision<previous.revision) return;
    if(previous&&!samePractice){setReceipt(null);setInvitation(null);setAuthority(false);setAccepted(false);setNeedsSigner(false);setTeamOpen(false);setTeamEmail('');setTeamCanSign(false);}
    currentStatus.current=next;setStatus(next);
    if(next.profile&&(!previous||!samePractice||next.revision!==previous.revision)){if(next.profile.display_name)setName(next.profile.display_name);setTitle(next.profile.title);setSignatureName(next.profile.display_name||initialName);setSignatureTitle(next.profile.title);}
    if(next.practice){const {legal_name,display_name,address_line1,address_line2,city,region,postal_code,administrative_email}=next.practice;
      setPractice({legal_name,display_name,address_line1,address_line2,city,region,postal_code,administrative_email});setSeats(selectionForSeats(next.practice.human_seats));setCovered(true);}
    if (pending.current && (!samePractice||next.revision!==pending.current.revision)) {pending.current=null;setUncertain(false);}
  },[initialName]);
  const run=useCallback(async<T,>(work:(signal:AbortSignal)=>Promise<T>,consume:(value:T)=>void)=>{
    if(request.current || !mounted.current || !identity.isCurrent()) return;
    const controller=new AbortController();request.current=controller;setBusy(true);setMessage('');
    const live=()=>mounted.current&&identity.isCurrent()&&!controller.signal.aborted;
    try{const value=await work(controller.signal);if(live())consume(value);}
    catch(error){if(live()){
      setMessage(failure(error));
      if(error instanceof EnrollmentError && error.code==='enrollment_signer_required'){setNeedsSigner(true);pending.current=null;setUncertain(false);}
      else if(error instanceof EnrollmentError && [401,403].includes(error.status)){
        setStatus(null);currentStatus.current=null;setPractice({...emptyPractice});setName('');setTitle('');setSignatureName('');setSignatureTitle('');
        setDocument(null);documentRequested.current=false;setReceipt(null);setInvitation(null);setInviteToken('');setSignerEmail('');setNeedsSigner(false);
        setCovered(false);setAuthority(false);setAccepted(false);setSeats({plan:'solo',humanSeats:1});pending.current=null;setUncertain(false);
        setTeamOpen(false);setTeamEmail('');setTeamCanSign(false);
      }else if(error instanceof EnrollmentError&&(error.status===422||['enrollment_human_seat_limit','enrollment_trial_already_received','enrollment_agreement_eligibility','enrollment_document_changed'].includes(error.code))){pending.current=null;setUncertain(false);}
      else if(pending.current){setUncertain(true);}
    }}finally{if(request.current===controller){request.current=null;if(live())setBusy(false);}}
  },[identity]);
  const check=useCallback(()=>void run(async signal=>{const next=await api.status(identity,signal);const available=await api.practices(identity,signal);if(available.active_practice_id!==(next.practice?.id??null))throw new EnrollmentError(409);return {next,available};},({next,available})=>{accept(next);setPractices(available);setChosenPractice(next.practice?.id??'');setErrors({});setCheckedPending(true);if(pending.current?.replayable===false){pending.current=null;setUncertain(false);}}),[run,api,identity,accept]);
  useEffect(()=>{
    mounted.current=true;check();
    if(new URLSearchParams(window.location.search).has('invite')){const url=new URL(window.location.href);url.searchParams.delete('invite');window.history.replaceState(null,'',url.pathname+url.search+url.hash);}
    return()=>{mounted.current=false;request.current?.abort();request.current=null;};
  },[check]);
  useEffect(()=>{if(!status?.profile?.display_name){if(!name&&initialName)setName(initialName);if(!practice.administrative_email&&initialEmail)setPractice(previous=>({...previous,administrative_email:initialEmail}));}},[initialName,initialEmail,status?.profile,name,practice.administrative_email]);
  const stage=review??status?.stage;
  useEffect(()=>{if(status&&status.stage!=='account'&&status.profile?.display_name&&inviteToken&&!inviteReviewed.current){inviteReviewed.current=true;setReview('practice');setChoice('join');}},[status,inviteToken]);
  useEffect(()=>{
    if(stage!=='agreement'||document||busy||documentRequested.current)return;
    documentRequested.current=true;
    void run(signal=>api.document(identity,signal),setDocument);
  },[stage,document,busy,run,api,identity]);

  const submit=(operation:Operation,recovery=false)=>{
    if(busy||uncertain&&!recovery)return;pending.current=operation;setCheckedPending(false);setErrors({});
    void run(async signal=>{const result=await operation.run(operation.key,signal);
      const latest=await api.status(identity,signal),available=await api.practices(identity,signal);if(available.active_practice_id!==(latest.practice?.id??null))throw new EnrollmentError(409);return {...result,enrollment:latest,available};},result=>{
      accept(result.enrollment);pending.current=null;setUncertain(false);setReview(null);
      if(result.available){setPractices(result.available);setChosenPractice(result.enrollment.practice?.id??'');}
      if(result.joined)setInviteToken('');
      if(result.invitation){setInvitation(result.invitation);setMessage(result.invitationPurpose==='team'?'The invitation is saved. Share this link with your teammate.':'Your progress is saved. Share this invitation with the authorized representative.');}
      if(result.url){try{navigate(stripeDestination(result.url));}catch(error){setMessage(failure(error));}}
    });
  };
  const mutation=(work:Operation['run'])=>{if(!status)return;submit({key:crypto.randomUUID(),revision:status.revision,run:work});};
  const retry=()=>{const original=pending.current;if(!original||original.replayable===false||busy||!checkedPending)return;setUncertain(false);submit(original,true);};
  const validate=(found:Errors)=>{setErrors(found);if(Object.keys(found).length){setMessage('Review the highlighted fields.');return false;}setMessage('');return true;};
  const updatePractice=(field:keyof PracticeDraft,value:string)=>setPractice(previous=>({...previous,[field]:value}));
  const saveProfile=(event:FormEvent)=>{event.preventDefault();if(!status)return;
    if(!validate({...((name.trim().length<2)?{name:'Enter your full name.'}:{}),...(name.trim().length>160?{name:'Use 160 characters or fewer.'}:{}),...(title.trim().length>120?{title:'Use 120 characters or fewer.'}:{})}))return;
    const body={expected_revision:status.revision,display_name:name.trim(),title:title.trim()};mutation(async(key,signal)=>({enrollment:await api.profile(identity,body,key,signal)}));};
  const savePractice=(event:FormEvent)=>{event.preventDefault();if(!status)return;
    const required:(keyof PracticeDraft)[]=['legal_name','address_line1','city','region','postal_code','administrative_email'];
    const found:Errors={};required.forEach(field=>{if(!practice[field].trim())found[field]='Enter this information.';});
    if(!validEmail(practice.administrative_email.trim()))found.administrative_email='Enter a valid administrative email.';
    if(!covered)found.covered='Confirm eligibility or contact us for the appropriate agreement.';
    if(!Number.isInteger(seats.humanSeats)||seats.humanSeats<1||seats.humanSeats>1000)found.seats='Enter 1–1,000 human users, or contact us for a larger practice.';
    if(!validate(found))return;
    const body:PracticeInput={...Object.fromEntries(Object.entries(practice).map(([key,value])=>[key,value.trim()])) as PracticeDraft,
      display_name:practice.display_name.trim()||practice.legal_name.trim(),expected_revision:status.revision,country:'US',human_seats:seats.humanSeats,covered_entity:true};
    mutation(async(key,signal)=>({enrollment:await api.practice(identity,body,key,signal)}));};
  const join=(event:FormEvent)=>{event.preventDefault();if(!status)return;if(!validate(inviteToken.trim()?{}:{invite:'Enter the invitation code from your practice owner.'}))return;
    const body={expected_revision:status.revision,token:inviteToken.trim()};mutation(async(key,signal)=>({enrollment:await api.join(identity,body,key,signal),joined:true}));};
  const sign=(event:FormEvent)=>{event.preventDefault();if(!status||!document)return;
    if(!validate({...((signatureName.trim().length<2)?{signature_name:'Enter the signer’s full name.'}:{}),...((signatureTitle.trim().length<2)?{signature_title:'Enter the signer’s title.'}:{}),
      ...(!accepted?{accepted:'Read and accept the agreement.'}:{}),...(!authority?{authority:'Confirm your authority to bind the practice.'}:{})}))return;
    const body={expected_revision:status.revision,doc_id:document.doc_id,version:document.version,sha256:document.sha256,
      signature_name:signatureName.trim(),signature_title:signatureTitle.trim(),authority_confirmed:true as const,accepted:true as const};
    mutation(async(key,signal)=>({enrollment:await api.accept(identity,body,key,signal)}));};
  const requestSigner=(event:FormEvent)=>{event.preventDefault();if(!status)return;if(!validate(validEmail(signerEmail.trim())?{}:{signer_email:'Enter the representative’s email.'}))return;
    const practiceId=status.practice?.id,body={email:signerEmail.trim(),role:'admin' as const,can_sign:true};
    mutation(async(key,signal)=>{const saved=await api.status(identity,signal);if(saved.practice?.id!==practiceId)throw new EnrollmentError(409);
      const value=await api.invitation(identity,{...body,expected_revision:saved.revision},key,signal);return {enrollment:value.enrollment,invitation:value,invitationPurpose:'signer'};});};
  const inviteTeammate=(event:FormEvent)=>{event.preventDefault();if(!status||status.practice?.role!=='owner')return;
    if(!validate(validEmail(teamEmail.trim())?{}:{team_email:'Enter your teammate’s email.'}))return;
    const practiceId=status.practice.id,body={email:teamEmail.trim(),role:teamRole,can_sign:teamRole==='admin'&&teamCanSign};
    mutation(async(key,signal)=>{const saved=await api.status(identity,signal);if(saved.practice?.id!==practiceId)throw new EnrollmentError(409);
      const value=await api.invitation(identity,{...body,expected_revision:saved.revision},key,signal);return {enrollment:value.enrollment,invitation:value,invitationPurpose:'team'};});};
  const switchPractice=()=>{if(!status||!chosenPractice||chosenPractice===status.practice?.id||!practices?.practices.some(item=>item.id===chosenPractice))return;
    const body={expected_revision:status.revision,practice_id:chosenPractice};mutation(async(key,signal)=>({enrollment:await api.selectPractice(identity,body,key,signal)}));};
  const recover=()=>{if(!status||busy)return;const practiceId=status.practice?.id??null;
    mutation(async(key,signal)=>{const saved=await api.status(identity,signal);if((saved.practice?.id??null)!==practiceId)throw new EnrollmentError(409);
      return {enrollment:await api.recover(identity,{expected_revision:saved.revision},key,signal)};});};
  const checkout=()=>{if(!status?.quote?.self_serve||!config.billing_configured)return;const body={expected_revision:status.revision};
    mutation(async(key,signal)=>{const value=await api.checkout(identity,body,key,signal);return {enrollment:value.enrollment,url:value.status==='open'?value.url:null};});};
  const showReceipt=()=>void run(signal=>api.receipt(identity,signal),setReceipt);
  const confirmWorkspace=()=>{if(!status||!prepareWorkspaceToken||busy)return;const practiceId=status.practice?.id??null;
    submit({key:crypto.randomUUID(),revision:status.revision,replayable:false,run:async(key,signal)=>{
      const saved=await api.status(identity,signal);if((saved.practice?.id??null)!==practiceId||!saved.workspace.organization_id)throw new EnrollmentError(409);
      const token=await prepareWorkspaceToken(saved,signal);if(!token||signal.aborted||!identity.isCurrent())throw new EnrollmentError(401);
      let confirmed=await api.confirmWorkspace(identity,{expected_revision:saved.revision,workspace_token:token},key,signal);
      if(confirmed.stage!=='ready'&&confirmed.action_required==='Your practice membership is prepared. Refresh your account, select the practice and confirm again.'){
        if(confirmed.practice?.id!==practiceId)throw new EnrollmentError(409);
        const scoped=await prepareWorkspaceToken(confirmed,signal);if(!scoped||signal.aborted||!identity.isCurrent())throw new EnrollmentError(401);
        confirmed=await api.confirmWorkspace(identity,{expected_revision:confirmed.revision,workspace_token:scoped},crypto.randomUUID(),signal);
      }
      return {enrollment:confirmed};
    }});};
  const portal=()=>{if(!status)return;void run(signal=>api.portal(identity,{expected_revision:status.revision},crypto.randomUUID(),signal),value=>navigate(stripeDestination(value.url,true)));};
  const chief=()=>{if(!status||status.stage!=='ready')return;void run(async()=>{
    const latest=await api.status(identity);if(latest.stage!=='ready'||!latest.workspace.url)throw new EnrollmentError(403);
    const url=workspaceDestination(latest.workspace.url,window.location.href,config.allowed_workspace_origins);if(openWorkspace)await openWorkspace(latest,url);else navigate(url);return latest;
  },accept);};
  const formDisabled=busy||uncertain;
  const ownsPractice=status?.practice?.role==='owner';
  const newTrial=status?.billing.status==='none'||status?.billing.status==='pending'&&!status.billing.trial_ends_at;
  const inviteLink=invitation?new URL('/onboarding?invite='+encodeURIComponent(invitation.token),window.location.origin).href:'';
  const errorSummary=Object.keys(errors).length>0&&<ul>{Object.entries(errors).map(([key,value])=><li key={key}><a href={`#enrollment-${key}`}>{value}</a></li>)}</ul>;
  return <main className="enrollment-page">
    <header className="enrollment-header"><a className="enrollment-brand" href="/onboarding">CosmaBot</a><nav aria-label="Account">{accountControls}</nav></header>
    {config.data_mode==='synthetic'&&<p className="enrollment-synthetic-note" role="note">Synthetic staging · Use invented account and practice information only.</p>}
    <section className="enrollment-card" aria-busy={busy}>
      <ol className="enrollment-progress" aria-label="Enrollment progress">{steps.map((step,index)=><li key={step} aria-current={status&&index===stageIndex(status.stage)?'step':undefined}>{step}</li>)}</ol>
      {status&&practices&&practices.practices.length>1&&<div className="enrollment-actions"><label className="enrollment-field">Your practices<select value={chosenPractice} disabled={busy||uncertain} onChange={event=>setChosenPractice(event.target.value)}>{practices.practices.map(practice=><option key={practice.id} value={practice.id}>{practice.display_name}</option>)}</select></label><button onClick={switchPractice} disabled={busy||uncertain||chosenPractice===status.practice?.id}>Open selected practice</button></div>}
      {message&&<div className="enrollment-error" role="alert">{message}{errorSummary}</div>}
      {uncertain&&<div className="enrollment-status" role="status"><p>Your submission may be saved. Check progress before retrying.</p>
        <div className="enrollment-actions"><button onClick={check} disabled={busy}>Check saved progress</button>{pending.current?.replayable!==false&&<button onClick={retry} disabled={busy||!pending.current||!checkedPending}>Retry the same submission</button>}</div></div>}
      {!status?<><h1>{busy?'Loading saved setup…':'Continue your setup'}</h1><p>Sign-in and saved progress are checked before any practice or payment is created.</p><button onClick={check} disabled={busy}>Check saved progress</button></>:
      stage==='account'?<><p className="enrollment-eyebrow">Your account</p><h1>Welcome to CosmaBot</h1><p>Confirm your name. Your sign-in is managed by Clerk.</p>
        <form className="enrollment-form" onSubmit={saveProfile} noValidate>
          <Field name="name" label="Your name" value={name} onChange={setName} error={errors.name} autoComplete="name" disabled={formDisabled}/>
          <Field name="title" label="Title (optional)" value={title} onChange={setTitle} error={errors.title} autoComplete="organization-title" required={false} disabled={formDisabled}/>
          <p className="enrollment-hint">Verified email: {status.profile?.email||initialEmail||'Provided by your signed-in account'}</p>
          <div className="enrollment-actions"><button className="primary" disabled={formDisabled}>Save and continue</button>{review&&<button type="button" onClick={()=>setReview(null)}>Back to saved setup</button>}</div>
        </form></>:
      stage==='practice'&&review&&status.agreement?.accepted&&choice!=='join'?<><h1>Practice details</h1><dl className="enrollment-summary"><dt>Legal practice</dt><dd>{status.practice?.legal_name}</dd><dt>Address</dt><dd>{status.practice?.address_line1}, {status.practice?.city}, {status.practice?.region} {status.practice?.postal_code}</dd><dt>Human users</dt><dd>{status.practice?.human_seats}</dd></dl><p>The accepted agreement and subscription stay bound to this practice. Changes require a separate reviewed update.</p><button onClick={()=>setReview(null)}>Back to saved setup</button></>:
      stage==='practice'?<><p className="enrollment-eyebrow">Your practice</p><h1>{choice==='join'?'Join your practice':'Set up your practice'}</h1>
        <div className="enrollment-actions"><button aria-pressed={choice==='create'} onClick={()=>setChoice('create')} disabled={formDisabled}>Create a practice</button><button aria-pressed={choice==='join'} onClick={()=>setChoice('join')} disabled={formDisabled}>Join with an invitation</button></div>
        {choice==='join'?<form className="enrollment-form" onSubmit={join} noValidate><p>Join the practice’s existing agreement and subscription. Joining does not create another trial.</p>
          <Field name="invite" label="Invitation code" value={inviteToken} onChange={setInviteToken} error={errors.invite} autoComplete="off" disabled={formDisabled}/>
          <div className="enrollment-actions"><button className="primary" disabled={formDisabled}>Join practice</button><button type="button" onClick={()=>setReview('account')} disabled={formDisabled}>Back</button></div></form>:
        <form className="enrollment-form" onSubmit={savePractice} noValidate>
          <p>Use the legal practice name and address for the agreement. Each legal practice has its own private workspace.</p>
          <Field name="legal_name" label="Legal practice name" value={practice.legal_name} onChange={v=>updatePractice('legal_name',v)} error={errors.legal_name} autoComplete="organization" disabled={formDisabled}/>
          <Field name="display_name" label="Practice display name (optional)" value={practice.display_name} onChange={v=>updatePractice('display_name',v)} required={false} disabled={formDisabled}/>
          <Field name="address_line1" label="Street address" value={practice.address_line1} onChange={v=>updatePractice('address_line1',v)} error={errors.address_line1} autoComplete="address-line1" disabled={formDisabled}/>
          <Field name="address_line2" label="Suite or address line 2 (optional)" value={practice.address_line2} onChange={v=>updatePractice('address_line2',v)} required={false} autoComplete="address-line2" disabled={formDisabled}/>
          <div className="enrollment-grid"><Field name="city" label="City" value={practice.city} onChange={v=>updatePractice('city',v)} error={errors.city} autoComplete="address-level2" disabled={formDisabled}/>
            <Field name="region" label="State" value={practice.region} onChange={v=>updatePractice('region',v)} error={errors.region} autoComplete="address-level1" disabled={formDisabled}/></div>
          <div className="enrollment-grid"><Field name="postal_code" label="ZIP code" value={practice.postal_code} onChange={v=>updatePractice('postal_code',v)} error={errors.postal_code} autoComplete="postal-code" disabled={formDisabled}/><p>Country: United States</p></div>
          <Field name="administrative_email" label="Administrative contact email" type="email" value={practice.administrative_email} onChange={v=>updatePractice('administrative_email',v)} error={errors.administrative_email} autoComplete="email" disabled={formDisabled}/>
          <EnrollmentPricing value={seats} onChange={setSeats} disabled={formDisabled} seatPolicy={config.pricing.seat_policy}/>
          <label className="enrollment-check" htmlFor="enrollment-covered"><input id="enrollment-covered" type="checkbox" checked={covered} disabled={formDisabled} onChange={e=>setCovered(e.target.checked)} aria-describedby={errors.covered?'enrollment-error-covered':undefined}/>This practice is a HIPAA covered entity.</label>
          {errors.covered&&<p id="enrollment-error-covered" className="enrollment-field-error">{errors.covered}</p>}
          <p className="enrollment-hint">If this does not describe your practice, <a href={ENROLLMENT_CONTACT}>contact us for the appropriate agreement</a>.</p>
          <div className="enrollment-actions"><button className="primary" disabled={formDisabled}>{seats.plan==='negotiated'?'Save and request negotiated pricing':'Save and continue'}</button><button type="button" onClick={()=>setReview('account')} disabled={formDisabled}>Back</button></div>
        </form>}</>:
      stage==='agreement'?<><p className="enrollment-eyebrow">Practice agreement</p><h1>Review and sign for {status.practice?.legal_name}</h1>
        <p>Cosmaneura Inc. is the business associate. This agreement covers the subscribed services; it does not connect an EHR or authorize an outside account.</p>
        {document?<AgreementDocument document={document}/>:<><p role="status">{busy?'Loading the full agreement…':'The agreement is unavailable.'}</p><button disabled={busy} onClick={()=>void run(signal=>api.document(identity,signal),setDocument)}>Reload agreement</button></>}
        {needsSigner||status.practice?.can_sign===false?<><h2>Use an authorized representative</h2><p>An authorized representative must sign for this practice. Your completed steps are saved. The practice owner can invite someone authorized to bind the practice. An invitation reserves a purchased human seat.</p>
          {ownsPractice?<form className="enrollment-form" onSubmit={requestSigner} noValidate><Field name="signer_email" label="Representative’s email" type="email" value={signerEmail} onChange={setSignerEmail} error={errors.signer_email} disabled={formDisabled}/>
            <div className="enrollment-actions"><button className="primary" disabled={formDisabled}>Create representative invitation</button><button type="button" onClick={()=>setNeedsSigner(false)} disabled={formDisabled}>Return to agreement</button></div></form>:<p>Ask the practice owner to invite the authorized representative. Delegated signing permission does not grant billing or owner access.</p>}
          {invitation&&<section className="enrollment-status"><label>Share this invitation<input className="enrollment-link-field" readOnly value={inviteLink}/></label><p>Expires {formatDate(invitation.expires_at)}. The recipient signs in with their own account.</p></section>}</>:
          <form className="enrollment-form" onSubmit={sign} noValidate><Field name="signature_name" label="Signer’s full name" value={signatureName} onChange={setSignatureName} error={errors.signature_name} autoComplete="name" disabled={formDisabled}/>
            <Field name="signature_title" label="Signer’s title" value={signatureTitle} onChange={setSignatureTitle} error={errors.signature_title} autoComplete="organization-title" disabled={formDisabled}/>
            <p>Verified signer email: {status.profile?.email}</p>
            <label className="enrollment-check" htmlFor="enrollment-authority"><input id="enrollment-authority" type="checkbox" checked={authority} disabled={formDisabled} aria-invalid={errors.authority?true:undefined} onChange={e=>setAuthority(e.target.checked)}/>I am authorized to bind {status.practice?.legal_name} to this agreement.</label>
            <label className="enrollment-check" htmlFor="enrollment-accepted"><input id="enrollment-accepted" type="checkbox" checked={accepted} disabled={formDisabled} aria-invalid={errors.accepted?true:undefined} onChange={e=>setAccepted(e.target.checked)}/>I have read and accept the full Customer Business Associate Agreement v2.3.</label>
            <div className="enrollment-actions"><button className="primary" disabled={formDisabled||!document}>Accept agreement</button><button type="button" onClick={()=>setNeedsSigner(true)} disabled={formDisabled}>I need an authorized representative</button><button type="button" onClick={()=>setReview('practice')} disabled={formDisabled}>Back</button></div>
          </form>}</>:
      <><p className="enrollment-eyebrow">{stage==='ready'?'Your practice is ready':'Your trial'}</p><h1>{stage==='ready'?'Welcome to '+status.practice?.display_name:stage==='negotiated'?'Let’s agree your practice price':stage==='activation_pending'?'Your setup is saved':stage==='finishing_setup'?'Finishing setup':stage==='canceled'?'Continue when you’re ready':stage==='payment_action_required'?'Review your payment setup':'Start your 14-day free trial'}</h1>
        {status.quote?.self_serve?<dl className="enrollment-summary"><dt>Human users</dt><dd>{status.quote.human_seats}, including the owner and staff</dd><dt>Monthly total</dt><dd>{dollars(status.quote.monthly_total_cents!)}/month (USD)</dd>
          {newTrial?<><dt>Due today</dt><dd>$0</dd><dt>Trial duration</dt><dd>14 days of usable access</dd><dt>First charge</dt><dd>{formatDate(status.billing.first_charge_at)}</dd></>:
            <><dt>Billing status</dt><dd>{status.billing.status==='trialing'?'Free trial':status.billing.status==='active'?'Active subscription':status.billing.status==='canceled'?'Canceled':'Payment review needed'}</dd>
              {status.billing.status==='trialing'&&<><dt>Trial ends</dt><dd>{formatDate(status.billing.trial_ends_at)}</dd></>}
              <dt>Invoices and payments</dt><dd>Review current invoices, payment amounts and dates in the Stripe billing portal.</dd></>}
        </dl>:<p>{status.practice?.human_seats} human users. Your negotiated recurring price must be agreed before checkout.</p>}
        {stage==='activation_pending'&&<p role="status">Your workspace is being prepared. Your trial clock has not started. We will ask for a card through Stripe when activation is available.</p>}
        {stage==='finishing_setup'&&<p role="status">We are confirming payment setup and your workspace. A checkout return alone does not confirm access. Your saved attempt will be recovered when you check.</p>}
        {stage==='negotiated'&&<p role="status">Your enrollment is saved for a negotiated quote. No unpriced subscription or trial has started. <a href="mailto:john@cosmaneura.com?subject=CosmaBot%20larger-practice%20pricing">Contact us about your practice price</a>.</p>}
        {stage==='canceled'&&<p>Your subscription is canceled. Manage your saved billing details or contact us; another trial is not created automatically.</p>}
        {stage==='payment'&&newTrial&&<><p>A card is required. Stripe handles card entry and verification. Your first subscription charge follows the confirmed 14-day trial unless you cancel before it ends.</p><p className="enrollment-hint">The hosted checkout confirms the final tax treatment and billing terms before you agree. No card details are saved in this browser.</p></>}
        {stage==='payment_action_required'&&<p>Use your saved billing account to review payment details. Check setup after completing any required payment action. Your original trial dates are preserved.</p>}
        {stage==='ready'&&<><p role="status">Your practice, agreement and subscription are confirmed. Open Chief to begin a supported practice task.</p>{status.billing.cancel_at_period_end&&<p>Cancellation is scheduled. Review its effective date in the billing portal.</p>}</>}
        {status.action_required&&<p className="enrollment-hint">An additional setup action is required. Check progress or contact your practice owner.</p>}
        <div className="enrollment-actions">
          {stage==='ready'&&<button className="primary" onClick={chief} disabled={formDisabled}>Open Chief</button>}
          {stage==='ready'&&ownsPractice&&<button onClick={()=>{setTeamOpen(value=>!value);setInvitation(null);}} disabled={formDisabled}>Invite a teammate</button>}
          {stage==='payment'&&newTrial&&ownsPractice&&status.quote?.self_serve&&<button className="primary" onClick={checkout} disabled={formDisabled||!config.billing_configured}>Continue securely with Stripe</button>}
          {stage==='finishing_setup'&&ownsPractice&&status.billing.status==='pending'&&<button className="primary" onClick={checkout} disabled={formDisabled||!config.billing_configured}>Resume secure checkout</button>}
          {stage!=='ready'&&status.workspace.organization_id&&status.agreement?.accepted&&['trialing','active'].includes(status.billing.status)&&prepareWorkspaceToken&&<button className="primary" onClick={confirmWorkspace} disabled={formDisabled}>Confirm practice account</button>}
          <button onClick={ownsPractice?recover:check} disabled={formDisabled}>{ownsPractice?'Check setup and payment':'Check saved progress'}</button>
          {status.agreement?.accepted&&<button onClick={showReceipt} disabled={formDisabled}>View agreement receipt</button>}
          {['ready','payment_action_required','canceled'].includes(stage??'')&&ownsPractice&&status.billing.status!=='none'&&<button onClick={portal} disabled={formDisabled}>Manage billing or cancel</button>}
          <button onClick={()=>setReview('practice')} disabled={formDisabled}>Review practice</button>
        </div>
        {stage==='ready'&&ownsPractice&&teamOpen&&<section className="enrollment-receipt" aria-label="Invite a teammate"><h2>Invite a teammate</h2><p>Every human needs a purchased seat, including office staff. Pending invitations reserve a seat. This joins the existing practice agreement and subscription.</p>
          <form className="enrollment-form" onSubmit={inviteTeammate} noValidate><Field name="team_email" label="Teammate’s email" type="email" value={teamEmail} onChange={setTeamEmail} error={errors.team_email} disabled={formDisabled}/>
            <label className="enrollment-field">Practice role<select value={teamRole} disabled={formDisabled} onChange={event=>{setTeamRole(event.target.value as 'admin'|'staff');if(event.target.value==='staff')setTeamCanSign(false);}}><option value="staff">Staff</option><option value="admin">Administrator</option></select></label>
            <label className="enrollment-check"><input type="checkbox" checked={teamCanSign} disabled={formDisabled||teamRole!=='admin'} onChange={event=>setTeamCanSign(event.target.checked)}/>Allow this administrator to sign practice agreements. This does not grant owner or billing access.</label>
            <button className="primary" disabled={formDisabled}>Create teammate invitation</button>
          </form>{invitation&&<label className="enrollment-field">Share invitation link<input className="enrollment-link-field" readOnly value={inviteLink}/><span className="enrollment-hint">Expires {formatDate(invitation.expires_at)}. No email was sent; share the link directly.</span></label>}
        </section>}{receipt&&<Receipt value={receipt}/>}</>}
    </section><footer className="enrollment-footer">Your sign-in, agreement and billing stay with your practice. <a href={BAA.pdf_url} target="_blank" rel="noopener noreferrer">BAA v2.3</a><a href={ENROLLMENT_CONTACT}>Contact us</a></footer>
  </main>;
}
