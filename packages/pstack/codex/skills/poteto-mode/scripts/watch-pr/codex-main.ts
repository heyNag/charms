import { main, realRuntime } from "./cli.ts";
import { chargeOutput, revisionBindings, TransportFailure, validateSnapshots } from "./codex-transport.ts";

interface RawVerdict {
  readonly kind: string;
  readonly terminal: boolean;
  readonly reason?: { readonly kind?: string } | string;
  readonly blocker?: { readonly kind?: string };
}
class MergeReady extends Error {
  constructor(readonly upstream: RawVerdict) { super("queued frontier is merge-ready"); }
}

const runtime = realRuntime();
const untilReady = process.env.PSTACK_WATCH_UNTIL_READY === "1";
let terminal: RawVerdict | null = null;
let helpDisplayed = false;
const argv = process.argv.slice(2);
const emit = (value: object): void => {
  const text = JSON.stringify({ wrapperSchemaVersion: 1, ...value }) + "\n";
  chargeOutput(Buffer.byteLength(text));
  process.stdout.write(text);
};

try {
  const code = await main(argv, {
    ...runtime,
    stdout: (text: string) => {
      if (argv.includes("--help") || argv.includes("-h")) {
        chargeOutput(Buffer.byteLength(text));
        process.stderr.write(text);
        helpDisplayed = true;
        return;
      }
      const raw = JSON.parse(text) as RawVerdict;
      if (raw.terminal) { terminal = raw; return; }
      if (untilReady && raw.kind === "WAITING" && typeof raw.reason === "object"
          && raw.reason?.kind === "merge-queue") throw new MergeReady(raw);
      emit({ outcome: "PROGRESS", complete: false, upstream: raw });
    },
  });
  const result = terminal as RawVerdict | null;
  if (result?.kind === "READY" || result?.kind === "COMPLETE") await validateSnapshots();
  if (result !== null)
    emit({ outcome: "UPSTREAM", complete: result.kind !== "TIMEOUT"
      && result.blocker?.kind !== "status-query", upstream: result,
      revisionBindings: revisionBindings() });
  else
    emit({ outcome: helpDisplayed ? "HELP" : "USAGE", complete: false, exitCode: code });
  process.exit(code);
} catch (error) {
  if (error instanceof MergeReady) {
    try {
      await validateSnapshots();
      emit({ outcome: "MERGE_READY", complete: true, upstream: error.upstream,
        revisionBindings: revisionBindings(), note: "No merge was requested or observed." });
      process.exit(0);
    } catch (failure) { error = failure; }
  }
  const failure = error instanceof TransportFailure ? error
    : new TransportFailure("EXECUTION_ERROR", error instanceof Error ? error.message : String(error), 70);
  // Emit this small control record even when the ordinary output budget is exhausted.
  process.stdout.write(JSON.stringify({ wrapperSchemaVersion: 1, outcome: failure.outcome,
    complete: false, detail: failure.message, exitCode: failure.exitCode }) + "\n");
  process.exit(failure.exitCode);
}
