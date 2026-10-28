/** Test-only event admission: readiness and the native click share one act turn. */
export async function clickEnabledLabButton(
  find: () => HTMLButtonElement | undefined,
  turn: (callback: () => Promise<void>) => Promise<unknown>,
  current: () => void,
  label: string,
) {
  const until = performance.now() + 15000;
  while (performance.now() < until) {
    current();
    let dispatched = false;
    await turn(async () => {
      await new Promise(resolve => setTimeout(resolve, 5));
      current();
      const target = find();
      if (!target?.isConnected || target.disabled) return;
      // Never retry after dispatch, even if the surrounding React turn rejects.
      dispatched = true;
      target.click();
    });
    current();
    if (dispatched) return;
  }
  throw new Error(`Enabled lab button was not available: ${label}`);
}
