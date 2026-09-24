"""HTTP-level acceptance verification for the disposable PRF-07B UI only."""

from __future__ import annotations

import hashlib
import io
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html import unescape

BASE = os.environ.get("PRF07B_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
_base_url = urllib.parse.urlsplit(BASE)
if _base_url.scheme != "http" or _base_url.hostname != "127.0.0.1" or _base_url.port in (None, 8000):
    raise RuntimeError("PRF-07B verifier requires an explicit loopback acceptance port")
PROJECT = "prf07b-synthetic-acceptance"
SOURCES = (("DESK", "prf07b-desk-revision-1"), ("QUANTITATIVE", "prf07b-quant-accepted"))
OUTPUTS = f"/ui/projects/{PROJECT}/outputs"


def request(path: str, *, data: bytes | None = None) -> tuple[int, bytes]:
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Refusing non-local request")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Origin": BASE} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def html(path: str) -> str:
    status, body = request(path)
    if status != 200:
        raise AssertionError(f"{path}: HTTP {status}")
    return body.decode("utf-8")


def form_token(page: str, action: str) -> str:
    pattern = r'<form[^>]+action="' + re.escape(action) + r'"[^>]*>(.*?)</form>'
    match = re.search(pattern, page, re.S)
    if match is None:
        raise AssertionError(f"Action not visible: {action}")
    token = re.search(r'name="csrf_token" value="([^"]+)"', match.group(1))
    if token is None:
        raise AssertionError(f"Action lacks CSRF token: {action}")
    return unescape(token.group(1))


def download_link(page: str, action: str) -> str:
    match = re.search(r'href="(' + re.escape(action) + r'/[^"]+)"', page)
    if match is None:
        raise AssertionError(f"Download link absent for {action}")
    return unescape(match.group(1))


def post_form(page: str, action: str) -> None:
    token = form_token(page, action)
    status, _ = request(action, data=urllib.parse.urlencode(
        {"csrf_token": token}
    ).encode("ascii"))
    if status != 200:
        raise AssertionError(f"POST {action}: final HTTP {status}")


def verify_pdf(method: str, source: str) -> None:
    action = f"/ui/projects/{PROJECT}/reports/{method}/{source}/pdf"
    page = html(OUTPUTS)
    if f'href="{action}/' not in page:
        post_form(page, action)
    link = download_link(html(OUTPUTS), action)
    status, first = request(link)
    second_status, second = request(link)
    if status != 200 or second_status != 200:
        raise AssertionError(f"{method} PDF download failed")
    if not first.startswith(b"%PDF-") or b"%%EOF" not in first[-1024:]:
        raise AssertionError(f"{method} PDF structure invalid")
    if len(first) < 500 or first != second:
        raise AssertionError(f"{method} PDF empty or repeat differs")
    print(f"{method} PDF: passed, bytes={len(first)}, repeated_sha256={hashlib.sha256(first).hexdigest()[:12]}")


def schedule() -> None:
    if "PRF-07B" not in html("/ui/projects"):
        raise AssertionError("Project absent from owner list")
    if "Переглянути результати та активність" not in html(f"/ui/projects/{PROJECT}"):
        raise AssertionError("Project navigation absent")
    page = html(OUTPUTS)
    for label in ("Кабінетні звіти", "Кількісні звіти", "Редакція 2",
                  "Чернетка", "Схвалено", "Прийнято", "Переглянути звіт"):
        if label not in page:
            raise AssertionError(f"Outputs label absent: {label}")
    for method, source in SOURCES:
        detail = html(f"/ui/projects/{PROJECT}/reports/{method}/{source}")
        if source not in detail:
            raise AssertionError(f"Source identity absent: {method}")
        verify_pdf(method, source)
        action = f"/ui/projects/{PROJECT}/reports/{method}/{source}/pptx"
        page = html(OUTPUTS)
        if f'href="{action}/' not in page:
            post_form(page, action)
            if "Презентація створюється" not in html(OUTPUTS):
                raise AssertionError(f"{method} pending state absent")
            print(f"{method} PPTX durable request: passed, pending UI visible")
        else:
            print(f"{method} PPTX: already completed; pending transition not retested")
    if request(f"/ui/projects/{PROJECT}/reports/DESK/{SOURCES[0][1]}/pptx/unknown")[0] != 404:
        raise AssertionError("Unknown artifact not hidden")
    if request("/ui/projects/foreign-project/outputs")[0] != 404:
        raise AssertionError("Foreign project not hidden")
    print("Owner navigation and unknown-resource checks: passed")


def complete() -> None:
    for method, source in SOURCES:
        action = f"/ui/projects/{PROJECT}/reports/{method}/{source}/pptx"
        for _ in range(40):
            page = html(OUTPUTS)
            if f'href="{action}/' in page:
                break
            if "Презентацію не вдалося створити" in page:
                raise AssertionError(f"{method} PPTX job failed")
            time.sleep(2)
        else:
            raise AssertionError(f"{method} PPTX job stayed pending")
        if "Попередній перегляд недоступний" not in page:
            raise AssertionError("Preview state absent")
        link = download_link(page, action)
        status, first = request(link)
        repeated_status, second = request(link)
        if status != 200 or repeated_status != 200 or first != second:
            raise AssertionError(f"{method} PPTX repeated download mismatch")
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            names = archive.namelist()
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                raise AssertionError(f"{method} OOXML structure incomplete")
            slides = [name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
            if not slides:
                raise AssertionError(f"{method} PPTX has no slides")
            text = b" ".join(archive.read(name) for name in slides)
            if source.encode() not in text:
                raise AssertionError(f"{method} source ID absent from slides")
            expected_status = "Схвалено" if method == "DESK" else "Прийнято"
            if expected_status.encode() not in text:
                raise AssertionError(f"{method} status snapshot absent from slides")
        print(f"{method} PPTX: passed, slides={len(slides)}, bytes={len(first)}, repeated_sha256={hashlib.sha256(first).hexdigest()[:12]}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"schedule", "complete"}:
        raise SystemExit("Usage: python tools/prf07b_verify.py schedule|complete")
    (schedule if sys.argv[1] == "schedule" else complete)()
