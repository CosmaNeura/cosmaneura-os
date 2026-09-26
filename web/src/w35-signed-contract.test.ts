import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import setup from './__fixtures__/w35-signed/team-setup-v2.json';
import resources from './__fixtures__/w35-signed/team-resources-v1.json';
import usage from './__fixtures__/w35-signed/team-usage-v1.json';
import rehearsal from './__fixtures__/w35-signed/team-rehearsal-v2.json';
import saved from './__fixtures__/w35-signed/model-saved.json';
import workspace from './__fixtures__/w35-signed/model-workspace.json';
import {validProviderTeam,validPresetCatalog,validSetupProjection,validTeamRehearsal,validResourceInventory,validModelUsage} from './team-setup-validators';
import {configurationHash} from './team-setup-request';
import {validModelObservation,validModelWorkspace} from './model-work-request';
import type {TeamConfiguration} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
// Actual signed application responses using isolated PostgreSQL and an injected model.
// These fixtures do not establish live provider or device acceptance.
it('accepts the actual signed v2 team response and verifies the exact configuration commitment',async()=>{
 expect(validProviderTeam(setup.team)).toBe(true);expect(validPresetCatalog(setup.catalog)).toBe(true);
 expect(validSetupProjection(setup.setup,setup.team.configuration as TeamConfiguration,setup.team.revision)).toBe(true);
 expect(await configurationHash(setup.team.configuration as TeamConfiguration)).toBe(setup.setup.configuration_sha256);
});
it('accepts the actual v2 rehearsal with its complete ordered invented cases',async()=>{
 expect(validTeamRehearsal(rehearsal)).toBe(true);expect(await configurationHash(rehearsal.configuration as TeamConfiguration)).toBe(rehearsal.setup_review.configuration_sha256);
});
it('accepts actual opaque resources and metered usage without private account correspondence',()=>{
 expect(validResourceInventory(resources)).toBe(true);expect(validModelUsage(usage)).toBe(true);
});
it('accepts the exact actual saved model receipt and corresponding current workspace projection',async()=>{
 expect(validModelObservation(saved)).toBe(true);expect(await validModelWorkspace(workspace,workspace.id)).toBe(true);
 expect(workspace.entries.some(e=>e.id===saved.saved_entry?.id&&e.revision===saved.saved_entry.revision)).toBe(true);
});
