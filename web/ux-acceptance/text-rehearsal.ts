type Property={value:string;priority:string};
type TextOverride={font:Property;line:Property;appliedFont:string;appliedLine:string};

/** Text-only stress fixture. Product CSS, viewport and control sizing stay intact. */
export function installTextRehearsal(root:HTMLElement):()=>void {
  if(new URLSearchParams(location.search).get('text-size')!=='200')return()=>{};
  const overrides=new WeakMap<HTMLElement,TextOverride>();
  let frame:number|null=null,stopped=false;
  const read=(element:HTMLElement,name:string):Property=>({value:element.style.getPropertyValue(name),priority:element.style.getPropertyPriority(name)});
  const restore=(element:HTMLElement,name:string,property:Property)=>{
    if(property.value)element.style.setProperty(name,property.value,property.priority);
    else element.style.removeProperty(name);
  };
  const observe=()=>observer.observe(root,{subtree:true,childList:true,characterData:true,attributes:true});
  function apply(){
    frame=null;if(stopped)return;
    observer.disconnect();
    const workspace=root.querySelector<HTMLElement>('.team-workspace');
    const elements=workspace?[workspace,...workspace.querySelectorAll<HTMLElement>('*')].filter(element=>element instanceof HTMLElement):[];
    // Restore every ancestor before measuring any descendant. This prevents
    // inherited text or newly mounted panels from being doubled repeatedly.
    for(const element of elements){
      const prior=overrides.get(element);if(!prior)continue;
      if(element.style.fontSize!==prior.appliedFont)prior.font=read(element,'font-size');
      if(element.style.lineHeight!==prior.appliedLine)prior.line=read(element,'line-height');
      restore(element,'font-size',prior.font);restore(element,'line-height',prior.line);
    }
    const measurements=elements.map(element=>{
      const style=getComputedStyle(element);
      return {element,font:parseFloat(style.fontSize),line:parseFloat(style.lineHeight)};
    });
    for(const {element,font,line} of measurements){
      if(!Number.isFinite(font))continue;
      const prior=overrides.get(element)??{font:read(element,'font-size'),line:read(element,'line-height'),appliedFont:'',appliedLine:''};
      element.style.setProperty('font-size',`${font*2}px`,'important');
      if(Number.isFinite(line))element.style.setProperty('line-height',`${line*2}px`,'important');
      prior.appliedFont=element.style.fontSize;prior.appliedLine=element.style.lineHeight;overrides.set(element,prior);
    }
    root.dataset.textScale='200';observe();
  }
  function schedule(){if(!stopped&&frame===null)frame=requestAnimationFrame(apply);}
  const observer=new MutationObserver(schedule);observe();schedule();
  window.addEventListener('resize',schedule);window.visualViewport?.addEventListener('resize',schedule);
  return()=>{stopped=true;observer.disconnect();if(frame!==null)cancelAnimationFrame(frame);window.removeEventListener('resize',schedule);window.visualViewport?.removeEventListener('resize',schedule);};
}
