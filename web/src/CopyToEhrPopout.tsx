import {useEffect,useRef,useState} from 'react';
import './copy-to-ehr.css';

type DocumentPictureInPicture={
  requestWindow:(options?:{width?:number;height?:number})=>Promise<Window>;
  window:Window|null;
};

function documentPip():DocumentPictureInPicture|null{
  const candidate=(window as Window&{documentPictureInPicture?:DocumentPictureInPicture}).documentPictureInPicture;
  return candidate&&typeof candidate.requestWindow==='function'?candidate:null;
}

export type CopyToEhrPopoutProps={
  disabled?:boolean;
  sectionLabel:string;
  sectionIndex:number;
  sectionCount:number;
};

/**
 * Chrome/Edge: Document Picture-in-Picture floating list.
 * Firefox, Safari, and iPad: same component shows split-screen guidance.
 */
export function CopyToEhrPopout({disabled=false,sectionLabel,sectionIndex,sectionCount}:CopyToEhrPopoutProps){
  const [mode,setMode]=useState<'idle'|'pip'|'guidance'|'unavailable'>('idle');
  const [error,setError]=useState('');
  const pipHost=useRef<HTMLDivElement>(null);
  const pipWindow=useRef<Window|null>(null);

  useEffect(()=>()=>{
    try{pipWindow.current?.close();}catch{/* Pop-out close is best-effort. */}
    pipWindow.current=null;
  },[]);

  useEffect(()=>{
    const win=pipWindow.current;
    if(!win||win.closed||!pipHost.current)return;
    const label=win.document.getElementById('copy-to-ehr-pip-label');
    if(label)label.textContent=`Next: ${sectionLabel} · ${sectionIndex+1} of ${sectionCount}`;
  },[sectionLabel,sectionIndex,sectionCount]);

  async function openPopout(){
    if(disabled)return;
    setError('');
    const api=documentPip();
    if(!api){
      setMode('guidance');
      return;
    }
    try{
      const win=await api.requestWindow({width:360,height:220});
      pipWindow.current=win;
      win.document.title='Copy to EHR';
      win.document.body.replaceChildren();
      const style=win.document.createElement('style');
      style.textContent='body{font:16px/1.4 system-ui,sans-serif;margin:12px;color:#273c32;background:#f7faf6}p{margin:0 0 8px}strong{display:block;margin-top:8px}';
      win.document.head.append(style);
      const root=win.document.createElement('div');
      root.innerHTML=`<p>Keep this list above your chart.</p><strong id="copy-to-ehr-pip-label">Next: ${sectionLabel} · ${sectionIndex+1} of ${sectionCount}</strong><p>Paste with your keyboard. CosmaBot never types into the chart.</p>`;
      win.document.body.append(root);
      if(pipHost.current)win.document.body.append(pipHost.current);
      win.addEventListener('pagehide',()=>{pipWindow.current=null;setMode('idle');},{once:true});
      setMode('pip');
    }catch{
      setMode('unavailable');
      setError('The floating copy list could not open. Use split screen instead.');
    }
  }

  return <div className="copy-to-ehr-popout">
    <button type="button" disabled={disabled||mode==='pip'} onClick={()=>void openPopout()}>
      {mode==='pip'?'Pop-out open':'Pop out'}
    </button>
    <div ref={pipHost} hidden/>
    {mode==='guidance'&&<aside className="copy-to-ehr-guidance" role="status">
      <p>This browser does not support a floating copy list. Open CosmaBot and your chart side by side with split screen, then use the copy buttons on this page.</p>
      <p className="team-fine">On an iPad or in Safari, split the screen. Paste stays a manual step.</p>
      <button type="button" onClick={()=>setMode('idle')}>Hide guidance</button>
    </aside>}
    {mode==='unavailable'&&error&&<p role="status">{error}</p>}
    {mode==='pip'&&<p role="status">Floating copy list is open. Paste stays a manual step in the chart.</p>}
  </div>;
}

export function supportsDocumentPictureInPicture():boolean{
  return documentPip()!==null;
}
