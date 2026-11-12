from dataclasses import dataclass, field
from application.sources.url_canonicalizer import canonicalize_url


class NavigationLimit(ValueError):
    pass


@dataclass
class NavigationBudget:
    max_requests: int = 12
    max_bytes: int = 2_048_000
    max_links: int = 25
    requests: int = 0
    received_bytes: int = 0
    considered_links: int = 0
    visited: set = field(default_factory=set)
    events: list = field(default_factory=list)
    stop_reason: str = ""

    def request(self, url):
        normalized = canonicalize_url(url)
        if normalized in self.visited:
            raise NavigationLimit("url_already_visited")
        if self.requests >= self.max_requests:
            raise NavigationLimit("request_budget_exhausted")
        if self.received_bytes >= self.max_bytes:
            raise NavigationLimit("byte_budget_exhausted")
        self.requests += 1
        self.visited.add(normalized)

    def receive(self, size):
        if self.received_bytes + size > self.max_bytes:
            self.stop_reason = "byte_budget_exhausted"
            raise NavigationLimit(self.stop_reason)
        self.received_bytes += size

    def event(self, **values):
        if len(self.events) < 16:
            self.events.append({k: v[:200] if isinstance(v, str) else v for k, v in values.items()})

    def diagnostics(self):
        return {"requests": self.requests, "received_bytes": self.received_bytes,
                "considered_links": self.considered_links,
                "max_requests": self.max_requests, "max_bytes": self.max_bytes,
                "max_links": self.max_links, "events": self.events,
                "stop_reason": self.stop_reason}
