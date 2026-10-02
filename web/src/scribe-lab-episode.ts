/** Test-only custody for one mounted Scribe laboratory journey. */
export class ScribeLabEpisode {
  private readonly controller = new AbortController();
  private closedReason: Error | null = null;
  private readonly work = new Map<Promise<unknown>, string>();
  private deadline: ReturnType<typeof setTimeout> | undefined;

  get closed() { return this.closedReason !== null; }
  get pendingPaths() { return [...this.work.values()]; }

  check() {
    if (this.closedReason) throw this.closedReason;
  }

  close(reason = 'Scribe lab episode closed') {
    if (this.closedReason) return;
    this.closedReason = new Error(reason);
    clearTimeout(this.deadline);
    this.controller.abort(this.closedReason);
  }

  async run<T>(body: () => Promise<T>, budgetMs: number): Promise<T> {
    this.check();
    if (!Number.isFinite(budgetMs) || budgetMs <= 0 || this.deadline) {
      throw new Error('Invalid Scribe lab episode budget');
    }
    this.deadline = setTimeout(() => this.close('Scribe lab episode deadline exceeded'), budgetMs);
    const actualBody = this.track((async () => {
      const result = await body();
      this.check();
      return result;
    })(), 'episode body');
    let removeAbort = () => {};
    const cancelled = new Promise<never>((_, reject) => {
      const abort = () => reject(this.closedReason!);
      this.controller.signal.addEventListener('abort', abort, {once: true});
      removeAbort = () => this.controller.signal.removeEventListener('abort', abort);
      if (this.closed) abort();
    });
    try {
      // Reject the test on its cooperative deadline even if native I/O ignores
      // abort. The actual body remains tracked; only drain can prove settlement.
      return await Promise.race([actualBody, cancelled]);
    } finally {
      clearTimeout(this.deadline);
      removeAbort();
    }
  }

  private track<T>(promise: Promise<T>, path: string): Promise<T> {
    this.work.set(promise, path);
    void promise.then(() => this.work.delete(promise), () => this.work.delete(promise));
    return promise;
  }

  /** Buffer through body completion; a headers-only promise cannot prove drain. */
  fetch(fetcher: typeof fetch, input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    this.check();
    const target = new AbortController();
    const signals = [this.controller.signal, ...(init?.signal ? [init.signal] : [])];
    const listeners = signals.map(signal => {
      const abort = () => target.abort(signal.reason);
      signal.addEventListener('abort', abort, {once: true});
      if (signal.aborted) abort();
      return () => signal.removeEventListener('abort', abort);
    });
    const path = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    return this.track((async () => {
      try {
        const received = await fetcher(input, {...init, signal: target.signal});
        this.check();
        const bytes = await received.arrayBuffer();
        this.check();
        const emptyStatus = [204, 205, 304].includes(received.status);
        if (emptyStatus && bytes.byteLength) throw new Error('Invalid empty-status Scribe lab response body');
        const response = new Response(emptyStatus ? null : bytes, {
          status: received.status, statusText: received.statusText, headers: received.headers,
        });
        Object.defineProperty(response, 'url', {value: received.url});
        return response;
      } finally {
        listeners.forEach(remove => remove());
      }
    })(), path);
  }

  /** Refuse to advance to another mounted episode if any owned work is unresolved. */
  async drain(budgetMs: number): Promise<void> {
    if (!Number.isFinite(budgetMs) || budgetMs <= 0) throw new Error('Invalid Scribe lab drain budget');
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        (async () => {
          while (this.work.size) await Promise.allSettled([...this.work.keys()]);
        })(),
        new Promise<never>((_, reject) => {
          timeout = setTimeout(() => reject(new Error(
            'Scribe lab owned work did not drain: ' + this.pendingPaths.join(', '),
          )), budgetMs);
        }),
      ]);
    } finally {
      clearTimeout(timeout);
    }
  }
}
