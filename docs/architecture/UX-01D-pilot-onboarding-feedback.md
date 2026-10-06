# UX-01D — Pilot onboarding and feedback

## Scope

UX-01D adds presentation-only first-use orientation, concise contextual guidance, an authenticated Help surface, and bounded explicit pilot feedback. It does not change research state, method contracts, approval semantics, Activity, or document generation.

## First-use and help

The Projects welcome panel is dismissible through browser `localStorage`; dismissal has no server or research effect. Essential guidance remains available on direct project and method URLs. Help and feedback are secondary navigation entries. VIEWER receives an explicit read-only explanation.

## Feedback boundary

`application.pilot_feedback` validates a four-value category, normalizes whitespace, bounds messages to 20–2000 characters, rejects common secret/connection-string shapes, and restricts context to a safe `/ui/` route plus an authorized project identifier and membership role. Identity and timestamp come from the authenticated request. No DOM, screenshot, dataset row, transcript, audio, evidence text, participant metadata, provider payload, or attachment is collected.

The temporary pilot sink is the existing structured operational log under `ai_research_os.pilot_feedback`. This avoids migration 024 and does not misuse research Activity. It intentionally provides no ticket workflow or normal-user read surface. Operational log retention/access policy applies. Sink failure is explicit and preserves typed text for retry.

## Security and accessibility

Existing browser-session and same-origin POST enforcement apply. Forged project context is rejected. Templates escape plain text. Essential instructions are readable text; controls are labelled and keyboard reachable. The welcome panel is non-modal and never blocks work.
