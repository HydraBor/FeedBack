"""Content-bound review provenance for CSP reference material."""
import hashlib
import json

AUDIT_VERSION = "csp-review-2026-10-09-v1"
FIELDS = ("id", "year", "track", "index", "title", "max_score", "statement", "editorial", "topic_ids", "subtasks", "time_ms", "memory_mb", "samples", "source", "editorial_source")

def fingerprint(problem):
    payload = {key: problem.get(key) for key in FIELDS}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def is_reviewed(problem):
    audit = problem.get("review_metadata") or {}
    return (problem.get("status") == "reviewed" and audit.get("status") == "passed"
        and audit.get("kind") in ("ai", "teacher") and audit.get("fingerprint") == fingerprint(problem)
        and bool(problem.get("statement", "").strip()) and bool(problem.get("editorial", "").strip())
        and bool(problem.get("topic_ids")) and bool(problem.get("editorial_source")))

def assessment(problem):
    audit = problem.get("review_metadata") or {}
    return audit.get("assessment", {}) if is_reviewed(problem) else {}
