# Daily Financial Health Brief

The implemented [daily-financial-health-brief skill](daily-financial-health-brief/SKILL.md) freshly reads the three view-only Google Sheets and produces normalized CSVs plus a traceable draft for the Operations Owner. Python 3.10+ on Linux, macOS or WSL is the only runtime dependency.

Open the skill's operator instructions for the complete end-to-end command. The current [deliverables/report.md](deliverables/report.md) uses an explicit provisional mode, following the user's instruction to proceed with available evidence. Ledger completeness remains unconfirmed: totals describe fetched records only and ledger materiality conclusions are withheld. This is a documented exception to interview-7's completeness prerequisite. Normal mode still requires Operations' matching completeness context. Negative-baseline percentages and materiality remain unresolved; signed differences are preserved. This workflow performs no source-system writes or financial actions.

Run behavioral verification from the repository root with `python3 -B -m unittest discover -s daily-financial-health-brief/tests -v`.

## Original assignment and submission instructions

Build a reusable Skill that prepares a source-traceable financial brief for human review.

## Start

1. Read the [formal assignment](https://private-pecorino-70e.notion.site/Project-A-Daily-Financial-Health-and-Budget-Brief-Learner-assignment-3da0b700541e8137ab79f8cb26d1a827?source=copy_link) for the work and acceptance requirements.
2. Create your own repository from [this starter](https://github.com/GitRollTraining/financial-health-brief) using **Fork**, then clone your copy and work there.

## Supplied files

| File | Purpose |
|---|---|
| `README.md` | Starting instructions and links. |

Create the Skill, implementation and outputs described in the formal assignment. This starter supplies no business workflow implementation.

## Before you work

**Interview rule.** You conduct the stakeholder interview yourself, and the questions are yours. Do not connect a coding agent or any other AI to the interview to run, script, or automate it. The interview transcript is assessed together with the code; a project whose interview was run by an agent is not scored.

- Export your interview as the original Work Sim Markdown, save one final complete file per session under `interviews/`, and commit and push it with your code. Do not rewrite the export. If the export is unavailable, contact the facilitator.

- Use an Agent Skills-capable coding environment. Choose and document your implementation runtime and dependencies; no runtime or install command is supplied here.
- Follow the [shared course guide for session capture](https://classroom.google.com/c/ODcyMjA4NTkwNDk2/m/ODc0NzI2NzQzMzQ2/details) and verify capture is active before implementation. Keep credentials out of the repository.
- Meet the [stakeholder](https://work-sim.catalyte.ai/s/interview-r62mbg) to understand the work and relevant business sources. Read those online sources through their intended access route; an unavailable source is not permission to substitute repository data.
