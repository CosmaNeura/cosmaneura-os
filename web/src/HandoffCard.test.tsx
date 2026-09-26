import {act} from 'react';import {createRoot,type Root} from 'react-dom/client';import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {HandoffCard} from './HandoffCard';import type {DraftHandoff} from './workspace-api';
let root:Root,el:HTMLDivElement;const retry=vi.fn(),show=vi.fn();
const base:DraftHandoff={id:'invented',origin_entry_id:'invented-entry',recipient_role:'scribe',recipient_name:'Scribe',brief:'Invented draft brief',context_revision:4,status:'failed',attempt_id:'attempt',attempt_count:1,result_entry_id:null,error_code:null,attempts:[]};
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.clearAllMocks();el=document.createElement('div');document.body.append(el);root=createRoot(el);});afterEach(async()=>{await act(async()=>root.unmount());el.remove();vi.unstubAllGlobals();});
it.each([['team_work_limit','Not started: team work limit'],['legacy_queued_unadmitted','Not started by this version'],['legacy_running_unconfirmed','Earlier draft outcome unconfirmed']])('renders safe %s history without automatically retrying',async(error_code,label)=>{
 await act(async()=>root.render(<HandoffCard handoff={{...base,error_code}} locked={false} onRetry={retry} onShow={show}/>));expect(el.textContent).toContain(label);expect(retry).not.toHaveBeenCalled();expect(show).not.toHaveBeenCalled();
 await act(async()=>el.querySelector<HTMLButtonElement>('button')!.click());expect(retry).toHaveBeenCalledOnce();
});
it('withholds unknown error text and honors the existing three-attempt boundary',async()=>{
 await act(async()=>root.render(<HandoffCard handoff={{...base,error_code:'private raw provider failure'}} locked={false} onRetry={retry} onShow={show}/>));expect(el.textContent).not.toContain('private raw provider');expect(el.querySelector('button')).toBeNull();
 await act(async()=>root.render(<HandoffCard handoff={{...base,error_code:'team_work_limit',attempt_count:3}} locked={false} onRetry={retry} onShow={show}/>));expect(el.textContent).toContain('Three attempts recorded');expect(el.querySelector('button')).toBeNull();
});
