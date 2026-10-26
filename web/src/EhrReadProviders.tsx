import {useCallback,useEffect,useRef,useState} from 'react';
import {EhrReadMount,type EhrReadMountProps} from './EhrReadMount';
import type {EhrProvider} from './ehr-read-api';
import {TebraMedicationMount} from './TebraMedicationMount';
import {AthenaAllergyMount} from './AthenaAllergyMount';
import {AthenaMedicationMount} from './AthenaMedicationMount';
type RecordsProvider=EhrProvider|'athena';

/** Each provider keeps its own mounted journal; only explicit actions contact it. */
export function EhrReadProviders(props:Omit<EhrReadMountProps,'provider'>){
 const [provider,setProvider]=useState<RecordsProvider>('elation'),[visited,setVisited]=useState<RecordsProvider[]>(['elation']);
 const busy=useRef({elation:false,tebra:false,athena:false}),[dispatching,setDispatching]=useState(false),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:RecordsProvider,value:boolean)=>{busy.current[name]=value;const next=busy.current.elation||busy.current.tebra||busy.current.athena;setDispatching(next);report.current?.(next);},[]);
 const elationBusy=useCallback((value:boolean)=>update('elation',value),[update]),tebraBusy=useCallback((value:boolean)=>update('tebra',value),[update]),athenaBusy=useCallback((value:boolean)=>update('athena',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 return <>
  <label className="ehr-provider-choice">Records system<select aria-label="Records system" value={provider} disabled={dispatching||props.locked||props.recoveryLocked} onChange={event=>{
   if(busy.current.elation||busy.current.tebra||busy.current.athena||props.locked||props.recoveryLocked)return;
   const next=event.target.value;if(next!=='elation'&&next!=='tebra'&&next!=='athena')return;setProvider(next);setVisited(old=>old.includes(next)?old:[...old,next]);
  }}><option value="elation">Elation</option><option value="tebra">Tebra</option><option value="athena">Athena</option></select></label>
  {visited.map(name=><div key={name} hidden={provider!==name}>{name==='athena'?<AthenaRecords {...props} active={props.active!==false&&provider===name} onBusyChange={athenaBusy}/>:name==='tebra'?<TebraRecords {...props} active={props.active!==false&&provider===name} onBusyChange={tebraBusy}/>:<EhrReadMount {...props} provider={name} active={props.active!==false&&provider===name} onBusyChange={elationBusy}/>}</div>)}
 </>;
}

function TebraRecords(props:Omit<EhrReadMountProps,'provider'>){
 const [choice,setChoice]=useState<'medications'|'appointments'>('medications'),[visited,setVisited]=useState<('medications'|'appointments')[]>(['medications']),[dispatching,setDispatching]=useState(false),busy=useRef({medications:false,appointments:false}),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:'medications'|'appointments',value:boolean)=>{busy.current[name]=value;const active=busy.current.medications||busy.current.appointments;setDispatching(active);report.current?.(active);},[]);
 const medicationsBusy=useCallback((value:boolean)=>update('medications',value),[update]),appointmentsBusy=useCallback((value:boolean)=>update('appointments',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 return <><label className="ehr-provider-choice">Tebra records<select aria-label="Tebra records" value={choice} disabled={dispatching||props.locked||props.recoveryLocked} onChange={event=>{if(busy.current.medications||busy.current.appointments||props.locked||props.recoveryLocked)return;const next=event.target.value;if(next!=='medications'&&next!=='appointments')return;setChoice(next);setVisited(old=>old.includes(next)?old:[...old,next]);}}><option value="medications">Medication records</option><option value="appointments">Appointments</option></select></label>{visited.map(name=><div key={name} hidden={name!==choice}>{name==='medications'?<TebraMedicationMount {...props} active={props.active!==false&&choice===name} onBusyChange={medicationsBusy}/>:<EhrReadMount {...props} provider="tebra" active={props.active!==false&&choice===name} onBusyChange={appointmentsBusy}/>}</div>)}</>;
}

function AthenaRecords(props:Omit<EhrReadMountProps,'provider'>){
 const [choice,setChoice]=useState<'allergies'|'medications'>('allergies'),[visited,setVisited]=useState<('allergies'|'medications')[]>(['allergies']),[dispatching,setDispatching]=useState(false),busy=useRef({allergies:false,medications:false}),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:'allergies'|'medications',value:boolean)=>{busy.current[name]=value;const active=busy.current.allergies||busy.current.medications;setDispatching(active);report.current?.(active);},[]);
 const allergiesBusy=useCallback((value:boolean)=>update('allergies',value),[update]),medicationsBusy=useCallback((value:boolean)=>update('medications',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 return <><label className="ehr-provider-choice">Athena records<select aria-label="Athena records" value={choice} disabled={dispatching||props.locked||props.recoveryLocked} onChange={event=>{if(busy.current.allergies||busy.current.medications||props.locked||props.recoveryLocked)return;const next=event.target.value;if(next!=='allergies'&&next!=='medications')return;setChoice(next);setVisited(old=>old.includes(next)?old:[...old,next]);}}><option value="allergies">Allergy records</option><option value="medications">Medication records</option></select></label>{visited.map(name=><div key={name} hidden={name!==choice}>{name==='allergies'?<AthenaAllergyMount {...props} active={props.active!==false&&choice===name} onBusyChange={allergiesBusy}/>:<AthenaMedicationMount {...props} active={props.active!==false&&choice===name} onBusyChange={medicationsBusy}/>}</div>)}</>;
}
