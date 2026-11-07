# Working Agreements

Set by Paul on 2026-11-07. These apply to every task in this repository and to the Command Center work.

## Two attempts per problem

1. A problem gets at most two attempts at a fix.
2. Before proposing any plan or step list, the plan is checked at least twice (three times where the cost of being wrong is high): reproduce the problem where possible, verify each step against the current tool interface or documentation, and confirm the fix works in a real environment before handing it over.
3. If the problem still persists after the second attempt, stop. Write down why each attempt failed and what was learned, then find an alternative approach rather than a third variation of the same one.
4. Attempt records live in `docs/ATTEMPT_LOG.md`.

## What this changes in practice

- No step lists from memory for third-party dashboards; paths are verified against the vendor's current docs or a screenshot first.
- Browser-facing changes are tested in a headless browser before delivery, not after a report back.
- Each hand-over states what was verified and what was not.
