# chatgpt-pro-review

`chatgpt-pro-review` helps an agent prepare a scoped packet for ChatGPT Pro
review, then reconcile the response against local files, diffs, tests, pull
request state, and repo conventions.

Use it for:

- plan hardening
- implementation review
- PR or code-review comment resolution
- eval or reporting methodology review
- external second-pass review of another agent's work

This directory is an [Agent Plugins v1](https://agent-plugins.org/specification)
plugin root. A compatible client with Agent Skills support loads `plugin.json`
here and discovers the skill from the standard fixed location:

```text
skills/chatgpt-pro-review
```

The plugin is independently versioned. Installation and update behavior is
defined by the client loading this package.

## Privacy

Do not send private repo context, secrets, auth tokens, customer data, or
sensitive unpublished code to ChatGPT unless the user explicitly approves that
specific context. When in doubt, prepare a paste packet and ask the user before
submitting it.

## Portable package files

```text
plugin.json                                      Agent Plugins v1 manifest
LICENSE                                          MIT license terms
README.md                                        usage and safety guidance
skills/chatgpt-pro-review/SKILL.md               skill instructions
```

## Development

In a Charms source checkout, run the package tests from the repository root:

```sh
python3 -m unittest discover -s packages/chatgpt-pro-review/tests -p 'test_*.py'
```
