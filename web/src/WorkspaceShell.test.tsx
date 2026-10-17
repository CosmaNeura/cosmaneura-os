import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {renderToStaticMarkup} from 'react-dom/server';
import {expect,it,vi} from 'vitest';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {WorkspaceDialog} from './WorkspaceDialog';
import {readWorkspaceRoute,workspaceRouteHash} from './workspace-route';

it('renders note structure while suppressing HTML, unsafe URLs and remote images',()=>{
  const html=renderToStaticMarkup(<WorkspaceMarkdown content={'## Assessment\n\n**Dizziness**\n\n- Review medications\n- Follow up\n\n[unsafe](javascript:alert(1))\n\n![tracking](https://example.com/track)\n\n<script>alert(1)</script>'}/>);
  expect(html).toContain('<h2>Assessment</h2>');expect(html).toContain('<strong>Dizziness</strong>');expect(html).toContain('<li>Review medications</li>');
  expect(html).not.toContain('<script');expect(html).not.toContain('javascript:');expect(html).not.toContain('<img');expect(html).not.toContain('track');
});

it('uses only opaque identifiers and supported screens in notebook routes',()=>{
  const route={page:'notebook' as const,workspaceId:'00000000-0000-4000-8000-000000000021',helper:'scribe',material:'Review'};
  expect(readWorkspaceRoute(workspaceRouteHash(route))).toEqual(route);
  expect(readWorkspaceRoute('#cosmas/notebook/Patient%20Name')).toBeNull();
  expect(readWorkspaceRoute('#cosmas/notebook/00000000-0000-4000-8000-000000000021?material=unknown')).toBeNull();
  expect(readWorkspaceRoute('#google-connected')).toBeNull();
});

it('traps dialog focus, closes with Escape and restores the invoking control',async()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  const host=document.createElement('div'),trigger=document.createElement('button');document.body.append(trigger,host);trigger.focus();
  const root=createRoot(host),close=vi.fn();
  try{
    await act(async()=>root.render(<WorkspaceDialog title="Keep team changes?" onClose={close}><button>Keep editing</button><button>Discard</button></WorkspaceDialog>));
    const buttons=host.querySelectorAll('button');expect(document.activeElement).toBe(buttons[0]);buttons[1].focus();
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));expect(document.activeElement).toBe(buttons[0]);
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(close).toHaveBeenCalledOnce();
    await act(async()=>root.unmount());expect(document.activeElement).toBe(trigger);
  }finally{host.remove();trigger.remove();vi.unstubAllGlobals();}
});
