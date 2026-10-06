# UX-01C — Research method workflow simplification

## Decision

UX-01C addresses the highest-friction pilot journey in the Qualitative method without changing research authority. Desk and Quant already expose coherent, method-specific workspaces; their graphical regression passed and no UX-01C change was justified.

The Qualitative page now derives a presentation-only current stage and one next action from persisted records. The derivation is read-only: services still own authorization, provenance, lifecycle transitions, approval, and persistence. Reloading or opening the run directly therefore reconstructs the same stage without browser history.

## Friction audit

The F1 problem was orientation: a researcher had to infer the active step from a long collection of forms. The F2 problem was action selection: prepared transcript and audio appeared equal, while routine navigation exposed technical record identifiers and required rediscovery of Review and Outputs.

The implemented shell adds:

- a current-stage card, completed-stage markers, and one derived primary action;
- stable anchors for participant, consent, session, source, analysis, conclusions, Review, and deliverables;
- a prepared DOCX/TXT transcript as the recommended pilot path;
- an explicit privacy-safe explanation that audio is available only when external transcription policy permits it;
- direct Review and canonical Project Outputs handoffs;
- collapsed technical records/exports as progressive disclosure;
- responsive stage/action layout at the accepted narrow viewport.

The existing Theme → Code → Span → Transcript Version → Source Artifact lineage remains unchanged. AI proposals remain proposals; only explicit human review creates an Approved Version. Project Outputs remains the sole deliverable authority.

## Boundaries

No research, authorization, privacy/provider, persistence, Desk Evidence, or Quant calculation semantics changed. No migration was introduced. UX-01D and OPS-01C remain deferred.
