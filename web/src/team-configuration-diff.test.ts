import {describe,it,expect} from 'vitest';
import {teamConfigurationDiff} from './team-configuration-diff';
import {teamFixture} from './team-setup-test-fixture';
describe('meaningful team changes',()=>{
  it('ignores omitted defaults, empty optional strings, property order and reordered set choices',()=>{
    const saved=structuredClone(teamFixture().configuration),draft=structuredClone(saved);
    saved.bots[0].skills=['saved_context','work_status'];draft.bots[0].skills=['work_status','saved_context'];
    draft.bots.reverse();draft.bots.forEach(bot=>{bot.job_focus='';bot.working_preferences='  ';bot.retired=false;});
    draft.presets=[];expect(teamConfigurationDiff(saved,draft).count).toBe(0);
  });
  it('shows only Scribe’s changed name and instructions when other defaults are filled in',()=>{
    const saved=teamFixture().configuration,draft=structuredClone(saved);
    draft.bots[0].name='Visit scribe';draft.bots[0].working_preferences='Keep uncertainty visible';
    const diff=teamConfigurationDiff(saved,draft);expect(diff.count).toBe(2);expect(diff.bots).toHaveLength(1);
    expect(diff.bots[0].fields.map(change=>change.field)).toEqual(['name','working_preferences']);
    expect(diff.settings).toEqual([]);
  });
});
