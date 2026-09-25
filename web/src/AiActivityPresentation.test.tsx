import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AiActivityPanel} from './AiActivityPanel';
import {modelActivityApi} from './model-activity-api';
import {activityContext,activityPage} from './model-activity-test-fixture';

const {readFileSync}=await vi.importActual<{readFileSync:(path:string,encoding:'utf8')=>string}>('node:fs');
const {fileURLToPath}=await vi.importActual<{fileURLToPath:(url:string)=>string}>('node:url');
const styles=readFileSync(fileURLToPath(import.meta.url).replace(/[^/]+$/,'AiActivityPanel.css'),'utf8');

vi.mock('./model-activity-api',()=>({modelActivityApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root,style:HTMLStyleElement;
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-presentation-token'},open=vi.fn(),lost=vi.fn();
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);
  style=document.createElement('style');style.textContent=styles;document.head.append(style);vi.mocked(modelActivityApi.read).mockResolvedValue(activityPage());});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();style.remove();vi.unstubAllGlobals();});
async function mount(){await act(async()=>root.render(<AiActivityPanel identity={identity} context={activityContext} locked={false} onOpenEncounter={open} onAccessLost={lost}/>));}
const button=(text:string)=>{const found=[...host.querySelectorAll('button')].find(node=>node.textContent===text);expect(found).toBeTruthy();return found!;};
const follows=(earlier:Element,later:Element)=>Boolean(earlier.compareDocumentPosition(later)&Node.DOCUMENT_POSITION_FOLLOWING);
function declared(selector:string,width:number){
  const found:Record<string,string>={};
  function read(rules:CSSRuleList){for(const rule of Array.from(rules)){
    if(rule.type===CSSRule.MEDIA_RULE){const media=rule as CSSMediaRule,limit=/max-width:\s*(\d+)px/.exec(media.conditionText);if(!limit||width<=Number(limit[1]))read(media.cssRules);}
    else if(rule.type===CSSRule.STYLE_RULE){const entry=rule as CSSStyleRule;if(entry.selectorText.split(',').map(part=>part.trim()).includes(selector)){
      for(let i=0;i<entry.style.length;i++){const key=entry.style[i];found[key]=entry.style.getPropertyValue(key).trim();}
    }
    }
  }}
  read(style.sheet!.cssRules);return found;
}

it('puts the first row ahead of explanatory disclosures with a concise intro and machine-readable observed time',async()=>{
  await mount();const first=host.querySelector('.ai-activity-list>li')!,details=[...host.querySelectorAll('details')];
  expect(details).toHaveLength(2);expect(details.every(node=>!node.open&&follows(first,node))).toBe(true);
  expect(details.map(node=>node.querySelector('summary')?.textContent)).toEqual(['About this activity','Rolling allowance and verified usage']);
  expect(host.querySelector('.ai-activity-intro')?.textContent).toBe('AI answers and private bot drafts.');
  expect(host.querySelector('time')?.dateTime).toBe(activityPage().as_of);
  expect(host.querySelector('time')?.textContent).toContain('device time');
  expect(host.querySelector('[role="group"][aria-label="Activity view"]')?.querySelectorAll('button')).toHaveLength(2);
  expect(modelActivityApi.read).toHaveBeenCalledOnce();expect(open).not.toHaveBeenCalled();
});

it('keeps unknown row usage visible and preserves completion, coverage and cost limits inside closed disclosures',async()=>{
  const page=activityPage();page.rows[0].admission.state='unknown';page.rows[0].admission.dispatch='unconfirmed';page.usage.pending_units=0;page.usage.unknown_units=1;vi.mocked(modelActivityApi.read).mockResolvedValueOnce(page);
  await mount();const row=host.querySelector('.ai-activity-list>li')!,about=host.querySelectorAll('details')[0],usage=host.querySelectorAll('details')[1];
  expect(row.textContent).toContain('Outcome unconfirmed');expect(row.textContent).toContain('Token usage unknown.');
  expect(about.open).toBe(false);expect(about.textContent).toContain('does not verify that practice work is complete');
  expect(about.textContent).toContain('Older retained usage can affect allowance without appearing here');
  expect(about.textContent).toContain('outcomes can change');
  expect(usage.open).toBe(false);expect(usage.textContent).toContain('missing usage is unknown');expect(usage.textContent).toContain('not currency costs');
});

it('opens explanatory details without an API request, selection, or new authority',async()=>{
  await mount();const about=host.querySelector('details')!;
  await act(async()=>about.querySelector('summary')!.click());
  expect(about.open).toBe(true);expect(modelActivityApi.read).toHaveBeenCalledOnce();expect(open).not.toHaveBeenCalled();expect(lost).not.toHaveBeenCalled();
});

it('keeps a source-withholding notice outside closed explanations when an empty page is returned',async()=>{
  const page=activityPage('attention',0);page.coverage.withheld_total=2;vi.mocked(modelActivityApi.read).mockResolvedValueOnce(page);
  await mount();const notice=[...host.querySelectorAll('p')].find(node=>node.textContent==='Some activity is withheld because its sources are unavailable.')!;
  expect(notice).toBeTruthy();expect(notice.closest('details')).toBeNull();expect(host.textContent).toContain('No active or unconfirmed activity');
  expect(open).not.toHaveBeenCalled();
});

it('retains keyboard focus and pressed-state semantics across explicit view reads',async()=>{
  await mount();const ended=button('Ended activity');ended.focus();vi.mocked(modelActivityApi.read).mockResolvedValueOnce(activityPage('recent'));
  await act(async()=>ended.click());expect(document.activeElement).toBe(ended);expect(ended.getAttribute('aria-pressed')).toBe('true');
  expect(button('Active and unconfirmed').getAttribute('aria-pressed')).toBe('false');expect(modelActivityApi.read).toHaveBeenCalledTimes(2);expect(open).not.toHaveBeenCalled();
});

it.each([304,375,390,1024])('declares two equal shrinkable view columns and 44px touch targets at %ipx without a mobile stacking override',async width=>{
  await mount();host.style.width=width+'px';
  // CSS/cascade qualification only: JSDOM does not measure browser geometry.
  const views=declared('.ai-activity-views',width),viewButton=declared('.ai-activity-views button',width),target=declared('.ai-activity button',width);
  expect(views.display).toBe('grid');expect(views['grid-template-columns']).toBe('repeat(2,minmax(0,1fr))');expect(views.gap).toBe('.5rem');
  expect(viewButton['min-width']).toBe('0');expect(viewButton.width).toBe('100%');expect(target['min-height']).toBe('44px');
  expect(declared('.ai-activity',width)['min-width']).toBe('0');expect(declared('.ai-activity',width)['overflow-wrap']).toBe('anywhere');
  const toolbar=declared('.ai-activity-toolbar',width);expect(toolbar.display).toBe('flex');expect(toolbar['align-items']).toBe('center');
  expect(declared('.ai-activity .ai-activity-refresh',width).flex).toBe('0 0 auto');
});
