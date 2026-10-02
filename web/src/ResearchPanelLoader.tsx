import {useEffect,useRef,useState} from 'react';
import type {ResearchWorkspace} from './ResearchWorkspace';

type ResearchPanelProps=Parameters<typeof ResearchWorkspace>[0];
export type ResearchPanelModule={ResearchWorkspace:typeof ResearchWorkspace};
export type ResearchPanelImport=()=>Promise<ResearchPanelModule>;

let panelCode:Promise<ResearchPanelModule>|null=null;
const importResearch:ResearchPanelImport=()=>{
  if(!panelCode)panelCode=import('./ResearchWorkspace').catch(error=>{
    // A transport failure can be attempted again. Browsers may retain module
    // evaluation failures; a retry is not a guarantee that a broken module opens.
    panelCode=null;throw error;
  });
  return panelCode;
};
type LoadState={identity:ResearchPanelProps['identity'];workspaceId:string;bot:string;
  phase:'loading'|'failed'|'ready';Panel?:typeof ResearchWorkspace};

/** Loads optional UI code only. Source reads, consent and custody stay in Research. */
export function ResearchPanelLoader({loadPanel=importResearch,...props}:ResearchPanelProps&{
  loadPanel?:ResearchPanelImport;
}){
  const [attempt,setAttempt]=useState(0),[state,setState]=useState<LoadState|null>(null);
  const generation=useRef(0),container=useRef<HTMLDivElement|null>(null),retryFocus=useRef<HTMLButtonElement|null>(null);
  useEffect(()=>()=>{retryFocus.current=null;},[props.identity,props.workspaceId,props.bot.address]);
  useEffect(()=>{
    const current=++generation.current,owner={identity:props.identity,workspaceId:props.workspaceId,bot:props.bot.address};
    setState({...owner,phase:'loading'});
    void Promise.resolve().then(loadPanel).then(module=>{
      if(current===generation.current){
        if(typeof module.ResearchWorkspace!=='function')throw new Error('Research panel unavailable');
        setState({...owner,phase:'ready',Panel:module.ResearchWorkspace});
      }
    }).catch(()=>{
      if(current===generation.current)setState({...owner,phase:'failed'});
    });
    return()=>{generation.current++;};
  },[loadPanel,attempt,props.identity,props.workspaceId,props.bot.address]);
  const current=state?.identity===props.identity&&state.workspaceId===props.workspaceId&&state.bot===props.bot.address?state:null;
  const Panel=current?.phase==='ready'?current.Panel:undefined;
  useEffect(()=>{
    const retry=retryFocus.current;
    if(!Panel||!retry)return;
    retryFocus.current=null;
    // Only replace focus lost with the explicit retry button. Do not interrupt
    // a clinician who moved to another field while the code was opening.
    if(document.activeElement===document.body&&!retry.isConnected)container.current?.focus();
  },[Panel]);
  return <div ref={container} className="research-panel-loader" role="region" aria-label="Research" tabIndex={-1}
    aria-busy={!Panel&&current?.phase!=='failed'}>
    {Panel?<Panel {...props}/>:<section className="team-prep" aria-label="Opening Research">
      <h2>Research</h2>
      {current?.phase==='failed'?<>
        <p role="alert">Research could not open. Your saved work is retained.</p>
        <p>This does not start a source lookup. If opening keeps failing, retain unsaved work before reopening CosmaBot.</p>
        <button className="team-primary" onClick={event=>{
          retryFocus.current=document.activeElement===event.currentTarget?event.currentTarget:null;
          setAttempt(value=>value+1);
        }}>Retry opening Research</button>
      </>:<p role="status">Opening Research…</p>}
    </section>}
  </div>;
}
