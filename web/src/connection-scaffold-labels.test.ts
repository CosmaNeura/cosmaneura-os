import {describe,expect,it} from 'vitest';
import {CONNECTION_ACTION_LABELS,SCAFFOLD_CONNECTION_LABELS} from './connection-guides';

describe('Track 3 scaffold Connections labels',()=>{
  it('exposes prescription and fax sandbox labels without enabling connectors',()=>{
    expect(SCAFFOLD_CONNECTION_LABELS.prescription_read).toBe('Prescription sandbox status');
    expect(SCAFFOLD_CONNECTION_LABELS.prescription_send).toBe('Send prescription');
    expect(SCAFFOLD_CONNECTION_LABELS.efax_sandbox_read).toBe('Fax sandbox status');
    expect(SCAFFOLD_CONNECTION_LABELS.efax_sandbox_send).toBe('Send fax (scaffold)');
    expect(CONNECTION_ACTION_LABELS.prescription_send).toBe(SCAFFOLD_CONNECTION_LABELS.prescription_send);
    expect(CONNECTION_ACTION_LABELS.efax_sandbox_read).toBe(SCAFFOLD_CONNECTION_LABELS.efax_sandbox_read);
  });

  it('keeps messaging copy clear that prescription send stays unavailable',async()=>{
    const {CONNECTION_GUIDES}=await import('./connection-guides');
    expect(CONNECTION_GUIDES.messaging.description).toContain('Prescription send stays unavailable');
    expect(CONNECTION_GUIDES.messaging.access).toContain('do not send live prescriptions or faxes');
  });
});
