import {useCallback,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {NativePracticeConnection,desktopPracticeConnectionPort,nativePracticeConnectionAvailable,type NativePracticeConnectionPlugin} from '../../clients/capture/src/native/practice-connection-plugin';
import {validateActiveNativeWorkspace} from '../../clients/shared/native-practice-profile.mjs';
import {AppleHostedStatus} from './AppleHostedStatus';
import {EnrollmentFlow} from './EnrollmentFlow';
import {EnrollmentError,type EnrollmentConfig,type EnrollmentStatus} from './enrollment-contract';
import {stripeDestination,type EnrollmentIdentity} from './enrollment-api';
import {createNativeEnrollmentApi,nativeEnrollmentCapabilities,nativeSelectedPracticeCapabilities,nativeEnrollmentPort,parseNativeAccountState,type NativeAccountState} from './native-enrollment';
import {parseNativeToken} from './native-auth';
import {NativeReadyPractices} from './NativeReadyPractices';

/** Mounted only by an explicit native practice connection action, never an admission gate. */
export function NativeEnrollmentEntry({plugin=NativePracticeConnection,available=nativePracticeConnectionAvailable(),onReturn,readyPractices=false}:{
  plugin?:NativePracticeConnectionPlugin;available?:boolean;onReturn:()=>void;readyPractices?:boolean;
}) {
  const scope=useRef<{active:boolean;epoch:number;state:NativeAccountState|null;pending:boolean;accountStarted:boolean}|null>(null);
  const [state,setState]=useState<NativeAccountState|null>(null),[config,setConfig]=useState<EnrollmentConfig|null>(null);
  const [failed,setFailed]=useState(false),[busy,setBusy]=useState(false),[supported,setSupported]=useState(false),[opening,setOpening]=useState(false);
  const readyPending=useRef(false),[readyBusy,setReadyBusy]=useState(false),[setupRevision,setSetupRevision]=useState<string|null>(null);
  const [selectedAvailable,setSelectedAvailable]=useState(false);
  const markReadyPending=useCallback((pending:boolean)=>{readyPending.current=pending;setReadyBusy(pending);},[]);
  const port=useMemo(()=>nativeEnrollmentPort(plugin),[plugin]);
  // Contract Origin: Mac desktop host vs iPhone Capacitor WebView.
  const expectedOrigin=desktopPracticeConnectionPort(plugin)?'app://cosmas':'capacitor://localhost';
  const api=useMemo(()=>port?createNativeEnrollmentApi(port,()=>scope.current?.state??null,()=>scope.current?.active===true,expectedOrigin):null,[port,expectedOrigin]);
  useLayoutEffect(()=>{
    const owner={active:true,epoch:0,state:null as NativeAccountState|null,pending:false,accountStarted:false};scope.current=owner;
    setState(null);setConfig(null);setFailed(false);setSupported(false);setSelectedAvailable(false);
    let remove:(()=>Promise<void>)|undefined;
    const accept=(value:unknown)=>{
      if(!owner.active)return;
      try{const next=parseNativeAccountState(value);
        if(owner.state?.revision===next.revision&&JSON.stringify(owner.state)!==JSON.stringify(next))throw new Error();
        owner.epoch++;owner.state=next;setState(next);setFailed(false);
      }catch{owner.epoch++;owner.state=null;setState(null);setFailed(true);}
    };
    if(available&&port&&api){
      void (async()=>{
        const capabilities=await plugin.capabilities();if(!owner.active)return;
        if(!nativeEnrollmentCapabilities(capabilities)){setFailed(true);return;}
        const handle=await plugin.addListener('accountStateChanged',accept);
        if(!owner.active){await handle.remove();return;}remove=()=>handle.remove();
        const epoch=owner.epoch,value=await plugin.accountStatus();if(!owner.active)return;
        if(owner.epoch===epoch)accept(value);
        if(!owner.state)throw new Error();
        const configuration=await api.config();if(!owner.active)return;
        // Synthetic staging or qualified production enrollment; the contract already requires
        // production to be qualified and to use the production Clerk key.
        if(!configuration.enabled||!configuration.auth_configured||!['synthetic','production'].includes(configuration.data_mode))throw new Error();
        let selected=false;
        if(typeof plugin.selectedPracticeCapabilities==='function'&&typeof plugin.activateSelectedPractice==='function'){
          try{selected=nativeSelectedPracticeCapabilities(await plugin.selectedPracticeCapabilities());}catch{/* Older owned hosts retain current-practice discovery. */}
        }
        if(!owner.active)return;setSelectedAvailable(selected);setConfig(configuration);setSupported(true);
      })().catch(()=>{if(owner.active)setFailed(true);});
    }else setFailed(true);
    return()=>{owner.active=false;owner.epoch++;owner.state=null;void remove?.().catch(()=>{});};
  },[plugin,available,port,api]);
  const identity=useMemo<EnrollmentIdentity|null>(()=>{
    const expected=state,owner=scope.current;if(expected?.phase!=='accountReady'||!expected.identity||!owner)return null;
    const isCurrent=()=>owner.active&&!owner.pending&&scope.current===owner&&owner.state?.phase==='accountReady'&&
      owner.state.revision===expected.revision&&owner.state.identity?.userId===expected.identity!.userId&&owner.state.identity?.sessionId===expected.identity!.sessionId;
    return {isCurrent,getToken:async()=>{if(!isCurrent())throw new EnrollmentError(401);
      const result=await plugin.accountToken({expectedRevision:expected.revision});if(!isCurrent())throw new EnrollmentError(401);
      return parseNativeToken(result,expected.revision);}};
  },[state,plugin]);
  async function signIn(){
    const owner=scope.current;if(!owner?.active||owner.pending||!supported)return;
    owner.pending=true;owner.accountStarted=true;owner.epoch++;const epoch=owner.epoch;owner.state=null;setState(null);setBusy(true);setFailed(false);
    try{const next=parseNativeAccountState(await plugin.beginAccountSignIn());if(owner.active&&owner.epoch===epoch){owner.epoch++;owner.state=next;setState(next);}}
    catch{if(owner.active&&owner.epoch===epoch)setFailed(true);}
    finally{owner.pending=false;if(owner.active)setBusy(false);}
  }
  async function returnToBeta(){
    const owner=scope.current;if(!owner?.active||owner.pending||readyPending.current)return;
    owner.pending=true;setBusy(true);
    try{if(!owner.state&&owner.accountStarted){
        // A failed/cancelled native sign-in may already have changed the SDK
        // realm. Obtain its current revision before an explicit Beta restore.
        const current=parseNativeAccountState(await plugin.accountStatus());if(!owner.active)throw new EnrollmentError(401);owner.state=current;
      }
      if(owner.state)await plugin.returnToBeta({expectedRevision:owner.state.revision});
      if(owner.active){owner.active=false;owner.state=null;onReturn();}}
    catch{if(owner.active){setFailed(true);setBusy(false);owner.pending=false;}}
  }
  const controls=<button className="button secondary" disabled={busy||readyBusy} onClick={()=>void returnToBeta()}>
    {readyPractices?'Return to original beta workspace':'Return to existing workspace'}</button>;
  if(opening)return <AppleHostedStatus role="status" title="Opening your practice" detail="The native app is verifying and opening this practice’s private workspace."/>;
  if(busy)return <AppleHostedStatus role="status" title="Updating your practice account" detail="Complete or cancel the secure sign-in window to continue."/>;
  if(failed||!available||!port)return <AppleHostedStatus title="Practice connection is not available yet"
    detail="This build cannot complete native practice setup. Your existing workspace remains available.">{controls}</AppleHostedStatus>;
  if(!supported||!config||!state)return <AppleHostedStatus role="status" title="Checking practice connection" detail="We are checking the native account service before starting setup.">{controls}</AppleHostedStatus>;
  if(state.phase!=='accountReady'||!identity)return <AppleHostedStatus role="status" title={readyPractices?'Your practices':'Connect a practice'}
    detail={readyPractices?'Sign in to see your ready practices. Your existing workspace stays separate.':'Sign in or create an account for your practice. Your existing beta workspace stays separate.'}>
    <button className="button" onClick={()=>void signIn()}>{readyPractices?'Sign in to practices':'Sign in or create account'}</button>{controls}</AppleHostedStatus>;
  const expected=state;
  async function prepareWorkspaceToken(_status:EnrollmentStatus,signal:AbortSignal){
    if(!identity?.isCurrent()||signal.aborted)throw new EnrollmentError(401);
    const result=await plugin.activatePracticeOrganization({expectedRevision:expected.revision});
    if(!identity.isCurrent()||signal.aborted)throw new EnrollmentError(401);
    return parseNativeToken(result,expected.revision);
  }
  async function openNativeWorkspace(){
    if(!identity?.isCurrent())throw new EnrollmentError(401);
    // The native driver creates the nonce, fetches the fixed registry endpoint,
    // verifies current membership/Box/API and replaces the renderer itself.
    const result=validateActiveNativeWorkspace(await plugin.activateRegisteredPractice({expectedRevision:expected.revision}));
    if(result.profile.session.subject!==expected.identity!.userId||result.profile.session.session_id!==expected.identity!.sessionId)throw new EnrollmentError(401);
    setOpening(true);
  }
  async function openSelectedPractice(status:EnrollmentStatus){
    if(!identity?.isCurrent()||!selectedAvailable||!plugin.activateSelectedPractice||!status.practice||status.stage!=='ready')throw new EnrollmentError(401);
    const result=validateActiveNativeWorkspace(await plugin.activateSelectedPractice({expectedRevision:expected.revision,
      expectedPracticeId:status.practice.id,expectedRegistryRevision:status.revision}));
    if(result.profile.session.subject!==expected.identity!.userId||result.profile.session.session_id!==expected.identity!.sessionId||
      result.profile.practice.practice_id!==status.practice.id||result.profile.practice.box_id!==status.workspace.box_id||
      result.profile.nativeIdentity.organizationId!==status.workspace.organization_id)throw new EnrollmentError(401);
    setOpening(true);
  }
  function navigate(url:string){
    const destination=url.startsWith('https://billing.stripe.com/')?'portal':'checkout';stripeDestination(url,destination==='portal');
    // Native uses its last reviewed Checkout/Portal response, never this URL.
    void port!.openEnrollmentDestination({expectedRevision:expected.revision,destination}).catch(()=>setFailed(true));
  }
  if(readyPractices&&setupRevision!==state.revision)return <NativeReadyPractices key={state.revision} api={api!} identity={identity}
    onOpenCurrent={openNativeWorkspace} onOpenSelected={selectedAvailable?openSelectedPractice:undefined}
    onCreatePractice={()=>setSetupRevision(state.revision)} onPendingChange={markReadyPending} accountControls={controls}/>;
  return <EnrollmentFlow key={state.revision} api={api!} identity={identity} config={config} accountControls={controls}
    initialName={state.identity!.displayName} initialEmail={state.identity!.email} search="" navigate={navigate}
    brand={<span className="enrollment-brand">CosmaBot</span>} invitationOrigin={config?.data_mode==='production'?'https://app.cosmas.ai':'https://onboarding.staging.cosmas.ai'}
    prepareWorkspaceToken={prepareWorkspaceToken} openNativeWorkspace={openNativeWorkspace}/>;
}
