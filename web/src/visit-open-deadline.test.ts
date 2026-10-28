import {afterEach, describe, expect, it, vi} from "vitest";
import {VisitOpenDeadline, VisitOpenTimeout} from "./visit-open-deadline";

describe("visit open deadline", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("returns a visit that opens inside the budget", async () => {
    const deadline = new VisitOpenDeadline();
    await expect(deadline.limit(Promise.resolve("invented-visit"))).resolves.toBe("invented-visit");
    expect(deadline.expired).toBe(false);
  });

  it("passes a failed open through without treating it as a timeout", async () => {
    const deadline = new VisitOpenDeadline();
    await expect(deadline.limit(Promise.reject(new Error("saved visit missing")))).rejects.toThrow("saved visit missing");
    expect(deadline.expired).toBe(false);
    expect(VisitOpenDeadline.expired(new Error("saved visit missing"))).toBe(false);
  });

  it("rejects once at five seconds and ignores a late result", async () => {
    vi.useFakeTimers();
    const deadline = new VisitOpenDeadline();
    let finish!: (value: string) => void;
    const work = new Promise<string>(resolve => { finish = resolve; });
    const limited = deadline.limit(work);
    const rejected = expect(limited).rejects.toBeInstanceOf(VisitOpenTimeout);
    await vi.advanceTimersByTimeAsync(VisitOpenDeadline.limitMs - 1);
    expect(deadline.expired).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    expect(deadline.expired).toBe(true);
    expect(VisitOpenDeadline.expired(await limited.catch(error => error))).toBe(true);
    finish("late visit");
    await expect(work).resolves.toBe("late visit");
  });

  it("spends one budget across the open and the follow-up read", async () => {
    vi.useFakeTimers();
    const deadline = new VisitOpenDeadline();
    let finish!: (value: string) => void;
    const opened = deadline.limit(new Promise<string>(resolve => { finish = resolve; }));
    await vi.advanceTimersByTimeAsync(4_000);
    finish("invented-visit");
    await expect(opened).resolves.toBe("invented-visit");
    const recovery = deadline.limit(new Promise(() => {}));
    const rejected = expect(recovery).rejects.toBeInstanceOf(VisitOpenTimeout);
    await vi.advanceTimersByTimeAsync(999);
    expect(deadline.expired).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    expect(deadline.expired).toBe(true);
  });
});
