import {describe,expect,it} from 'vitest';
import {validateRecordLocation,validCoreWebOrigin,parseRecordNavigationResult} from './core-record-location';
const workspace='00000000-0000-4000-8000-000000000001',origin='https://core.example.invalid';
const appointment='appointment_'+'0'.repeat(25)+'1';
const fixture=()=>({contract_version:1,workspace_id:workspace,appointment_ref:appointment,href:origin+'/notes/'+appointment,checked_at:new Date().toISOString()});

describe('Cosmaneura navigation correspondence',()=>{
  it('retains only the exact existing record destination',()=>{const v=fixture();expect(validateRecordLocation(v,workspace,origin)).toEqual(v);});
  it.each(['','http://core.example.invalid','https://core.example.invalid/','https://CORE.example.invalid','https://core.example.invalid:443',
    'https://core.example.invalid?next=x','https://user@core.example.invalid','https://core.example.invalid\\evil',
    'https://core..invalid','https://-core.invalid','https://cöre.invalid','https://127.1',
    'https://localhost','https://127.0.0.1','https://core.example.invalid:8443','https://core.123',
    'https://core.0xabc','https://0x7f000001'])('rejects ambiguous origin %s',v=>expect(validCoreWebOrigin(v)).toBe(false));
  it.each([{workspace_id:'00000000-0000-4000-8000-000000000002'},{href:'https://other.invalid/notes/'+appointment},
    {href:origin+'/notes/'+appointment+'?token=secret'},{href:origin+'/notes/'+appointment+'#content'},
    {href:origin+'/notes/%61ppointment_'+'0'.repeat(25)+'1'},{appointment_ref:'../patients'},
    {checked_at:'2020-01-01T00:00:00Z'},{checked_at:new Date(Date.now()+60000).toISOString()},
    {contract_version:2},{token:'private'},{note_saved:true}])('rejects scope, destination and unsupported evidence %j',change=>{
      expect(()=>validateRecordLocation({...fixture(),...change},workspace,origin)).toThrow();
    });
  it('accepts only the matching bounded native navigation event, with no record-state inference',()=>{
    const value={schemaVersion:1,requestId:workspace,status:'opened'};
    expect(parseRecordNavigationResult(JSON.stringify(value),workspace)).toEqual(value);
    for(const v of [{...value,requestId:crypto.randomUUID()},{...value,saved:true},{...value,status:'reviewed'}])
      expect(parseRecordNavigationResult(JSON.stringify(v),workspace)).toBeNull();
    expect(parseRecordNavigationResult('{"schemaVersion":1,"schemaVersion":1}',workspace)).toBeNull();
  });
});
