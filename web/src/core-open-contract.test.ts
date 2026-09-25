import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-open.json';
import {validateCoreCommand,validateCoreConnection,type CoreConnectionCommand} from './core-connection-contract';

beforeEach(()=>vi.setSystemTime(new Date(fixture.open.response.discovery.checked_at)));
afterEach(()=>vi.useRealTimers());
it('accepts the actual signed open receipt and its exact selected appointment',async()=>{
  const command=fixture.open.command as CoreConnectionCommand;
  validateCoreCommand(command);
  await expect(validateCoreConnection(fixture.open.response,command)).resolves.toEqual(fixture.open.response);
});
it.each(['missing','extra','invalid','selection'])('rejects an invalid open binding: %s',async fault=>{
  const value=structuredClone(fixture.open.response) as any;
  if(fault==='missing')delete value.workspace;
  if(fault==='extra')value.workspace.owner_id=crypto.randomUUID();
  if(fault==='invalid')value.workspace.workspace_id='not-a-workspace';
  const command={...fixture.open.command,...(fault==='selection'?{source_sha256:'0'.repeat(64)}:{})} as CoreConnectionCommand;
  await expect(validateCoreConnection(value,command)).rejects.toThrow();
});
