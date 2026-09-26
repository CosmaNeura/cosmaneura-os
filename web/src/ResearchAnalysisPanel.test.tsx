import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,it,expect,vi} from 'vitest';
import {ResearchAnalysisPanel} from './ResearchAnalysisPanel';
import {analysisAnchor,analysisBody,analysisWorkspace} from './research-analysis-test-fixture';
import type {ResearchAnalysisDraft} from './research-analysis-contract';
import type {ConversationInput} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,element:HTMLDivElement;const submit=vi.fn(async(_body:ConversationInput)=>{}),smaller=vi.fn();
function Harness({text,model='Configured GPT-4.1',locked=false,enabled=true,modelBlocked=false}:{text?:string;model?:string;locked?:boolean;enabled?:boolean;modelBlocked?:boolean}){
 const [draft,setDraft]=useState<ResearchAnalysisDraft>({question:'',selected:false});return <ResearchAnalysisPanel access={{workspace:analysisWorkspace(text),model:{enabled,model},modelBlocked,onSubmit:submit}} packet={analysisAnchor} draft={draft} bot={analysisBody.role} teamRevision={1} enabled={true} locked={locked} onEdit={setDraft} onSubmit={submit} onSmaller={smaller}/>;
}
function button(text:string){const found=[...element.querySelectorAll('button')].find(b=>b.textContent===text);expect(found,text).toBeTruthy();return found!;}
async function click(text:string){expect(button(text).disabled).toBe(false);await act(async()=>button(text).click());}
async function check(text:string){const input=[...element.querySelectorAll('label')].find(l=>l.textContent?.includes(text))?.querySelector('input')!;expect(input).toBeTruthy();expect(input.disabled).toBe(false);await act(async()=>input.click());}
async function question(value:string){const field=element.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(props:Parameters<typeof Harness>[0]={}){await act(async()=>root.render(<Harness {...props}/>));}
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);submit.mockClear();smaller.mockClear();element=document.createElement('div');document.body.append(element);root=createRoot(element);});afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();});
it('requires separate packet selection, editable question, destination review and consent without auto-dispatch',async()=>{
 await mount();expect(element.querySelector('textarea')).toBeNull();await click('Ask Research about saved sources');expect(element.querySelector('textarea')!.value).toBe('');expect(button('Review AI request').disabled).toBe(true);await check('Use saved source packet');await question('Explain only these source excerpts');await click('Review AI request');expect(element.textContent).toContain('To configured model: Configured GPT-4.1');expect(element.textContent).toContain('No notebook, preparation, work status');expect(button('Send to Research').disabled).toBe(true);expect(submit).not.toHaveBeenCalled();await check('I consent to sending');await click('Send to Research');
 expect(submit).toHaveBeenCalledOnce();const body=submit.mock.calls[0][0];expect(body).toMatchObject({expected_revision:3,team_revision:1,content:'Explain only these source excerpts',research_analysis:{version:1,consented:true,entries:[analysisAnchor]}});expect(Object.keys(body).sort()).toEqual(['content','expected_revision','idempotency_key','research_analysis','role','team_revision']);
});
it('refuses an oversized packet before consent and offers an explicit smaller save without truncation',async()=>{
 await mount({text:'x'.repeat(5001)});await click('Ask Research about saved sources');expect(element.textContent).toContain('5,000-character analysis limit');expect(element.querySelector('.research-excerpt')!.textContent).toHaveLength(5001);expect(button('Review AI request').disabled).toBe(true);await click('Choose fewer excerpts to save');expect(smaller).toHaveBeenCalledOnce();expect(submit).not.toHaveBeenCalled();
});
it('invalidates consent when destination, source content or capture lock changes, retaining the question',async()=>{
 await mount();await click('Ask Research about saved sources');await check('Use saved source packet');await question('Question to retain');await click('Review AI request');await check('I consent to sending');await mount({model:'New model'});expect(element.querySelector('[aria-label="Review selected source analysis"]')).toBeNull();expect(element.querySelector('textarea')!.value).toBe('Question to retain');await click('Review AI request');await mount({model:'New model',locked:true});expect(element.querySelector('[aria-label="Review selected source analysis"]')).toBeNull();expect(button('Review AI request').disabled).toBe(true);expect(submit).not.toHaveBeenCalled();
});
it('keeps saved-source analysis unavailable when no model is configured, with no source I/O dependency',async()=>{
 await mount({enabled:false});await click('Ask Research about saved sources');expect(element.textContent).toContain('AI analysis is not connected');await question('Retained question');expect(button('Review AI request').disabled).toBe(true);expect(submit).not.toHaveBeenCalled();
});
it('admits only one direct consented handoff while its first callback is unsettled',async()=>{
 let finish!:()=>void;submit.mockImplementationOnce(()=>new Promise<void>(resolve=>{finish=resolve;}));await mount();await click('Ask Research about saved sources');await check('Use saved source packet');await question('One request');await click('Review AI request');await check('I consent to sending');const send=button('Send to Research');await act(async()=>{send.click();send.click();});expect(submit).toHaveBeenCalledOnce();await act(async()=>finish());
});

it('withholds new analysis when this bot blocks model answers without discarding saved sources',async()=>{
 await mount({modelBlocked:true});await click('Ask Research about saved sources');expect(element.textContent).toContain('AI answers are blocked for this bot');expect(element.textContent).toContain('Invented saved public-source packet');expect(button('Review AI request').disabled).toBe(true);expect(submit).not.toHaveBeenCalled();
});
