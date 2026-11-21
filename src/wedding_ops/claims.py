"""Checks on the facts in model-written text (docs/plans/2026-11-22-deputy-claim-check.md).

The deputy's model writes an answer, a short title and sometimes a message. Each fact
in that text (a clock time, a table, a count, a report reference or a known name) must
appear in the text that supports it: the records in the person's context, and for
some fields the person's own words. Sentences with an unsupported fact are removed.

Report status is not checked here as a token: code states it (see Deputy._status_lines),
so sentences in which the model states the status of a report are removed instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Clock times as people and models write them: 18:40, 6.40pm, 6:40 pm, 7pm.
CLOCK = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)(?:\s*([ap])\.?m\b\.?)?", re.IGNORECASE)
HOUR_ONLY = re.compile(r"(?<![:.\d])\b(1[0-2]|0?[1-9])\s*([ap])\.?m\b\.?", re.IGNORECASE)
TABLE = re.compile(r"\btable\s+([A-Za-z]?\d+[A-Za-z]?)\b", re.IGNORECASE)
COUNT = re.compile(r"\b(\d+)\s+of\s+(\d+)\b")
REFERENCE = re.compile(r"\b([RQ]\d{1,2})\b")
QUOTED = re.compile(r"“[^”]*”")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")

# A sentence states the status of a report when it names a report and a status together.
REPORT_NOUN = re.compile(r"\b([RQ]\d{1,2}|requests?|reports?|questions?|alerts?|drafts?|notes?|nudges?)\b",
                         re.IGNORECASE)
REPORT_STATUS = re.compile(r"\b(sent|unsent|pending|approved|rejected|declined|open|answered|resolved|withdrawn|"
                           r"waiting|logged|recorded|flagged|received)\b", re.IGNORECASE)

# First-person statements of doing something only a tapped draft can do. Counted for the
# gate, not enforced: code writes every outcome sentence, so these show prompt drift.
SELF_ACT = re.compile(
    r"\b(I'll|I will|I'm|I am|I've|I have|I just|let me)\s+(?:\w+\s+){0,2}?"
    r"(flag|ask|tell|send|sent|message|notify|nudg|pass|forward|escalat|report|log|record|updat|remind|chas|"
    r"contact|call|cancel|withdr|arrang|let)\w*", re.IGNORECASE)

STOPWORDS = {"the", "and", "for", "mr", "mrs", "ms", "mdm", "auntie", "aunty", "uncle", "table", "guest", "seat",
             "where", "what", "who", "his", "her", "she", "him", "ah", "lah", "leh"}


def clock_forms(hour: int, minute: int, half: str | None) -> set[str]:
    """Every 24-hour reading of a clock time. Without am or pm, an hour under 12 may be either."""
    if half:
        hour = hour % 12 + (12 if half.lower() == "p" else 0)
        return {f"{hour:02d}:{minute:02d}"}
    forms = {f"{hour:02d}:{minute:02d}"}
    if hour < 12:
        forms.add(f"{hour + 12:02d}:{minute:02d}")
    return forms


@dataclass(frozen=True)
class Fact:
    shown: str             # as written, for logs
    forms: frozenset[str]  # normalised forms; one of them must be in the support


def facts(text: str, names: set[str]) -> list[Fact]:
    """The checkable facts in a text. Names come from the wedding's own vocabulary."""
    found: list[Fact] = []
    for match in CLOCK.finditer(text):
        forms = clock_forms(int(match[1]), int(match[2]), match[3])
        found.append(Fact(match[0], frozenset(f"time:{form}" for form in forms)))
    for match in HOUR_ONLY.finditer(text):
        forms = clock_forms(int(match[1]), 0, match[2])
        found.append(Fact(match[0], frozenset(f"time:{form}" for form in forms)))
    found += [Fact(m[0], frozenset({f"table:{m[1].casefold()}"})) for m in TABLE.finditer(text)]
    found += [Fact(m[0], frozenset({f"count:{m[1]}/{m[2]}"})) for m in COUNT.finditer(text)]
    found += [Fact(m[0], frozenset({f"ref:{m[1]}"})) for m in REFERENCE.finditer(text)]
    lowered = text.casefold()
    for name in names:
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", lowered):
            found.append(Fact(name, frozenset({f"name:{name}"})))
    return found


class Support:
    """The normalised facts that a text may state."""

    def __init__(self, text: str, names: set[str], references: set[str] = frozenset(), *,
                 extra_names: str = ""):
        self.forms: set[str] = set()
        for fact in facts(text, names):
            self.forms |= fact.forms
        self.forms |= {f"ref:{reference}" for reference in references}
        # Naming a person or place the person just mentioned is not a claim about them.
        for fact in facts(extra_names, names):
            self.forms |= {form for form in fact.forms if form.startswith("name:")}

    def missing(self, text: str, names: set[str]) -> list[str]:
        return [fact.shown for fact in facts(text, names) if not fact.forms & self.forms]


def sentences(text: str) -> list[str]:
    return [part for part in SENTENCE_END.split(text.strip()) if part.strip()]


def states_report_status(sentence: str) -> bool:
    return bool(REPORT_NOUN.search(sentence) and REPORT_STATUS.search(sentence))


@dataclass
class Checked:
    text: str
    removed: list[str]           # sentences with a fact that no record supports
    status: list[str]            # sentences stating a report's status, which code states instead
    status_references: set[str]  # references named in those status sentences


def check_answer(text: str, support: Support, names: set[str]) -> Checked:
    """Keep the sentences whose facts are supported and that do not state report status."""
    kept, removed, status, references = [], [], [], set()
    for sentence in sentences(text):
        if states_report_status(sentence):
            status.append(sentence)
            references |= set(REFERENCE.findall(sentence))
        elif support.missing(sentence, names):
            removed.append(sentence)
        else:
            kept.append(sentence)
    return Checked(" ".join(kept), removed, status, references)


def without_quotes(text: str) -> str:
    """Text with quoted spans removed: quotes hold people's own words, which are not records."""
    return QUOTED.sub("“”", text)


def self_acts(text: str) -> int:
    return len(SELF_ACT.findall(text))


def from_their_words(argument: str, words: str) -> bool:
    """A name the model passes on (a lookup, an arrival) must share a word with what the person wrote."""
    theirs = {w for w in re.findall(r"[a-z]+", words.casefold()) if len(w) > 2 and w not in STOPWORDS}
    mine = {w for w in re.findall(r"[a-z]+", argument.casefold()) if len(w) > 2 and w not in STOPWORDS}
    return bool(mine & theirs) or not mine
