import type {BotRole} from './workspace-api';
import {isProductionReviewProfile} from './production-review-copy';

/** Plain one-line descriptions for built-in AI assistants. Not API/template text. */
export const ASSISTANT_DESCRIPTIONS: Record<Exclude<BotRole, 'custom'>, string> = {
  chief: 'Your AI chief of staff: coordinates work and drafts for your review',
  scribe: 'Turns a recorded visit into a draft note',
  research: 'Finds and summarizes clinical and practice information with sources',
  visit_prep: 'Gathers what you need before a visit',
  follow_up: 'Tracks follow-up work after a visit',
};

export function assistantDescription(role: BotRole, fallback = 'A custom assistant for a job you define'): string {
  if (role === 'custom') return fallback;
  return ASSISTANT_DESCRIPTIONS[role];
}

/** Custom-bot creation and capability restrictions stay off unless explicitly enabled. */
export function showCustomBotControls(env: Record<string, string | boolean | undefined> = import.meta.env): boolean {
  return env.VITE_CUSTOM_BOTS_ENABLED === 'true';
}

/** Coming-soon connection cards stay hidden unless explicitly enabled.
 * Production-review builds always hide them (App Store must not show test-stage placeholders). */
export function showComingSoonConnections(env: Record<string, string | boolean | undefined> = import.meta.env): boolean {
  if (isProductionReviewProfile(env)) return false;
  return env.VITE_COMING_SOON_CONNECTIONS_ENABLED === 'true';
}
