import {describe,expect,it} from 'vitest';
import {ASSISTANT_DESCRIPTIONS,assistantDescription,showComingSoonConnections,showCustomBotControls} from './assistant-copy';

describe('assistant copy',()=>{
  it('names each built-in assistant with a plain one-line description',()=>{
    expect(ASSISTANT_DESCRIPTIONS.chief).toBe('Your AI chief of staff: coordinates work and drafts for your review');
    expect(ASSISTANT_DESCRIPTIONS.scribe).toBe('Turns a recorded visit into a draft note');
    expect(ASSISTANT_DESCRIPTIONS.research).toBe('Finds and summarizes clinical and practice information with sources');
    expect(assistantDescription('visit_prep')).toMatch(/before a visit/i);
    expect(assistantDescription('follow_up')).toMatch(/follow-up/i);
    expect(assistantDescription('custom','Prepare referrals')).toBe('Prepare referrals');
  });
  it('keeps custom bots and coming-soon cards hidden unless the Vite flag is true',()=>{
    expect(showCustomBotControls({})).toBe(false);
    expect(showCustomBotControls({VITE_CUSTOM_BOTS_ENABLED:'false'})).toBe(false);
    expect(showCustomBotControls({VITE_CUSTOM_BOTS_ENABLED:'true'})).toBe(true);
    expect(showComingSoonConnections({})).toBe(false);
    expect(showComingSoonConnections({VITE_COMING_SOON_CONNECTIONS_ENABLED:'TRUE'})).toBe(false);
    expect(showComingSoonConnections({VITE_COMING_SOON_CONNECTIONS_ENABLED:'true'})).toBe(true);
  });
  it('hides coming-soon cards on the production-review profile even when the Vite flag is on',()=>{
    const production={VITE_COMING_SOON_CONNECTIONS_ENABLED:'true',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.beta.cosmas.ai'};
    const staging={VITE_COMING_SOON_CONNECTIONS_ENABLED:'true',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.staging.cosmas.ai'};
    expect(showComingSoonConnections(production)).toBe(false);
    expect(showComingSoonConnections(staging)).toBe(true);
  });
});
