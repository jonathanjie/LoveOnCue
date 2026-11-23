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
DURATION = re.compile(r"\b(\d{1,3})\s*(?:min|mins|minute|minutes|minit)\b", re.IGNORECASE)
REFERENCE = re.compile(r"\b([RQ]\d{1,2})\b")
QUOTED = re.compile(r"“[^”]*”")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
# A line break after a line with no end punctuation, unless the next line is a list item.
UNFINISHED_LINE = re.compile(r"(?<![.!?\u2026:\u201d\"')\]])[ \t]*\n+[ \t]*(?![\u2022*\-\d])")

# A sentence states the status of a report when it names a report and a status together.
REPORT_NOUN = re.compile(r"\b([RQ]\d{1,2}|requests?|reports?|questions?|alerts?|drafts?|notes?|nudges?|arrivals?|"
                         r"changes?)\b",
                         re.IGNORECASE)
REPORT_STATUS = re.compile(r"\b(sent|unsent|pending|approved|rejected|declined|open|answered|resolved|withdrawn|"
                           r"waiting|logged|recorded|flagged|received)\b", re.IGNORECASE)

# The deputy answers once per message and has no outbound effect of its own: only a tapped
# draft acts. So a first-person promise about the future ("I'll ...", "let me ...") is never
# true, whatever the verb, and neither is a claim, in any mood, to do or have done something
# only a draft can do ("I'm flagging", "I've sent", "I've taken back", "I can pass it on", "want
# me to ask"): the draft under the answer says what a tap does. Code writes every outcome sentence.
# Gate v6 measured these in 15% of answers when only the prompt forbade them.
# Verbs that act on someone else or on a record. "tell you" is informing the reader, not acting.
OUTBOUND_VERBS = (r"(?:flag|ask|tell(?!\s+you)|told|send|sent|message|notif|nudg|pass|forward|escalat|report|log|"
                  r"record|updat|remind|chas|contact|call|cancel|withdr|arrang|put|let|tak|took|mark)\w*")
# Up to two words may stand between the subject and the verb ("I've just sent"), but not a
# negation: "I have no record of it" says what is missing, not what was done.
GAP = r"(?:(?!no\b|not\b|never\b)\w+\s+){0,2}?"
SELF_ACT = re.compile(
    r"\b(?:I'll|I will|I'm going to|I am going to|I'm gonna|let me)\b"
    r"|\b(?:I'm|I am|I've|I have|I just|I already)\s+" + GAP + OUTBOUND_VERBS, re.IGNORECASE)
# An offer to act ("I can pass it on", "want me to ask Alex?") is false only beside a draft or
# button, which is the offer itself; without one, "I can't send messages" style lines are honest.
OFFER = re.compile(r"\b(?:I can|I could|I would|I'd|want me to|shall I|should I)\s+" + GAP + OUTBOUND_VERBS,
                   re.IGNORECASE)

# Words that make a message a question, in English and common Singlish spellings.
QUESTION_WORDS = {"what", "wat", "where", "when", "who", "whom", "which", "why", "how", "izzit", "issit", "can i",
                  "should", "do i", "is it"}

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


# A run-sheet line keeps the time an item had before it moved: "19:10 Dinner service (moved from
# 19:00)". Live play v10: three replies said dinner was "still 19:00" after the change, and the
# old time in that parenthesis supported them. An old time is a fact only beside the new one.
MOVED = re.compile(r"(\d{1,2}:\d{2})([^\n]*?)\(moved from (\d{1,2}:\d{2})\)")
# Words that put a time in the past: "was at 19:00", "moved from 19:00", "originally 19:00".
PAST_TIME = re.compile(r"\b(?:was|were|moved from|originally|planned for|previously|earlier|instead of|used to be)\b",
                       re.IGNORECASE)
# The same in an update notice: "Dinner service 19:00 → 19:10".
ARROW = re.compile(r"(\d{1,2}:\d{2})\s*\u2192\s*(\d{1,2}:\d{2})")


