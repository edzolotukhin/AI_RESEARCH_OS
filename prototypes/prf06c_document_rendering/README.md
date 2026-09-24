# PRF-06C/D isolated document prototype

Synthetic technology qualification only. This directory does not implement
application export, read the research database, or alter production manifests.
Inputs are invented in `fixtures.py`. Output, previews, local dependencies,
virtual environments, and run directories are ignored by Git and excluded
from the Docker build context. See `RESULTS.md` for evidence and limitations.

## Windows reproduction

Verified here with Python 3.12.14, ReportLab 4.4.9, pypdf 6.10.0, bundled
Node 24.19.0 and `@oai/artifact-tool` 2.8.59. The Node package is proprietary,
internal-evaluation-only, and **not a production dependency**. It and the
presentation finalizer come from the desktop development runtime.

From this directory in PowerShell, use a new lowercase run name each time;
the PPTX finalizer refuses to overwrite an existing final file:

```powershell
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$env:SKILL_DIR = Join-Path $env:USERPROFILE '.codex\plugins\cache\openai-primary-runtime\presentations\26.909.12148\skills\presentations'
$env:RUNTIME_NODE_MODULES = "$runtime\node\node_modules"
$env:RUNTIME_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$env:PRF06C_FONT_PATH = "$runtime\native\poppler\Library\share\fonts\DejaVuSans.ttf"
$env:PRF06C_RUN_NAME = 'my-new-run'
& $env:RUNTIME_PYTHON prototype.py
& "$runtime\node\bin\node.exe" build_decks.mjs
& "$runtime\node\bin\node.exe" preview_saved.mjs
& $env:RUNTIME_PYTHON validate.py
```

Initial setup, only if local bundled runtime is present and these paths do
not already exist:

```powershell
$runtime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
New-Item -ItemType Junction -Path '.\node_modules' -Target "$runtime\node\node_modules"
& "$runtime\python\python.exe" -m venv --system-site-packages .venv
```

The junction and virtual environment are local evaluation conveniences, not
deployable dependency packaging. No global installation is needed.

## Linux/Python 3.11 PDF reproduction

From the repository root in PowerShell, with Docker Desktop available:

```powershell
docker build --file prototypes/prf06c_document_rendering/Dockerfile.pdf --tag prf06d-pdf-prototype:local prototypes/prf06c_document_rendering
docker run --rm --network none --memory 256m --cpus 1 --pids-limit 64 --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m --env PRF06C_RUN_NAME=my-linux-run --mount 'type=bind,source=C:\AI_AGENTS\AI_RESEARCH_OS\prototypes\prf06c_document_rendering\runs,target=/prototype/runs' prf06d-pdf-prototype:local sh -c 'python prototype.py && python validate.py --pdf-only'
```

Use a fresh run name. Build may access package repositories; document
generation and tests have `--network none`. No credentials, databases, or
historical research directories are mounted. The Dockerfile pins the base
image digest and Python versions, but Debian apt packages and the package
index are not hash-locked. A production image needs an approved internal lock
and software-bill-of-materials review. The Linux image verifies **PDF only**;
Node/PPTX/preview were not run in Linux.

The normalized prototype object retains source IDs, report/composition
version, method, source status, ordered text, citations, limitations, and
authorized table/chart metadata. Production must resolve exact referenced
research records and never infer missing numbers. Immutable output, private
storage, downloads, and explicit presentation generation are not implemented.
