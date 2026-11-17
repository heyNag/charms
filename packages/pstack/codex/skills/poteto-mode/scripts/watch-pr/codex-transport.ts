import { spawn } from "node:child_process";
import type * as T from "./types.ts";

export class TransportFailure extends Error {
  constructor(readonly outcome: string, message: string, readonly exitCode = 75) {
    super(message);
    this.name = "TransportFailure";
  }
}

function positiveSetting(name: string, fallback: number): number {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isFinite(value) || value <= 0)
    throw new TransportFailure("INVALID_CONFIGURATION", `invalid ${name}`, 64);
  return value;
}

const expiresAt = performance.now() + positiveSetting("PSTACK_WATCH_REMAINING_MS", 900_000);
const outputLimit = positiveSetting("PSTACK_WATCH_OUTPUT_LIMIT", 8 * 1024 * 1024);
let captured = 0;

export function chargeOutput(bytes: number): void {
  captured += bytes;
  if (captured > outputLimit)
    throw new TransportFailure("OUTPUT_LIMIT", "watcher captured-output budget exhausted", 125);
}

export function remainingMilliseconds(): number {
  const remaining = expiresAt - performance.now();
  if (remaining <= 0)
    throw new TransportFailure("DEADLINE", "watcher monotonic attempt deadline expired", 124);
  return remaining;
}

export function runBounded(argv: readonly [string, ...string[]]): Promise<{
  readonly code: number; readonly stdout: string; readonly stderr: string;
}> {
  const remaining = remainingMilliseconds();
  return new Promise((resolve, reject) => {
    // Inherit the supervisor-owned process group, including every descendant.
    const child = spawn(argv[0], argv.slice(1), { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    let settled = false;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    const abort = (error: unknown): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.kill("SIGTERM");
      child.stdout.destroy();
      child.stderr.destroy();
      reject(error);
    };
    const timer = setTimeout(() => abort(new TransportFailure(
      "DEADLINE", "watcher command exceeded remaining attempt budget", 124
    )), remaining);
    child.stdout.on("data", (chunk: string) => {
      if (settled) return;
      try { chargeOutput(Buffer.byteLength(chunk)); stdout += chunk; }
      catch (error) { abort(error); }
    });
    child.stderr.on("data", (chunk: string) => {
      if (settled) return;
      try { chargeOutput(Buffer.byteLength(chunk)); stderr += chunk; }
      catch (error) { abort(error); }
    });
    child.on("error", abort);
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: code ?? -1, stdout, stderr });
    });
  });
}

export interface RevisionIdentity {
  readonly headRefOid: string | null;
  readonly baseRefOid: string | null;
  readonly headRefName: string;
  readonly baseRefName: string;
  readonly state: "OPEN" | "CLOSED" | "MERGED";
  readonly mergedAt: string | null;
}

export function parseRevisionIdentity(value: unknown): RevisionIdentity {
  if (typeof value !== "object" || value === null)
    throw new TransportFailure("SNAPSHOT_UNAVAILABLE", "missing revision identity");
  const raw = value as Record<string, unknown>;
  if (!(["OPEN", "CLOSED", "MERGED"] as unknown[]).includes(raw.state)
      || typeof raw.headRefName !== "string" || typeof raw.baseRefName !== "string"
      || !raw.headRefName || !raw.baseRefName
      || !(raw.mergedAt === null || typeof raw.mergedAt === "string"))
    throw new TransportFailure("SNAPSHOT_UNAVAILABLE", "invalid PR revision identity");
  for (const key of ["headRefOid", "baseRefOid"]) {
    const oid = raw[key];
    if (!(typeof oid === "string" && /^[0-9a-f]{40}$/.test(oid))
        && !(raw.state !== "OPEN" && oid === null))
      throw new TransportFailure("SNAPSHOT_UNAVAILABLE", `unavailable ${key}`);
  }
  return raw as unknown as RevisionIdentity;
}

interface RevisionReader {
  snapshotIdentity(context: T.PrContext): Promise<RevisionIdentity>;
}
interface Binding {
  readonly context: T.PrContext;
  readonly identity: RevisionIdentity;
  readonly reader: RevisionReader;
}
const bindings = new Map<string, Binding>();

const key = (context: T.PrContext): string =>
  JSON.stringify([context.owner, context.repo, context.number]);
const same = (left: RevisionIdentity, right: RevisionIdentity): boolean =>
  ["headRefOid", "baseRefOid", "headRefName", "baseRefName", "state", "mergedAt"]
    .every((field) => left[field as keyof RevisionIdentity] === right[field as keyof RevisionIdentity]);

export async function beginSnapshot(
  reader: T.GitHubReader, context: T.PrContext
): Promise<RevisionIdentity | null> {
  const revisionReader = reader as T.GitHubReader & Partial<RevisionReader>;
  if (revisionReader.snapshotIdentity === undefined) return null;
  return await revisionReader.snapshotIdentity(context);
}

export function checkSnapshotFacts(
  identity: RevisionIdentity | null, facts: T.PullRequestFacts
): void {
  if (identity === null) return;
  if (facts.headRefOid !== identity.headRefOid || facts.headRefName !== identity.headRefName
      || facts.baseRefName !== identity.baseRefName || facts.state !== identity.state
      || facts.mergedAt !== identity.mergedAt)
    throw new TransportFailure("STALE_SNAPSHOT", "PR changed between initial revision and facts read");
}

export async function endSnapshot(
  reader: T.GitHubReader, context: T.PrContext, identity: RevisionIdentity | null
): Promise<void> {
  if (identity === null) return;
  const revisionReader = reader as T.GitHubReader & RevisionReader;
  const current = await revisionReader.snapshotIdentity(context);
  if (!same(identity, current))
    throw new TransportFailure("STALE_SNAPSHOT", "PR head/base changed while evidence was read");
  bindings.set(key(context), { reader: revisionReader, context, identity });
}

export async function validateSnapshots(): Promise<void> {
  for (const binding of bindings.values()) {
    remainingMilliseconds();
    const current = await binding.reader.snapshotIdentity(binding.context);
    if (!same(binding.identity, current))
      throw new TransportFailure("STALE_SNAPSHOT", "PR head/base changed before watcher handoff");
  }
}

export const revisionBindings = (): readonly object[] =>
  [...bindings.values()].map(({ context, identity }) => ({ context, identity }));
