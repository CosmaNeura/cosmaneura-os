import {useLayoutEffect,useMemo,useRef,useState,type RefObject} from 'react';
import './copy-answer.css';

/** An explicit local copy of a completed answer; never a send or record approval. */
export function CopyAnswer({content,scope,disabled,isCurrent,edited=false,manualSelectionTarget}:{content:string;scope:object;disabled:boolean;isCurrent:()=>boolean;edited?:boolean;manualSelectionTarget?:RefObject<HTMLTextAreaElement|null>}){
  const episode=useMemo(()=>({}),[content,scope]),current=useRef<object|null>(episode);current.current=episode;
  const controls=useRef({disabled,isCurrent});controls.current={disabled,isCurrent};
  const inFlight=useRef(false),text=useRef<HTMLTextAreaElement>(null);
  const [result,setResult]=useState<{episode:object;state:'copying'|'copied'|'manual'}|null>(null);
  useLayoutEffect(()=>{current.current=episode;return()=>{if(current.current===episode)current.current=null;};},[episode]);
  const state=result?.episode===episode?result.state:null;
  const available=()=>current.current===episode&&!controls.current.disabled&&controls.current.isCurrent();
  async function copy(){
    if(!available()||inFlight.current||!content.trim())return;
    inFlight.current=true;setResult({episode,state:'copying'});
    try{
      if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(content);
      if(available())setResult({episode,state:'copied'});
    }catch{
      if(available())setResult({episode,state:'manual'});
    }finally{
      inFlight.current=false;
      // A settled attempt blocked by a temporary lock must remain retryable.
      // Clear only its progress; never publish a late success or fallback.
      if(current.current===episode)setResult(value=>value?.episode===episode&&value.state==='copying'?null:value);
    }
  }
  return <section className="message-copy-answer" aria-label="Use this answer">
    <button type="button" disabled={disabled||state==='copying'||!content.trim()} onClick={()=>void copy()}>{edited?'Copy edited copy':'Copy answer'}</button>
    {state==='copying'&&<p role="status">Copying…</p>}
    {state==='copied'&&<p role="status">Copied to your clipboard. Review the draft before using it.</p>}
    {state==='manual'&&<><p role="status">{manualSelectionTarget?'Copy is unavailable here. Select your edited copy above and use Copy.':'Copy is unavailable here. Select the answer below and use Copy.'}</p>
      {!manualSelectionTarget&&<label>{edited?'Edited copy to copy':'Answer to copy'}<textarea ref={text} readOnly value={content} disabled={disabled} /></label>}
      <button type="button" disabled={disabled} onClick={()=>{if(available()){const target=(manualSelectionTarget??text).current;if(target?.isConnected&&!target.disabled&&(!manualSelectionTarget||target.value===content.replace(/\r\n?/g,'\n'))){target.focus({preventScroll:true});target.select();}}}}>{edited?'Select edited copy':'Select answer'}</button></>}
  </section>;
}
