# benny

> Codex execution context: this dormant pack retains upstream Cursor automation procedures. Before setup or execution, read `adapters/codex/adapter.md` from the selected, verified pstack runtime and preserve that runtime binding in the target project. Cursor's `/automate`, Automations editor, model picker, and named integration actions below are source-host terms, not native Codex tools. A configured native or authenticated bridge/provider route must preserve the workflow's triggers, review and approval gates, thread identity, future wakes, stop behavior, cleanup, and required handoff. If no such route is available, leave the automations disabled and report the missing prerequisite. Copying this pack does not activate an automation.


benny gives you two cursor automations for slack issue reports. one triages each report. the other reproduces confirmed bugs and may prepare a small draft fix.

the files in this directory are dormant setup and automation sources. they do not appear as slash skills.

## set it up

1. point cursor at [`FOR_AGENTS.md`](./FOR_AGENTS.md) and name the target repository.
2. let setup merge this whole directory into the target at `.agents/automations/benny/`. it must preserve destination-only files and review conflicts instead of overwriting local edits.
3. use an actual supported Codex project-scoped activation route and provision the complete verified runtime for shared dependencies. preserve unrelated settings. if that route is unavailable, stop setup before enabling automation.

4. keep user-owned configuration outside the copied pack, for example in `.agents/benny/`. adapt [`configuration.example.yaml`](./templates/configuration.example.yaml) and [`feature-map.example.md`](./skills/reproduce-and-fix-issues/references/feature-map.example.md).
5. commit the verified Codex project activation/runtime binding, `.agents/automations/benny/`, and any secret-free configuration before enabling either automation.
6. review each new automation draft or update existing automations in their editors. then send a harmless test report and verify every source-channel post stays in the original thread.
