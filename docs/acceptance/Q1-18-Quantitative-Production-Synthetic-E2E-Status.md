# Q1-18 — Quantitative Production Synthetic E2E Status

## Status

**NOT ACCEPTED**

Quantitative properties **QA–QV are accepted**. The production synthetic Quantitative E2E remains open.

## Current first loss

The current Quantitative `WorkflowRun` failed before the provider boundary. Dataset replacement correctly requires the setup-gated `PAUSED` state, but a terminal failed run cannot be rearmed into that state. Consequently, the same run cannot accept the replacement dataset required to rerun QC, WeightSet approval, deterministic analysis, and the bounded semantic stages.

The failed attempt made **zero semantic calls and zero physical provider attempts**. Shared protected dataset storage (QV) is accepted and is not the blocker.

## Next milestone — QW

QW will define an explicit, auditable rearm operation for an eligible failed pre-provider Quantitative run. The recovery must preserve the same Project and WorkflowRun identity, retain the prior failure in audit history, invalidate obsolete execution authority, and return the run to setup-gated `PAUSED` for same-run dataset replacement.

QW is not a general retry mechanism for terminal failed runs. Production synthetic E2E acceptance remains pending until QW is implemented and the full path is rerun successfully.
