## What changes for someone using the plugin

<!-- One or two sentences, from their side of the tool. -->

## Changelog

<!--
Add the entry to CHANGELOG.md under "## [Unreleased]" and paste it here.
CI fails without it. If nothing users would notice changed — refactor, tests,
internal docs — label this pull request `no-changelog` instead and say why.
-->

## Consent and data

<!-- Delete this section if the change touches neither. -->

- [ ] No tool gained the ability to write or delete with less consent than before
- [ ] Destructive operations still ask through `guard.consent`
- [ ] Tests do not touch the real Things database, `~/.config`, or the app

## How it was verified

<!--
`uv run pytest` is the floor. Anything touching how Things actually behaves —
the URL scheme, AppleScript, the sqlite schema — needs `scripts/smoke.sh` or a
described live check, because the documentation has been wrong about this app
more than once.
-->