class Support:
    """The normalised facts that a text may state."""

    def __init__(self, text: str, names: set[str], references: set[str] = frozenset(), *,
                 extra_names: str = "", shifts_from: str = ""):
        self.forms: set[str] = set()
        # old time form -> the current time forms that a sentence must also state to mention it
        self.superseded: dict[str, set[str]] = {}
        pairs = [(m[3], m[1]) for m in MOVED.finditer(text)] + [(m[1], m[2]) for m in ARROW.finditer(text)]
        for old, current in pairs:
            new = {form for fact in facts(current, names) for form in fact.forms}
            for fact in facts(old, names):
                for form in fact.forms:
                    self.superseded.setdefault(form, set()).update(new)
        # After a second move, an older notice's new time ("18:50 → 19:00") is old as well.
        old_times = {old for old, _ in pairs}

        def latest(match: re.Match) -> str:
            return "" if match[2] in old_times else match[2]
        for fact in facts(ARROW.sub(latest, MOVED.sub(r"\1\2", text)), names):
            self.forms |= fact.forms
        # A record's time moved by a duration the person gave ("15 min later" on 19:00) is
        # arithmetic on supported facts, so the result is supported too.
        shifts = {int(m[1]) for m in DURATION.finditer(shifts_from)}
        for form in [f for f in self.forms if f.startswith("time:")]:
            hour, minute = map(int, form[5:].split(":"))
            for shift in shifts:
                total = (hour * 60 + minute + shift) % (24 * 60)
                self.forms.add(f"time:{total // 60:02d}:{total % 60:02d}")
        self.forms |= {f"ref:{reference}" for reference in references}
        # Naming a person or place the person just mentioned is not a claim about them.
        for fact in facts(extra_names, names):
            self.forms |= {form for form in fact.forms if form.startswith("name:")}

    def missing(self, text: str, names: set[str]) -> list[str]:
        found = facts(text, names)
        stated = {form for fact in found for form in fact.forms}

        past = bool(PAST_TIME.search(text))

        def supported(fact) -> bool:
            if fact.forms & self.forms:
                return True
            # "moved from 19:00 to 19:10" and "dinner was at 19:00" are true; "dinner is still
            # 19:00" is not. An earlier time is supported beside the current one, or as the past.
            earlier = [form for form in fact.forms if form in self.superseded]
            return bool(earlier) and (past or any(self.superseded[form] & stated for form in earlier))
        return [fact.shown for fact in found if not supported(fact)]


def sentences(text: str) -> list[str]:
    return [part for part in SENTENCE_END.split(text.strip()) if part.strip()]


# A decision word used as a predicate states a status even without a report noun: "so tell the
# kitchen it's not approved" sat above a code line saying the request was pending (live play v9).
# Only decision words: "registration is open" or "he is recorded as onsite" are not statuses.
# Not "pending" (a task is pending, truly) and not "be approved" ("moving speeches needs to be
# approved" is advice): replay v10 lost a due time and a whole answer to those.
DECISION_PREDICATE = re.compile(
    r"\b(?:is|was|are|were|'s|isn't|wasn't|aren't|not|still|already|yet|now)\s+(?:not\s+|yet\s+|still\s+)?"
    r"(?:approved|rejected|declined|withdrawn|answered|unsent)\b", re.IGNORECASE)


# The status word is said of something: "was sent", "is still pending", "has been answered", or
# right after the noun ("request approved"). Replay v10: "I can't change the run sheet, and the
# approved sheet has speeches at 19:45" was removed as a status (a verb "change" and an adjective).
STATUS_SAID = re.compile(
    r"(?:\b(?:is|was|are|were|be|been|being|'s|got|has|have|still|already|now|yet|not)\s+(?:not\s+|yet\s+|still\s+|"
    r"been\s+|already\s+)?|" + REPORT_NOUN.pattern + r"\s+)" + REPORT_STATUS.pattern, re.IGNORECASE)


def states_report_status(sentence: str) -> bool:
    return bool(REPORT_NOUN.search(sentence) and STATUS_SAID.search(sentence)) or bool(
        DECISION_PREDICATE.search(sentence))


@dataclass
class Checked:
    text: str
    removed: list[str]           # sentences with a fact that no record supports
    status: list[str]            # sentences stating a report's status, which code states instead
    status_references: set[str]  # references named in those status sentences
    acts: list[str]              # first-person acts the deputy cannot do
    internal: list[str]          # sentences that name the system's own vocabulary


def check_answer(text: str, support: Support, names: set[str], internal: re.Pattern | None = None, *,
                 offered: bool = False) -> Checked:
    """Keep the sentences whose facts are supported and that do not state report status.

    `internal` matches words from the system's closed vocabulary (action and field names). A
    sentence that uses one was written about the system, not for the person, so it is removed.
    The prompt keeps these names out of its prose; this is the backstop.
    """
    kept, removed, status, references, acts, internals = [], [], [], set(), [], []
    # A line break inside a sentence is not a sentence end: live play v10 showed "I don't have a
    # seat listed for" on its own after the rest of the sentence, on the next line, was removed.
    text = UNFINISHED_LINE.sub(" ", text)
    for sentence in sentences(text):
        if internal is not None and internal.search(sentence):
            internals.append(sentence)
        elif SELF_ACT.search(sentence) or (offered and OFFER.search(sentence)):
            acts.append(sentence)
        elif states_report_status(sentence):
            status.append(sentence)
            references |= set(REFERENCE.findall(sentence))
        elif support.missing(sentence, names):
            removed.append(sentence)
        else:
            kept.append(sentence)
    return Checked(" ".join(kept), removed, status, references, acts, internals)


