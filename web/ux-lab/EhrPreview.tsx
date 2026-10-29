import {useEffect,useMemo,useRef,useState} from 'react';
import {EhrReadPanel} from '../src/EhrReadPanel';
import {ehrReadApi,ehrHash,ehrItemHash,type EhrReceipt} from '../src/ehr-read-api';
import {ehrBinding,ehrPractice,ehrScope,ehrVisit,ehrWindowReceipt,ehrVerifiedReceipt,ehrReviewResult} from '../src/ehr-read-fixtures.test-support';
import type {EhrReadRecovery} from '../src/ehr-read-recovery';
import type {Workspace} from '../src/workspace-api';

// This isolated layout fixture never calls the API. Signed API/SQL integration
// is exercised separately by test_ehr_read_ui_server_lab.py.
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
export function EhrPreview(){
 const saved=useRef<EhrReadRecovery|null>(null),[workspace,setWorkspace]=useState<Workspace>({id:ehrVisit.id,label:ehrVisit.label,revision:5,appointment_id:null,entries:[],work_candidates:[]}),[notice,setNotice]=useState('');
 const recovery=useMemo(()=>({authorize:async()=>{},load:async()=>saved.current,persist:async(value:EhrReadRecovery|null)=>{saved.current=structuredClone(value);}}),[]);
 useEffect(()=>{
  const original={...ehrReadApi};
  const receipts=new Map<string,EhrReceipt>();
  ehrReadApi.status=async()=>({contract_version:1,provider:'elation',mode:'synthetic',status:'ready',...ehrBinding,practice:ehrPractice});
  ehrReadApi.execute=async(_identity,body,anchor)=>{
   let result:EhrReceipt;
   if(body.action==='observe'){
    result=await ehrWindowReceipt(body);if(result.observation.kind!=='window')throw new Error('Fixture window required');
    const item=result.observation.items[0];item.starts_at=new Date(Date.parse(body.starts_at)+1800000).toISOString();item.ends_at=new Date(Date.parse(body.starts_at)+3600000).toISOString();item.sha256=await ehrItemHash(item);result.payload_sha256=await ehrHash(result.observation);
   }else{if(!anchor)throw new Error('Fixture anchor required');result=await ehrVerifiedReceipt(anchor,body);}
   receipts.set(body.idempotency_key,result);return structuredClone(result);
  };
  ehrReadApi.resolve=async(_identity,body)=>receipts.get(body.idempotency_key)??{status:'not_found',observation_id:null,observation_key:body.idempotency_key};
  ehrReadApi.inspect=async(_identity,anchor)=>structuredClone(anchor);
  ehrReadApi.review=async(_identity,_workspace,body,anchor)=>ehrReviewResult(anchor,body);
  return()=>{Object.assign(ehrReadApi,original);};
 },[]);
 return <><EhrReadPanel identity={identity} scope={ehrScope} recovery={recovery} workspace={{id:workspace.id,label:workspace.label,revision:workspace.revision}}
  currentSources={workspace.entries.filter(e=>e.kind==='ehr_read_source'&&e.ehr_source_state).map(e=>({id:e.id,state:e.ehr_source_state!}))}
  onSaved={setWorkspace} onAuthenticationLost={()=>setNotice('Fixture access changed')} onAskChief={()=>setNotice('Layout fixture: Chief draft preparation selected')}/>{notice&&<p role="status">{notice}</p>}</>;
}
