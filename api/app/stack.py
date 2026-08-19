"""Scoring a posting's description against the stack actually worked in.

The title says what a role is called. The description says what it is built with and how much
experience it wants, and those are the two questions that decide whether applying is worth the
time. Both are answered here, from text alone, for free.

A match is expressed as *the share of the technologies a posting names that are already known*.
That direction matters. Scoring the other way round — how much of the known stack the posting
mentions — rewards long postings for listing everything and says nothing about whether the job
is a fit. Measuring the posting's own demands means a role wanting Python, FastAPI and MongoDB
scores full marks, while one wanting Java, Spring and Kafka scores nothing, however many
familiar words appear elsewhere in the text.

The vocabulary therefore has to include technologies that are *not* known. A list of only the
familiar ones would find familiar words in every posting and score them all perfectly.
"""

import re

from pydantic import BaseModel

KNOWN = {
    "python": r"python",
    "typescript": r"typescript|\bts\b",
    "javascript": r"javascript|\bjs\b",
    "sql": r"\bsql\b",
    "fastapi": r"fastapi",
    "node": r"node\.?js|\bnode\b",
    "express": r"express\.?js|\bexpress\b",
    "rest": r"\brest(ful)?\b|rest api",
    "rabbitmq": r"rabbitmq",
    "microservices": r"micro[- ]?services?",
    "react": r"\breact\b",
    "redux": r"redux",
    "mongodb": r"mongo(db)?",
    "neo4j": r"neo4j|cypher",
    "postgresql": r"postgres(ql)?",
    "kubernetes": r"kubernetes|\bk8s\b",
    "helm": r"\bhelm\b",
    "argocd": r"argo\s?cd|argocd",
    "docker": r"docker",
    "ci/cd": r"ci/?cd|github actions",
    "aws": r"\baws\b|amazon web services",
    "observability": r"opentelemetry|coralogix|observability",
    "pytest": r"pytest",
    "llm": r"\bllm\b|large language model|openai|prompt engineering|\bgenai\b",
}
"""Technologies with real production experience behind them, and how each is written about.

Patterns rather than plain words because postings spell these many ways — "Node.js", "NodeJS" and
"Node", or "K8s" for Kubernetes. Short forms are anchored on word boundaries so that "ts" does not
match inside "artifacts".
"""

UNKNOWN = {
    "java": r"\bjava\b",
    "go": r"\bgolang\b|\bgo\b(?= developer| engineer| programming)",
    "c#": r"\bc#|\.net\b",
    "ruby": r"\bruby\b|rails",
    "php": r"\bphp\b",
    "rust": r"\brust\b",
    "c++": r"c\+\+",
    "scala": r"\bscala\b",
    "kotlin": r"\bkotlin\b",
    "swift": r"\bswift\b",
    "angular": r"angular",
    "vue": r"\bvue(\.js)?\b",
    "django": r"django",
    "flask": r"\bflask\b",
    "spring": r"spring boot|\bspring\b",
    "kafka": r"\bkafka\b",
    "spark": r"\bspark\b",
    "hadoop": r"hadoop",
    "airflow": r"airflow",
    "snowflake": r"snowflake",
    "databricks": r"databricks",
    "terraform": r"terraform",
    "ansible": r"ansible",
    "jenkins": r"jenkins",
    "gcp": r"\bgcp\b|google cloud",
    "azure": r"\bazure\b",
    "elasticsearch": r"elastic ?search",
    "graphql": r"graphql",
    "mysql": r"\bmysql\b",
    "cassandra": r"cassandra",
    "unity": r"\bunity\b",
    "android": r"\bandroid\b",
    "ios": r"\bios\b|swiftui",
    "embedded": r"\bembedded\b|\brtos\b",
}
"""Technologies a posting may demand that are not part of the stack.

These exist so that a score means something. Without them every posting that says "Python" once
would score 100%, no matter how much Java, Kafka and Spark surrounded it.

Deliberately unforgiving in one place: "Go" is matched only where it is followed by developer,
engineer or programming, because the bare word appears in ordinary English in every posting ever
written.
"""

YEARS = re.compile(
    r"(\d+)\s*(?:\+|-|–|to)?\s*(?:\d+)?\s*\+?\s*years?(?:\s+of)?"
    r"(?:\s+(?:relevant|professional|hands[- ]on|industry|proven))?"
    r"\s+(?:experience|exp\b)",
    re.I,
)
"""How a posting states the experience it wants.

Only the leading number is captured. A posting asking for "3-5 years" is asking for three; the
upper bound is what they hope for, and treating the range as five would discard a role that is
actually open.
"""


class TechMatch(BaseModel):
    """What one description says about its technologies and its experience bar."""

    matched: list[str]
    """Technologies the posting names that are already known, in vocabulary order."""

    missing: list[str]
    """Technologies the posting names that are not."""

    score: float | None
    """Share of named technologies that are known, or None if it names none at all.

    None is not zero. A posting that describes the work in prose without naming a single
    technology has not been judged, and treating that silence as a score of zero would discard
    roles on the strength of how they were written.
    """

    minimum_years: int | None
    """The lowest number of years the posting asks for, or None if it never says."""


def _found(vocabulary: dict[str, str], text: str) -> list[str]:
    """Returns the vocabulary entries whose pattern appears in the text."""
    return [name for name, pattern in vocabulary.items() if re.search(pattern, text, re.I)]


def minimum_years(description: str) -> int | None:
    """The least experience a posting asks for anywhere in its text.

    A description often states several requirements — three years with one technology, five with
    another. The smallest is the one that decides whether applying is plausible.

    Args:
        description: The posting body as plain text.

    Returns:
        The lowest number of years stated, or None if the posting never puts a number on it.
    """
    stated = [int(match) for match in YEARS.findall(description)]
    return min(stated) if stated else None


def tech_match(description: str) -> TechMatch:
    """Scores a description against the known stack.

    Args:
        description: The posting body as plain text.

    Returns:
        Which technologies were recognised on each side, the resulting share, and the experience
        bar if the posting states one.
    """
    matched = _found(KNOWN, description)
    missing = _found(UNKNOWN, description)
    named = len(matched) + len(missing)
    return TechMatch(
        matched=matched,
        missing=missing,
        score=len(matched) / named if named else None,
        minimum_years=minimum_years(description),
    )
