export function readScreen(document, pack) {
  const unrecognised = {state: 'screen_not_recognised'};
  // A pack is data: exactly these selector slots and field names. Never execute it.
  if (!pack || Object.keys(pack).sort().join() !== 'fields,rows,screen'
      || Object.keys(pack.fields ?? {}).sort().join() !== 'appointment,person,time'
      || ![pack.screen, pack.rows, ...Object.values(pack.fields)].every(value => typeof value === 'string' && value.length <= 200)) return unrecognised;
  try {
    const screen = document.querySelector(pack.screen);
    if (!screen) return unrecognised;
    const nodes = [...screen.querySelectorAll(pack.rows)];
    if (!nodes.length || nodes.length > 50) return unrecognised;
    const rows = nodes.map(node => Object.fromEntries(Object.entries(pack.fields).map(([field, selector]) => {
      const matches = node.querySelectorAll(selector);
      const text = matches.length === 1 ? matches[0].textContent.trim() : '';
      if (!text || text.length > 200) throw new Error();
      return [field, text];
    })));
    return {state: 'recognised', rows};
  } catch { return unrecognised; }
}
