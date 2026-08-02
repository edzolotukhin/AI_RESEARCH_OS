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
| ADR-009 | Persistence Boundary and Repository Strategy | Active |
| ADR-010 | Durable Workflow Checkpoint and Recovery Policy | Active |
| ADR-011 | HTTP API Boundary and Synchronous Execution Policy | Superseded (research async — see ADR-012) |
| ADR-012 | Background Execution, Claiming, Lease and Recovery | Active |
| ADR-013 | External Orchestration and Idempotent Submission | Active |
| ADR-014 | Authentication and Access Boundary | Active |
| ADR-015 | Desk Research Brief and Research Contract | Active (DR-01 complete) |
| ADR-016 | Desk Research Design and Semantic Planning | Active (DR-02 complete) |
| ADR-017 | Search, Source Acquisition and Provenance Boundary | Active (DR-03) |
| ADR-018 | Evidence and Provenance Boundary | Active (DR-04) |
| ADR-019 | Desk Research Analysis, Findings and Insights | Active (DR-05) |
| ADR-020 | Desk Research Report Writer and Final Artifact | Active (DR-06) |
| ADR-021 | Desk Research Review and Quality Gate | Active (DR-07) |

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