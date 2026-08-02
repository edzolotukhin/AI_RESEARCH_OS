from __future__ import annotations

from domain.reports.report import Report


def render_report_markdown(report: Report) -> str:
    lines: list[str] = [
        f"# {report.title}",
        "",
        f"_Language: {report.language}_",
        "",
        "## Executive Summary",
        "",
        report.executive_summary.strip(),
        "",
    ]
    for section in report.sections:
        lines.extend(
            [
                f"## {section.title}",
                "",
                section.content.strip(),
                "",
            ],
        )
        if section.citation_ids:
            refs = ", ".join(f"[{item}]" for item in section.citation_ids)
            lines.extend([f"_Citations: {refs}_", ""])

    if report.limitations:
        lines.extend(["## Limitations", ""])
        for limitation in report.limitations:
            lines.append(f"- {limitation}")
        lines.append("")

    if report.citation_registry:
        lines.extend(["## References", ""])
        for citation_id in sorted(report.citation_registry):
            entry = report.citation_registry[citation_id]
            title = entry.get("title", "")
            url = entry.get("canonical_url", "")
            lines.append(f"[{citation_id}] {title} — {url}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def safe_report_filename(title: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in title.strip().lower()
    )
    safe = "-".join(part for part in safe.split("-") if part)
    return f"{safe or 'research-report'}.md"
