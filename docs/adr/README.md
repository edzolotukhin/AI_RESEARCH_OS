# Architecture Decision Records (ADR)

## Purpose

Architecture Decision Records (ADRs) document the significant architectural decisions made during the development of AI Research OS.

Each ADR explains:

- the context of the decision;
- the decision itself;
- the consequences of adopting that decision.

The goal is to preserve architectural knowledge, improve consistency, and make future evolution of the platform transparent.

---

# ADR Lifecycle

Every architectural decision follows the same lifecycle:
Idea
   │
   ▼
Discussion
   │
   ▼
Proposed ADR
   │
   ▼
Review
   │
   ▼
Active ADR
   │
   ▼
Implementation

If an architectural decision changes in the future, the original ADR is never modified. Instead, a new ADR supersedes the previous one.

---

# ADR Status

The following statuses are used throughout the project.

| Status | Description |
|----------|-------------|
| Proposed | The ADR is under discussion. |
| Active | The ADR has been accepted and is currently in force. |
| Superseded | The ADR has been replaced by a newer decision. |
| Deprecated | The ADR is no longer recommended but may still exist for compatibility reasons. |

---

# ADR Index

| ADR | Title | Status |
|------|-------|--------|
| ADR-000 | Architecture Principles | Active |
| ADR-001 | Project Model | Planned |
| ADR-002 | Workflow Architecture | Planned |
| ADR-003 | Task Architecture | Planned |
| ADR-004 | Workflow Ownership | Planned |
| ADR-005 | Knowledge Model | Planned |
| ADR-006 | Artifact Model | Planned |
| ADR-007 | Agent Architecture | Planned |
| ADR-008 | Executor Catalog Contract | Active |

Additional ADRs will be added as the architecture evolves.

---

# ADR Naming Convention

Each ADR follows the naming convention:

ADR-XXX-Short-Title.md

Examples:

ADR-000-Architecture-Principles.md

ADR-001-Project-Model.md

ADR-002-Workflow-Architecture.md

---

# ADR Template

Every ADR follows the same structure.
# ADR-XXX: Title

Status:
Date:

Context

Decision

Consequences

Related ADRs (optional)

Notes (optional)

---

# Guiding Principles

Architecture decisions should:

- solve a single architectural problem;
- be concise and focused;
- explain why a decision was made rather than how it is implemented;
- remain immutable after acceptance.

Implementation details belong to the source code or technical documentation, not to ADRs.