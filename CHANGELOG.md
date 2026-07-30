# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project does not yet follow semantic versioning. Changes are grouped under **Unreleased** until a version policy is adopted.

## [Unreleased]

### Added

- Deterministic offline research workflow demo (`examples/deterministic_research_demo.py`)
- Packaging contract: runtime dependencies in `requirements.txt` (`openai`, `python-dotenv`)
- Python support contract in `pyproject.toml` (`>=3.11,<3.15`)
- Environment template (`.env.example`) for `OPENAI_API_KEY`
- Subprocess tests for the offline demo
- Examples README describing the offline demo path
- Proprietary license ([LICENSE](LICENSE)) — All Rights Reserved
- Repository legal posture clarified (source available, not open source)

### Changed

- Planner dependency graph validation moved inside structured-output retry boundary (`PlannerPayloadContract`)
- Agency initialization contract hardened — lazy initialization on `start_research()`
- Runtime failure finalization hardened — `WorkflowRun` reaches terminal state after executor failure
- `ROADMAP.md` synchronized with completed Phase B hardening and GF-00 progress

### Removed

- Tracked runtime project artifacts under `agency/projects/` from the current tree
- Stale legacy examples (`workflow_dsl.py`, `brand_health_demo.py`)
- Generated repository tree dump (`strukture.txt`)

### Security / Repository Hygiene

- Runtime project JSON snapshots removed from the current branch tip; `.gitignore` hardened to prevent re-tracking
- Git history may still contain previously committed runtime snapshots; a history rewrite has **not** been performed

---

## Historical Notes

Early development used sprint-based working logs. Key milestones before Phase A stabilization:

- **ProjectBrief** domain model and readiness validation (sandbox path)
- **ResearchDesigner** GPT integration with prompt templates and JSON parsing
- Transition from ad-hoc services to domain-driven workflow runtime (Phase A)

For internal task tracking see [docs/backlog.md](docs/backlog.md). For direction see [ROADMAP.md](ROADMAP.md).
