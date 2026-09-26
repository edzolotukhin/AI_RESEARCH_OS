"""Single-attempt acceptance HTTP client with bounded, redacted diagnostics.

Only validation fields / HTML alerts are retained, never full response pages,
request bodies, input/ctx echoes, cookies or arbitrary provider payloads.
"""
from __future__ import annotations

import json
import os
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# Preserve direct-script callers as well as package imports.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.structured_output.json_validator import JsonValidator

MAX_ERROR_BYTES = 65536
_FIELDS = {"detail", "errors", "error", "message", "msg", "type", "loc", "code"}
_SENSITIVE = re.compile(r"authorization|cookie|password|secret|token|api.?key", re.I)


class AcceptanceHttpError(RuntimeError):
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic
        super().__init__(json.dumps(diagnostic, ensure_ascii=True))


def _safe_text(value, secrets):
    text = str(value)
    for secret in sorted(set(secrets), key=len, reverse=True):
        if len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    # Provider previews / request dumps are not validation diagnostics.
    text = re.split(r"(?i)(?:preview|prompt|payload|response_body|input)\s*[=:]", text, maxsplit=1)[0]
    text = re.sub(r"(?i)\b(?:Bearer|Basic)\s+[^\s,;<>]+", "[REDACTED]", text)
    text = re.sub(r"\b(?:sk-|tvly-|airos_)[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(
        r'''(?ix)["']?(?:authorization|cookie|password|secret|token|api[_-]?key)["']?\s*[:=]\s*(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;<>]+)''',
        "[REDACTED]", text,
    )
    return " ".join(text.split())[:2000]


def _structured(value, secrets, depth=0):
    if depth > 6:
        return "[OMITTED: depth]"
    if isinstance(value, dict):
        return {k: _structured(v, secrets, depth+1) for k,v in value.items() if k in _FIELDS}
    if isinstance(value, list):
        return [_structured(v, secrets, depth+1) for v in value[:30]]
    if isinstance(value, str):
        return _safe_text(value, secrets)
    return value if value is None or isinstance(value, (bool, int, float)) else None


class _Alerts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.messages = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"br", "img", "input", "meta", "link", "hr"}:
            return
        starts = ("alert" in attrs.get("class", "").split() or attrs.get("role") == "alert")
        self.stack.append((tag, starts))
        if starts:
            self.parts = []

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            _, ends = self.stack.pop()
            if ends:
                self.messages.append(" ".join(self.parts))
                self.parts = []

    def handle_data(self, data):
        if any(alert for _, alert in self.stack) and not any(tag in {"script", "style"} for tag,_ in self.stack):
            self.parts.append(data)


def error_diagnostic(error, *, endpoint, stage, secrets=()):
    record = {"http_status": error.code, "endpoint": _safe_text(urllib.parse.urlsplit(endpoint).path, secrets),
              "stage": _safe_text(stage, secrets)}
    headers = error.headers or {}
    for header in ("x-request-id", "x-correlation-id", "request-id"):
        value = headers.get(header)
        if value and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
            record[header] = _safe_text(value, secrets)
    try:
        body = error.read(MAX_ERROR_BYTES + 1)
    except OSError:
        record["body_omitted"] = "read_error"
        return record
    finally:
        error.close()
    if len(body) > MAX_ERROR_BYTES:
        record["body_omitted"] = "size_limit"
        return record
    text = body.decode("utf-8", errors="replace")
    content_type = headers.get("content-type", "").lower()
    if "json" in content_type:
        try:
            parsed = JsonValidator().validate(text)
            if parsed.is_valid:
                record["validation"] = _structured(parsed.data, secrets)
            else:
                record["body_omitted"] = "invalid_json"
        except (ValueError, RecursionError):
            record["body_omitted"] = "invalid_json"
    elif "text/html" in content_type:
        parser = _Alerts()
        parser.feed(text)
        record["validation"] = {"messages": [_safe_text(m, secrets) for m in parser.messages[:10]]}
        if not parser.messages:
            record["body_omitted"] = "no_alert"
    else:
        record["body_omitted"] = "unsupported_content_type"
    return record


def post_form(url, values, *, stage, diagnostic_path=None, timeout=240):
    """Normal form POST, no retry. Success keeps urllib's normal redirect path."""
    request = urllib.request.Request(url, data=urllib.parse.urlencode(values).encode())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.url
    except urllib.error.HTTPError as error:
        secrets = [v for k,v in os.environ.items() if _SENSITIVE.search(k)]
        secrets.extend(str(v) for k,v in values.items() if _SENSITIVE.search(k))
        with error:
            record = error_diagnostic(error, endpoint=url, stage=stage, secrets=secrets)
        encoded = json.dumps(record, ensure_ascii=True)
        print(encoded, file=sys.stderr)
        if diagnostic_path is not None:
            path = Path(diagnostic_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
        raise AcceptanceHttpError(record) from None
