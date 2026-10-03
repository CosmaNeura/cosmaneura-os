import {useEffect,useRef,useState,type ComponentType} from 'react';

/** Cache only loaded UI code. Failed imports retry only on explicit user action. */
export function deferredWorkspacePanel<P extends object>(load:()=>Promise<ComponentType<P>>,label:string){
  let cached:Promise<ComponentType<P>>|null=null;
  const request=()=>cached??(cached=Promise.resolve().then(load).then(panel=>{
    if(!panel||(typeof panel!=="function"&&typeof panel!=="object"))throw new Error("Panel unavailable");
    return panel;
  }).catch(error=>{cached=null;throw error;}));
  return function DeferredPanel(props:P){
    const [Panel,setPanel]=useState<ComponentType<P>|null>(null);
    const [failed,setFailed]=useState(false),[attempt,setAttempt]=useState(0);
    const container=useRef<HTMLDivElement|null>(null),retryFocus=useRef(false);
    useEffect(()=>{
      let current=true;setFailed(false);
      void request().then(panel=>{if(current)setPanel(()=>panel);}).catch(()=>{if(current)setFailed(true);});
      return()=>{current=false;};
    },[attempt]);
    useEffect(()=>{
      if(Panel&&retryFocus.current){retryFocus.current=false;if(document.activeElement===document.body)container.current?.focus();}
    },[Panel]);
    // Keep current props during loading; code resolution never restores old account props.
    return <div ref={container} tabIndex={-1} aria-label={label} aria-busy={!Panel&&!failed}>
      {Panel?<Panel {...props}/>:failed?<section className="team-prep">
        <p role="alert">{label} could not open. Your workspace is still open. Try again.</p>
        <button className="team-primary" onClick={event=>{retryFocus.current=document.activeElement===event.currentTarget;setAttempt(value=>value+1);}}>Retry opening {label}</button>
      </section>:<p role="status">Opening {label}…</p>}
    </div>;
  };
}
