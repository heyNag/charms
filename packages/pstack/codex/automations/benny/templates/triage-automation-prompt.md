# Triage automation prompt

> Codex execution context: this dormant pack retains upstream Cursor automation procedures. Before setup or execution, read `adapters/codex/adapter.md` from the selected, verified pstack runtime and preserve that runtime binding in the target project. Cursor's `/automate`, Automations editor, model picker, and named integration actions below are source-host terms, not native Codex tools. A configured native or authenticated bridge/provider route must preserve the workflow's triggers, review and approval gates, thread identity, future wakes, stop behavior, cleanup, and required handoff. If no such route is available, leave the automations disabled and report the missing prerequisite. Copying this pack does not activate an automation.


> Source material for the copied setup workflow. Paraphrase this intent into a built-in `automate` draft after `automate` confirms that the copied pack is committed in the repository where the automation will run.

Read and follow `.agents/automations/benny/skills/triage-issue-reports/instructions.md` for this run.

Configuration source. Include this repository-relative path only when it is committed in the same target repository. Otherwise paraphrase the configured values. Never use a plugin source or cache path:

```text
{{BENNY_CONFIG_PATH}}
```

Trigger:

```json
{
	"source_channel_id": "{{SLACK_CHANNEL_ID}}",
	"ts": "{{SLACK_MESSAGE_TS}}",
	"thread_ts": "{{SLACK_THREAD_TS_OR_EMPTY}}"
}
```

The creation intent should describe this as a new top-level report in the configured source Slack channel.

Treat the source channel and root thread timestamp as immutable. If either is missing or does not match configuration, stop without posting or writing to the issue tracker.

The committed operational file owns classification, attachment review, cause tracing, routing, dedupe, tracker writes, and the final verdict. Post no progress messages. Never post a root message in the source channel.

The coordinator is the only Slack poster. Any delegated worker must be read-only, return findings only, and receive an explicit ban on every Slack write action.

End the single verdict with exactly one configured marker:

```text
[benny:bug]
[benny:performance]
[benny:other]
```

A bug or performance marker may add `tracker=<URL>`.
