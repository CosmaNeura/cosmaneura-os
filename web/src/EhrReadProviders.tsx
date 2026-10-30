import {useCallback,useEffect,useRef,useState} from 'react';
import {EhrReadMount,type EhrReadMountProps} from './EhrReadMount';
import type {EhrProvider} from './ehr-read-api';
import {TebraMedicationMount} from './TebraMedicationMount';
import {AthenaAllergyMount} from './AthenaAllergyMount';
import {AthenaMedicationMount} from './AthenaMedicationMount';
export type RecordsProvider=EhrProvider|'athena';
export type RecordsProviderRequest={provider:RecordsProvider;intent:object};

function SegmentedChoice<T extends string>({label,value,options,disabled,onChange}:{label:string;value:T;options:{id:T;name:string}[];disabled:boolean;onChange:(next:T)=>void}){
 return <div className="ehr-provider-choice" role="group" aria-label={label}>
  <span className="ehr-provider-choice-label">{label}</span>
  <div className="ehr-provider-tabs">
   {options.map(option=><button key={option.id} type="button" aria-pressed={value===option.id} disabled={disabled} onClick={()=>{if(!disabled&&value!==option.id)onChange(option.id);}}>{option.name}</button>)}
  </div>
 </div>;
}

/** Each provider keeps its own mounted journal; only explicit actions contact it. */
export function EhrReadProviders({requestedProvider,...props}:Omit<EhrReadMountProps,'provider'>&{requestedProvider?:RecordsProviderRequest}){
 const initialProvider=props.active!==false&&!props.locked&&!props.recoveryLocked&&requestedProvider&&['elation','tebra','athena'].includes(requestedProvider.provider)?requestedProvider.provider:'elation';
 const [provider,setProvider]=useState<RecordsProvider>(initialProvider),[visited,setVisited]=useState<RecordsProvider[]>([initialProvider]);
 const busy=useRef({elation:false,tebra:false,athena:false}),[dispatching,setDispatching]=useState(false),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:RecordsProvider,value:boolean)=>{busy.current[name]=value;const next=busy.current.elation||busy.current.tebra||busy.current.athena;setDispatching(next);report.current?.(next);},[]);
 const consumedRequest=useRef<object|undefined>(undefined);
 useEffect(()=>{
  if(!requestedProvider||props.active===false||consumedRequest.current===requestedProvider.intent)return;
  consumedRequest.current=requestedProvider.intent;
  if(busy.current.elation||busy.current.tebra||busy.current.athena||props.locked||props.recoveryLocked)return;
  const next=requestedProvider.provider;if(next!=='elation'&&next!=='tebra'&&next!=='athena')return;
  setProvider(next);setVisited(old=>old.includes(next)?old:[...old,next]);
 },[requestedProvider,props.active,props.locked,props.recoveryLocked]);
 const elationBusy=useCallback((value:boolean)=>update('elation',value),[update]),tebraBusy=useCallback((value:boolean)=>update('tebra',value),[update]),athenaBusy=useCallback((value:boolean)=>update('athena',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 const locked=Boolean(dispatching||props.locked||props.recoveryLocked);
 function choose(next:RecordsProvider){
  if(busy.current.elation||busy.current.tebra||busy.current.athena||props.locked||props.recoveryLocked)return;
  setProvider(next);setVisited(old=>old.includes(next)?old:[...old,next]);
 }
 return <>
  <SegmentedChoice label="Records system" value={provider} disabled={locked} onChange={choose}
   options={[{id:'elation',name:'Elation'},{id:'tebra',name:'Tebra'},{id:'athena',name:'Athena'}]}/>
  {visited.map(name=><div key={name} hidden={provider!==name}>{name==='athena'?<AthenaRecords {...props} active={props.active!==false&&provider===name} onBusyChange={athenaBusy}/>:name==='tebra'?<TebraRecords {...props} active={props.active!==false&&provider===name} onBusyChange={tebraBusy}/>:<EhrReadMount {...props} provider={name} active={props.active!==false&&provider===name} onBusyChange={elationBusy}/>}</div>)}
 </>;
}

function TebraRecords(props:Omit<EhrReadMountProps,'provider'>){
 const [choice,setChoice]=useState<'medications'|'appointments'>('medications'),[visited,setVisited]=useState<('medications'|'appointments')[]>(['medications']),[dispatching,setDispatching]=useState(false),busy=useRef({medications:false,appointments:false}),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:'medications'|'appointments',value:boolean)=>{busy.current[name]=value;const active=busy.current.medications||busy.current.appointments;setDispatching(active);report.current?.(active);},[]);
 const medicationsBusy=useCallback((value:boolean)=>update('medications',value),[update]),appointmentsBusy=useCallback((value:boolean)=>update('appointments',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 const locked=Boolean(dispatching||props.locked||props.recoveryLocked);
 return <><SegmentedChoice label="Tebra records" value={choice} disabled={locked}
  options={[{id:'medications',name:'Medication records'},{id:'appointments',name:'Appointments'}]}
  onChange={next=>{if(busy.current.medications||busy.current.appointments||props.locked||props.recoveryLocked)return;setChoice(next);setVisited(old=>old.includes(next)?old:[...old,next]);}}/>
  {visited.map(name=><div key={name} hidden={name!==choice}>{name==='medications'?<TebraMedicationMount {...props} active={props.active!==false&&choice===name} onBusyChange={medicationsBusy}/>:<EhrReadMount {...props} provider="tebra" active={props.active!==false&&choice===name} onBusyChange={appointmentsBusy}/>}</div>)}</>;
}

function AthenaRecords(props:Omit<EhrReadMountProps,'provider'>){
 const [choice,setChoice]=useState<'allergies'|'medications'>('allergies'),[visited,setVisited]=useState<('allergies'|'medications')[]>(['allergies']),[dispatching,setDispatching]=useState(false),busy=useRef({allergies:false,medications:false}),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:'allergies'|'medications',value:boolean)=>{busy.current[name]=value;const active=busy.current.allergies||busy.current.medications;setDispatching(active);report.current?.(active);},[]);
 const allergiesBusy=useCallback((value:boolean)=>update('allergies',value),[update]),medicationsBusy=useCallback((value:boolean)=>update('medications',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 const locked=Boolean(dispatching||props.locked||props.recoveryLocked);
 return <><SegmentedChoice label="Athena records" value={choice} disabled={locked}
  options={[{id:'allergies',name:'Allergy records'},{id:'medications',name:'Medication records'}]}
  onChange={next=>{if(busy.current.allergies||busy.current.medications||props.locked||props.recoveryLocked)return;setChoice(next);setVisited(old=>old.includes(next)?old:[...old,next]);}}/>
  {visited.map(name=><div key={name} hidden={name!==choice}>{name==='allergies'?<AthenaAllergyMount {...props} active={props.active!==false&&choice===name} onBusyChange={allergiesBusy}/>:<AthenaMedicationMount {...props} active={props.active!==false&&choice===name} onBusyChange={medicationsBusy}/>}</div>)}</>;
}