def without_quotes(text: str) -> str:
    """Text with quoted spans removed: quotes hold people's own words, which are not records."""
    return QUOTED.sub("“”", text)


def self_acts(text: str, *, offered: bool = False) -> int:
    return len(SELF_ACT.findall(text)) + (len(OFFER.findall(text)) if offered else 0)


def from_their_words(argument: str, words: str) -> bool:
    """A name the model passes on (a lookup, an arrival) must share a word with what the person wrote."""
    theirs = {w for w in re.findall(r"[a-z]+", words.casefold()) if len(w) > 2 and w not in STOPWORDS}
    mine = {w for w in re.findall(r"[a-z]+", argument.casefold()) if len(w) > 2 and w not in STOPWORDS}
    return bool(mine & theirs) or not mine


# A tag at the end that turns a statement into a question ("inside now right", "can anot").
QUESTION_TAGS = re.compile(r"\b(?:(?<!all )right|anot|or not|is it|izzit|issit|correct)\W*$")


def asks(text: str) -> bool:
    """The message asks something: a question mark, a question word in English or Singlish
    ("where's" counts as "where"), or a question tag at the end."""
    lowered = text.casefold().replace("\u2019", "'").strip()
    words = f" {re.sub(r"'s\b", '', re.sub(r'[^\w\s\']', ' ', lowered))} "
    return ("?" in lowered or any(f" {word} " in words for word in QUESTION_WORDS)
            or bool(QUESTION_TAGS.search(lowered)))


# Words that say a task is finished. A draft that marks a task done must rest on the person's own
# words: without "acknowledge" to choose, the model drafted "Mark your task done" for "ok got it 👍
# cedar ballroom. wait so the ceremony is inside now right" (replay v9).
DONE_WORDS = re.compile(r"\b(?:done|finish|finished|finishing|complete|completed|siap|settled|sorted|ready)\b",
                        re.IGNORECASE)


def says_done(text: str) -> bool:
    return bool(DONE_WORDS.search(text))


# Words that say the person is late. "not yet lol going there now", in answer to a check-in,
# drafted "Jamie Lim is running late" (live play v10).
LATE_WORDS = re.compile(r"\b(?:late|later|delay|delayed|stuck|jam|jammed|traffic|lambat|eta|"
                        r"(?:won't|wont|can't|cant|cannot|not) make it)\b", re.IGNORECASE)


def says_late(text: str) -> bool:
    return bool(LATE_WORDS.search(text))


# What a confirmation is made of. Acknowledging changes a record without a tap, so the set is
# closed: a message outside it keeps its Acknowledge or On it button, which is safe. "Any short
# message that asks nothing" let "help car spoil!!" acknowledge the driver's task (live play v9).
CONFIRMATION_PHRASES = re.compile(
    r"ok+|okay|okie|oki|k+|noted|note|on it|got it|gotcha|roger|received|copy|copied|sure|yes|yep|yup|ya|yeah|"
    r"can|will do|alright|all right|understood|seen|ack|acknowledged|confirm|confirmed")
# Particles and address words that may come with one ("ok can lah boss").
CONFIRMATION_FILLER = re.compile(r"lah|la|leh|ah|liao|lor|boss|sir|maam|ma'am|bro|sis|already|alr|then|thanks|"
                                 r"thank you|thx|ty|with thanks|sorry")
CONFIRMATION_EMOJI = "👍👌✅🙏✔️"


def is_confirmation(text: str) -> bool:
    """A message made only of confirmation phrases ("ok noted", "on it", a thumbs up), with at
    least one of them, that asks nothing. "thanks" alone is not one: it does not say "seen"."""
    if asks(text):
        return False
    words = re.sub(rf"[^\w\s'{CONFIRMATION_EMOJI}]", " ", text.casefold())
    words = re.sub(rf"([{CONFIRMATION_EMOJI}])", r" \1 ", words)
    remaining, confirmed = f" {' '.join(words.split())} ", False
    for pattern, counts in ((CONFIRMATION_PHRASES, True), (CONFIRMATION_FILLER, False)):
        remaining, found = re.subn(rf"(?<= )(?:{pattern.pattern})(?= )", " ", remaining)
        remaining = f" {' '.join(remaining.split())} "
        confirmed |= counts and found > 0
    emoji = sum(remaining.count(mark) for mark in CONFIRMATION_EMOJI)
    remaining = "".join(ch for ch in remaining if ch not in CONFIRMATION_EMOJI)
    return (confirmed or emoji > 0) and not remaining.strip()
