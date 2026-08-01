# AI Research OS Documentation

## Architecture

Start here:

- [architecture.md](architecture.md) — documentation index
- [../architecture/overview.md](../architecture/overview.md) — layers and runtime flow
- [adr/README.md](adr/README.md) — Architecture Decision Records

## Development

- [development_rules.md](development_rules.md) — coding and layer boundaries

## Other

- [backlog.md](backlog.md)
- [changelog.md](changelog.md)
- [../ROADMAP.md](../ROADMAP.md)

---

## Documentation reality rules

**Authoritative sources (in order):**

1. Source code and Alembic migrations
2. Automated tests (especially integration tests)
3. Accepted ADRs (`docs/adr/`, status **Active**)
4. README and ROADMAP (must follow merges)

**Rules:**

1. When a capability merges to `main`, update ROADMAP and backlog in the same or next documentation pass.
2. ADRs own architectural decisions; README describes current developer/operator reality.
3. Backlog contains **future** work only — move completed items out of “Next”.
4. Do not leave “planned only” language after implementation (except historical ADR context).
5. Prefer **500+ automated tests** in prose; cite exact counts in one verification section only.
6. Do not claim product completeness because infrastructure placeholders exist (artifact metadata ≠ full lifecycle; auth ≠ identity platform; Compose ≠ production deployment).
