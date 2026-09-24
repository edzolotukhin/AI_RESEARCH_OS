# PRF-07B isolated document acceptance

This is a disposable, fictional-data-only local environment. It uses its own
Compose project, PostgreSQL volume, protected-data volume, and network. It does
not reuse the default `ai_research_os` deployment.

## Start

From the repository root in PowerShell:

```powershell
.\scripts\prf07b_start.ps1
```

The script generates `.env.prf07b` once, without printing its database
password or UI key. The file is Git-ignored and Docker-ignored. It builds the
current local source into `ai-research-os-prf07b:4273e291`, starts only
`ai_research_os_prf07b` PostgreSQL, migrates that database to head, creates
idempotent synthetic fixtures, and starts only its API and worker.

If port 18080 is occupied before first start, choose a free port:

```powershell
.\scripts\prf07b_start.ps1 -Port 18081
```

For the optional automated verifier on another port, set
`$env:PRF07B_BASE_URL = 'http://127.0.0.1:18081'` in that PowerShell session.

After first start, reuse the same port and `.env.prf07b`; do not regenerate
credentials against an existing acceptance volume.

## Check

```powershell
Invoke-WebRequest http://127.0.0.1:18080/health
Invoke-WebRequest http://127.0.0.1:18080/ready
docker compose --project-name ai_research_os_prf07b --env-file .env.prf07b --file docker-compose.prf07b.yml ps
```

Open `http://127.0.0.1:18080/ui/projects` in a browser. This internal UI
authenticates server-side with its dedicated local key. No browser login or
plaintext password is needed. Do not copy that key into a browser or report.

Choose “PRF-07B — Синтетична перевірка PDF/PPTX”, click
`Відкрити проєкт`, then `Переглянути результати та активність`.
In `Кабінетні звіти`, start with approved revision 1 (`Схвалено`);
revision 2 is the newer draft (`Чернетка`). The `Кількісні звіти`
section contains one `Прийнято` synthetic report.

For each selected report, use `Переглянути звіт`, then on Outputs use
`Створити PDF` and `Завантажити PDF`. Use
`Створити презентацію`, refresh Outputs while
`Презентація створюється` is shown, then `Завантажити PPTX`.
Downloads appear in the browser's configured Downloads folder. Open PPTX in
Microsoft PowerPoint when available and LibreOffice as a secondary check.
Inspect Ukrainian typography, long headings, continuation slides, citations,
limitations, source/status binding, page breaks, and clipping. Avoid putting
credentials or full document text in defect reports; note method, revision,
slide/page number, and a cropped screenshot.

The UI intentionally has no in-app slide preview. Quantitative project
deliverables do not contain unrelated standalone statistical tables/charts.
These are covered separately by renderer tests.

## Automated, non-visual verification

Only against this disposable project:

```powershell
docker compose --project-name ai_research_os_prf07b --env-file .env.prf07b --file docker-compose.prf07b.yml stop worker
python tools/prf07b_verify.py schedule
docker compose --project-name ai_research_os_prf07b --env-file .env.prf07b --file docker-compose.prf07b.yml start worker
python tools/prf07b_verify.py complete
```

The first phase exercises real UI POST forms and a visible pending state.
The second waits for the separate worker and verifies OOXML structure and
byte-identical repeated downloads. Database checksum verification is a
separate read-only query, not a replacement for visual inspection.

## Stop and restart without data loss

```powershell
docker compose --project-name ai_research_os_prf07b --env-file .env.prf07b --file docker-compose.prf07b.yml stop
docker compose --project-name ai_research_os_prf07b --env-file .env.prf07b --file docker-compose.prf07b.yml start
```

If containers need recreation, rerun `.\scripts\prf07b_start.ps1` with
the original port. The seed refuses to overwrite incomplete existing fixtures.

## Cleanup — only after explicit owner authorization

First verify that the Compose project name is exactly
`ai_research_os_prf07b` and its volumes are exactly
`ai_research_os_prf07b_postgres_data` and
`ai_research_os_prf07b_protected_data`. Then:

```powershell
docker compose --project-name ai_research_os_prf07b --env-file .env.prf07b --file docker-compose.prf07b.yml down --volumes
Remove-Item -LiteralPath .env.prf07b
```

These cleanup commands are documented, not executed during PRF-07B.
