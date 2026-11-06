// @vitest-environment node
import {describe,expect,it} from 'vitest';
import {teamFixture} from '../team-setup-test-fixture';
import {PRESENTATION_KEY,WorkspacePresentationPreference} from './presentation';
import {WorkspaceSession} from './workspace-session';

describe('stable presentation chrome before team load',()=>{
  it('keeps messages labels settled before team.revision arrives and only changes on choose()',()=>{
    const values=new Map<string,string>([[PRESENTATION_KEY,'messages']]);
    const storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);}};
    const session=new WorkspaceSession({presentation:{enabled:true,phone:true,storage}});
    const labels=()=>session.presentation.current()==='messages'?['Chats','Visits','Work','Settings']:['Home','Visits and notes','Practice work','Settings'];
    expect(session.getSnapshot().team).toBeNull();
    expect(session.presentation.current()).toBe('messages');
    expect(labels()).toEqual(['Chats','Visits','Work','Settings']);
    session.setTeam({...teamFixture(),revision:0});
    expect(session.presentation.current()).toBe('messages');
    expect(labels()).toEqual(['Chats','Visits','Work','Settings']);
    session.setTeam(teamFixture());
    expect(session.presentation.current()).toBe('messages');
    expect(labels()).toEqual(['Chats','Visits','Work','Settings']);
    expect(session.presentation.choose('workspace',false)).toBe(true);
    expect(session.presentation.current()).toBe('workspace');
    expect(labels()).toEqual(['Home','Visits and notes','Practice work','Settings']);
    session.clear();
    expect(session.getSnapshot().team).toBeNull();
    expect(session.presentation.current()).toBe('workspace');
    expect(labels()).toEqual(['Home','Visits and notes','Practice work','Settings']);
  });
  it('uses the phone default before team load when nothing is saved',()=>{
    const session=new WorkspaceSession({presentation:{enabled:true,phone:true}});
    expect(session.presentation.current()).toBe('messages');
    session.setTeam(teamFixture());
    expect(session.presentation.current()).toBe('messages');
  });
  it('stays on workspace when messages presentation is disabled',()=>{
    const preference=new WorkspacePresentationPreference(new WorkspaceSession({presentation:{enabled:false,phone:true}}),{enabled:false,phone:true});
    expect(preference.current()).toBe('workspace');
  });
});
