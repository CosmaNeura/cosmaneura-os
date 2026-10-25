import {useCallback,useEffect,useRef,useState} from 'react';
import {EhrReadMount,type EhrReadMountProps} from './EhrReadMount';
import type {EhrProvider} from './ehr-read-api';

/** Each provider keeps its own mounted journal; only explicit actions contact it. */
export function EhrReadProviders(props:Omit<EhrReadMountProps,'provider'>){
 const [provider,setProvider]=useState<EhrProvider>('elation'),[visited,setVisited]=useState<EhrProvider[]>(['elation']);
 const busy=useRef({elation:false,tebra:false}),[dispatching,setDispatching]=useState(false),report=useRef(props.onBusyChange);report.current=props.onBusyChange;
 const update=useCallback((name:EhrProvider,value:boolean)=>{busy.current[name]=value;const next=busy.current.elation||busy.current.tebra;setDispatching(next);report.current?.(next);},[]);
 const elationBusy=useCallback((value:boolean)=>update('elation',value),[update]),tebraBusy=useCallback((value:boolean)=>update('tebra',value),[update]);
 useEffect(()=>()=>report.current?.(false),[]);
 return <>
  <label className="ehr-provider-choice">Records system<select aria-label="Records system" value={provider} disabled={dispatching||props.locked||props.recoveryLocked} onChange={event=>{
   if(busy.current.elation||busy.current.tebra||props.locked||props.recoveryLocked)return;
   const next=event.target.value;if(next!=='elation'&&next!=='tebra')return;setProvider(next);setVisited(old=>old.includes(next)?old:[...old,next]);
  }}><option value="elation">Elation</option><option value="tebra">Tebra</option></select></label>
  {visited.map(name=><div key={name} hidden={provider!==name}><EhrReadMount {...props} provider={name} active={props.active!==false&&provider===name} onBusyChange={name==='elation'?elationBusy:tebraBusy}/></div>)}
 </>;
}
