import {afterEach, expect, it, vi} from 'vitest';
import {ScribeLabEpisode} from './scribe-lab-episode';

function gate<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return {promise, resolve};
}
afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); });

it('cancels a timed-out committed response before late work can act on the next mounted context', async () => {
  vi.useFakeTimers();
  const episode = new ScribeLabEpisode(), delivery = gate<ArrayBuffer>();
  const firstHost = document.createElement('div'), nextHost = document.createElement('div');
  firstHost.textContent = 'physician'; nextHost.textContent = 'nurse';
  document.body.append(firstHost, nextHost);
  let commits = 0, firstClicks = 0, nextClicks = 0;
  const firstButton = document.createElement('button'), nextButton = document.createElement('button');
  firstButton.onclick = () => firstClicks++; nextButton.onclick = () => nextClicks++;
  firstHost.append(firstButton); nextHost.append(nextButton);
  const upstream = vi.fn(async () => {
    commits++; // The invented server has already committed the original request.
    const response = new Response('saved');
    response.arrayBuffer = () => delivery.promise;
    return response;
  });
  const result = episode.run(async () => {
    await episode.fetch(upstream, '/original-review', {method: 'POST'});
    episode.check();
    firstButton.click();
  }, 20);
  const rejected = expect(result).rejects.toThrow('deadline exceeded');
  await vi.advanceTimersByTimeAsync(20);
  expect(episode.closed).toBe(true);
  firstHost.remove();
  delivery.resolve(new TextEncoder().encode('saved').buffer);
  await rejected;
  await episode.drain(100);
  const next = new ScribeLabEpisode();
  await next.run(async () => { next.check(); nextButton.click(); }, 100);
  expect(commits).toBe(1);
  expect(upstream).toHaveBeenCalledTimes(1);
  expect(firstClicks).toBe(0);
  expect(nextClicks).toBe(1);
  expect(nextHost.textContent).toBe('nurse');
  expect(episode.pendingPaths).toEqual([]);
});

it('retains and aborts the caller signal until the response body finishes', async () => {
  const episode = new ScribeLabEpisode(), caller = new AbortController();
  const reading = gate<void>();
  const upstream = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const response = new Response('headers arrived');
    response.arrayBuffer = () => {
      reading.resolve();
      return new Promise((_resolve, reject) => {
        init!.signal!.addEventListener('abort', () => reject(init!.signal!.reason), {once: true});
      });
    };
    return response;
  });
  const request = episode.fetch(upstream, '/body-pending', {signal: caller.signal});
  const rejected = expect(request).rejects.toThrow('caller cancelled');
  await reading.promise;
  expect(episode.pendingPaths).toEqual(['/body-pending']);
  caller.abort(new Error('caller cancelled'));
  await rejected;
  await episode.drain(100);
  expect(episode.pendingPaths).toEqual([]);
});

it('fails closed with owned paths when an abort-resistant transport cannot drain', async () => {
  vi.useFakeTimers();
  const episode = new ScribeLabEpisode(), headers = gate<Response>();
  const request = episode.fetch(async () => headers.promise, '/abort-resistant');
  const rejected = expect(request).rejects.toThrow('episode closed');
  episode.close();
  const drain = episode.drain(25);
  const undrained = expect(drain).rejects.toThrow('did not drain: /abort-resistant');
  await vi.advanceTimersByTimeAsync(25);
  await undrained;
  expect(() => episode.fetch(async () => new Response('new'), '/forbidden-new-work')).toThrow('episode closed');
  headers.resolve(new Response('late receipt'));
  await rejected;
  await episode.drain(25);
});

it('rejects the original run on deadline while retaining an abort-resistant body for bounded drain', async () => {
  vi.useFakeTimers();
  const episode = new ScribeLabEpisode(), headers = gate<Response>();
  let lateEffects = 0;
  const result = episode.run(async () => {
    await episode.fetch(async () => headers.promise, '/server-still-running');
    episode.check();
    lateEffects++;
  }, 20);
  const rejected = expect(result).rejects.toThrow('deadline exceeded');
  await vi.advanceTimersByTimeAsync(20);
  await rejected;
  expect(episode.pendingPaths).toEqual(['/server-still-running', 'episode body']);
  const boundedDrain = expect(episode.drain(25)).rejects.toThrow('did not drain');
  await vi.advanceTimersByTimeAsync(25);
  await boundedDrain;
  // Abort is not evidence that a server stopped; this late response must be
  // observed only by the closed original episode, without a new submission.
  headers.resolve(new Response('original server eventually settled'));
  await episode.drain(100);
  expect(lateEffects).toBe(0);
  expect(episode.pendingPaths).toEqual([]);
});

it('preserves exact successful response bytes, status, headers and final URL after full drain', async () => {
  const episode = new ScribeLabEpisode();
  const original = new Response('exact café draft', {status: 201, headers: {'X-Synthetic-Receipt': 'exact'}});
  Object.defineProperty(original, 'url', {value: 'http://127.0.0.1/original'});
  const response = await episode.fetch(async () => original, '/successful');
  expect(response.status).toBe(201);
  expect(response.headers.get('X-Synthetic-Receipt')).toBe('exact');
  expect(response.url).toBe('http://127.0.0.1/original');
  expect(await response.text()).toBe('exact café draft');
  expect(episode.pendingPaths).toEqual([]);
});

it.each([204, 205, 304])('preserves the empty body for HTTP %s', async status => {
  const episode = new ScribeLabEpisode();
  const response = await episode.fetch(async () => new Response(null, {status}), '/empty');
  expect(response.status).toBe(status);
  expect(await response.text()).toBe('');
  expect(episode.pendingPaths).toEqual([]);
});
