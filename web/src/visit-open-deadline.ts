/** A catalog visit open must finish or surface a retry before the page stays disabled. */
export class VisitOpenTimeout extends Error {
  constructor() {
    super("This visit could not be opened.");
    this.name = "VisitOpenTimeout";
  }
}

export class VisitOpenDeadline {
  static readonly limitMs = 5_000;
  private readonly endsAt = Date.now() + VisitOpenDeadline.limitMs;
  private didExpire = false;

  get expired(): boolean {
    return this.didExpire;
  }

  static expired(error: unknown): error is VisitOpenTimeout {
    return error instanceof VisitOpenTimeout;
  }

  /** Reject when this attempt's single five-second budget is spent. Later results are ignored. */
  limit<T>(work: Promise<T>): Promise<T> {
    const remaining = this.endsAt - Date.now();
    if (remaining <= 0) {
      this.didExpire = true;
      return Promise.reject(new VisitOpenTimeout());
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        this.didExpire = true;
        reject(new VisitOpenTimeout());
      }, remaining);
      const finish = (settle: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        settle();
      };
      work.then(
        value => finish(() => resolve(value)),
        error => finish(() => reject(error)),
      );
    });
  }
}
