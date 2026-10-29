import {act} from 'react';

/** Wall-clock settle window for Messages journey tests (matches server-lab 45s bump). */
export const MESSAGES_JOURNEY_SETTLE_MS = 45000;
const POLL_MS = 2;

export async function waitMessagesJourney(check: () => void, timeoutMs = MESSAGES_JOURNEY_SETTLE_MS) {
  const end = performance.now() + timeoutMs;
  while (performance.now() < end) {
    let done = false;
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, POLL_MS));
      try {
        check();
        done = true;
      } catch {}
    });
    if (done) return;
  }
  check();
}

/** Vitest case budget when a journey waits for async account journal / composer readiness. */
export const MESSAGES_JOURNEY_TEST_TIMEOUT_MS = 60000;
