import { ClerkProvider, SignIn, SignUp, UserButton, useAuth, useClerk, useUser } from '@clerk/react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createEnrollmentApi, enrollmentApiBase, type EnrollmentApi, type EnrollmentIdentity } from './enrollment-api';
import { EnrollmentError, type EnrollmentConfig, type EnrollmentStatus } from './enrollment-contract';
import { EnrollmentFlow } from './EnrollmentFlow';
import { prepareEnrollmentWorkspaceToken } from './enrollment-clerk';
import './enrollment.css';

export function enrollmentRouteRequested(enabled=import.meta.env.VITE_ENROLLMENT_ENABLED==='true',href=window.location.href,accountOnly=import.meta.env.VITE_ENROLLMENT_ACCOUNT_ONLY==='true'):boolean {
  try{const page=new URL(href);return enabled&&['http:','https:'].includes(page.protocol)&&
    (accountOnly&&page.pathname==='/'||['/onboarding','/enroll','/sign-in','/sign-up'].includes(page.pathname.replace(/\/$/,'')));}catch{return false;}
}
function returnPath(search:string):string {
  const input=new URLSearchParams(search),safe=new URLSearchParams();
  for(const key of ['plan','seats','source','invite']){const value=input.get(key);if(value&&value.length<1025)safe.set(key,value);}
  return '/onboarding'+(safe.size?'?'+safe.toString():'');
}
export function EnrollmentEntry({apiBase=import.meta.env.VITE_ENROLLMENT_API_BASE,publishableKey=import.meta.env.VITE_ENROLLMENT_CLERK_PUBLISHABLE_KEY}:{
  apiBase?:string;publishableKey?:string;
}) {
  const connection=useMemo(()=>{try{return {api:createEnrollmentApi(enrollmentApiBase(apiBase)),error:false};}catch{return {api:null,error:true};}},[apiBase]);
  const [config,setConfig]=useState<EnrollmentConfig|null>(null),[failed,setFailed]=useState(connection.error),[retry,setRetry]=useState(0);
  useEffect(()=>{setConfig(null);setFailed(connection.error);if(!connection.api)return;
    let live=true;const controller=new AbortController();
    void connection.api.config(controller.signal).then(value=>{
      if(!live)return;
      if(publishableKey&&value.clerk_publishable_key!==publishableKey)throw new EnrollmentError(503);
      setConfig(value);
    }).catch(()=>{if(live)setFailed(true);});return()=>{live=false;controller.abort();};
  },[connection,publishableKey,retry]);
  if(failed||!config||!config.enabled||!config.auth_configured||!config.clerk_publishable_key||!connection.api)return <main className="enrollment-page">
    <header className="enrollment-header"><a className="enrollment-brand" href="/onboarding">CosmaBot</a></header>
    <section className="enrollment-card"><h1>{!failed&&!config?'Checking account availability…':'Account setup is not available yet'}</h1>
      <p role={failed?'alert':'status'}>{!failed&&!config?'We are checking the account service before opening sign-in.':'Your account and trial have not been created. Return when account enrollment is available.'}</p>
      <button onClick={()=>setRetry(value=>value+1)}>Check availability</button></section></main>;
  return <ClerkProvider publishableKey={config.clerk_publishable_key}>
    <EnrollmentClerkAccount api={connection.api} config={config}/>
  </ClerkProvider>;
}
function EnrollmentClerkAccount({api,config}:{api:EnrollmentApi;config:EnrollmentConfig}) {
  const auth=useAuth(),{user}=useUser(),clerk=useClerk();
  const context=`${auth.userId??''}:${auth.sessionId??''}`;
  const observed=useRef({context,orgId:auth.orgId,signedIn:auth.isSignedIn});
  observed.current={context,orgId:auth.orgId,signedIn:auth.isSignedIn};
  const getter=useRef(auth.getToken);getter.current=auth.getToken;
  const active=useRef(true);useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
  const identity=useMemo<EnrollmentIdentity>(()=>({isCurrent:()=>active.current&&observed.current.context===context&&observed.current.signedIn===true,
    getToken:async options=>{if(!active.current||observed.current.context!==context)return null;
      const token=await getter.current(options);return active.current&&observed.current.context===context?token:null;}}),[context]);
  const prepareWorkspaceToken=async(status:EnrollmentStatus,signal?:AbortSignal,allowPreparation=true)=>{
    const target=status.workspace.organization_id;if(!target||!identity.isCurrent()||!user||user.id!==auth.userId)throw new EnrollmentError(403);
    return prepareEnrollmentWorkspaceToken({identity,reload:()=>user.reload(),
      memberships:page=>user.getOrganizationMemberships({initialPage:page,pageSize:100}),
      activate:organization=>clerk.setActive({organization}),activeOrganization:()=>observed.current.orgId},status,signal,allowPreparation);
  };
  const openWorkspace=async(status:EnrollmentStatus,url:string)=>{
    await prepareWorkspaceToken(status,undefined,false);
    window.location.assign(url);
  };
  if(!auth.isLoaded)return <main className="enrollment-page"><section className="enrollment-card" role="status">Checking your signed-in account…</section></main>;
  if(auth.isSignedIn!==true){const signIn=window.location.pathname.startsWith('/sign-in'),destination=returnPath(window.location.search);
    return <main className="enrollment-page"><header className="enrollment-header"><a className="enrollment-brand" href="/onboarding">CosmaBot</a><nav><a href={signIn?destination:'/sign-in'+window.location.search}>{signIn?'Create account':'Sign in'}</a></nav></header>
      {config.data_mode==='synthetic'&&<p className="enrollment-synthetic-note" role="note">Synthetic staging · Use invented information only.</p>}
      <section className="enrollment-card"><p className="enrollment-eyebrow">Account → Practice → Agreement → Trial → Chief</p><h1>{signIn?'Welcome back':'Create your CosmaBot account'}</h1>
        <p>Use Google, Microsoft, or email and password. Connecting a mailbox or calendar is a separate choice after setup.</p>
        <p>{config.activation_available?'A card is required for your 14-day free trial.':'Registration is available. Your trial starts when your workspace is ready.'} Solo is $300/month; 2–10 human users are $300 for the first user plus $100 for each additional user. 11+ users require an agreed quote.</p>
        <div className="enrollment-auth">{signIn?<SignIn routing="hash" signUpUrl={destination} forceRedirectUrl={destination}/>:<SignUp routing="hash" signInUrl={'/sign-in'+window.location.search} forceRedirectUrl={destination}/>}</div>
      </section></main>;
  }
  if(!auth.userId||!auth.sessionId||typeof auth.getToken!=='function')return <main className="enrollment-page"><section className="enrollment-card"><h1>Sign in again to continue</h1><p role="alert">Your secure account session is unavailable.</p><UserButton/></section></main>;
  return <EnrollmentFlow key={context} api={api} identity={identity} config={config} accountControls={<UserButton/>}
    initialName={user?.fullName??''} initialEmail={user?.primaryEmailAddress?.emailAddress??''} openWorkspace={openWorkspace} prepareWorkspaceToken={prepareWorkspaceToken}/>;
}
