"""A Jev client that cannot fail quietly.

THE REASON THIS EXISTS.

I published a claim that the model "does not discriminate", on the strength of four
requests and a control that agreed with me. Both were malformed. The request used
`state` as an object and invented an `options` field; the control shared the same call
path as the probes, so it confirmed the fault rather than auditing it.

**A malformed request does not raise. It returns a well-formed, confidently unhelpful
answer.** That is the single most dangerous property of this API and it is why every
call in this library is checked before it is made and measured after it returns.

Three guarantees:

  1. `preflight()` refuses to send a request that does not match the documented shape.
     A library that cannot send a malformed request cannot produce a malformed finding.
  2. Answers are scored, never string-matched out of prose. A reply that does not carry a
     parseable verdict is `None`, and a `None` is a FAILURE -- not a low score.
  3. Every call is journalled, so a claim can be re-checked against the exact request
     that produced it.

THE CONTRACT, which is the whole thing:

    POST https://api.typesafe.ai/v1/systemone
    {"model": "jev-1.13.0",
     "state": "<a STRING>",
     "questions": {"<qid>": {"type": "choice",
                             "instructions": "<the question>",
                             "criteria": {"<label>": "<what the label MEANS>"}}}}

There is no `options` field. The option set IS the keys of `criteria`.
"""
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable

BASE = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"
TYPES = ("choice", "noul", "score")


class MalformedRequest(ValueError):
    """Raised BEFORE a request leaves the process. The point is that this is cheap."""


class MissingVerdict(RuntimeError):
    """The model answered, but the answer carries no parseable verdict.

    This is a FAILURE, not a low score. Collapsing the two is how a broken control
    reports agreement with a broken thing.
    """


@dataclass
class Answer:
    qid: str
    kind: str
    verdict: str | None
    probability: float
    distribution: dict
    confidence: float | None
    ok: bool
    note: str = ""


@dataclass
class Journal:
    """Every request and every response, so any published number can be re-checked."""
    entries: list = field(default_factory=list)

    def add(self, request: dict, response: dict, answers: list, elapsed: float):
        self.entries.append({
            "request": request, "response": response,
            "answers": [a.__dict__ for a in answers], "elapsed_s": round(elapsed, 3),
        })

    def failures(self) -> list:
        return [e for e in self.entries if any(not a["ok"] for a in e["answers"])]

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh, indent=1)


def preflight(body: dict) -> None:
    """Refuse to send anything that does not match the documented contract.

    This is the function that would have prevented the retraction.
    """
    if not isinstance(body.get("state"), str):
        raise MalformedRequest(
            "`state` must be a STRING. Sending a dict or a list does not error -- the "
            "model reads what it can and answers confidently about the rest, which looks "
            "exactly like a finding about the model.")
    q = body.get("questions")
    if not isinstance(q, dict) or not q:
        raise MalformedRequest("`questions` must be a non-empty object of qid -> spec.")
    for qid, spec in q.items():
        t = spec.get("type")
        if t not in TYPES:
            raise MalformedRequest(f"question {qid!r}: type must be one of {TYPES}, got {t!r}")
        if "options" in spec:
            raise MalformedRequest(
                f"question {qid!r}: there is NO `options` field. The option set IS the "
                f"keys of `criteria`. Sending both confuses the model and it hedges.")
        if t == "choice":
            cr = spec.get("criteria")
            if not isinstance(cr, dict) or len(cr) < 2:
                raise MalformedRequest(
                    f"question {qid!r}: a choice needs `criteria` with at least two "
                    f"label -> meaning entries.")
            if not isinstance(spec.get("instructions"), str):
                raise MalformedRequest(f"question {qid!r}: `instructions` must be a string.")
        if t == "noul" and not spec.get("instructions"):
            raise MalformedRequest(f"question {qid!r}: noul needs `instructions`.")


def _dist(ans: dict, kind: str) -> dict:
    if kind == "choice":
        p = ans.get("probabilities") or {}
        return {str(k): float(v) for k, v in p.items()} if p else {}
    if kind == "noul":
        raw = ans.get("noul")
        if isinstance(raw, (int, float)):
            return {"yes": float(raw), "no": 1.0 - float(raw)}
    if kind == "score":
        return ans.get("probabilities") or {}
    return {}


def _verdict(dist: dict, kind: str) -> str | None:
    """Read the verdict from a STRUCTURED field.

    Never from prose. The version of this that searched the reply for the last
    occurrence of "correct" scored a reply that opened "on the right track" and
    concluded later that a choice was correct, as fully confident.
    """
    if not dist:
        return None
    return max(dist, key=dist.get)


class Client:
    def __init__(self, key: str | None = None, model: str = DEFAULT_MODEL,
                 base: str = BASE, timeout: int = 50, tries: int = 4):
        self.key = key or os.environ.get("TYPESAFEAI_KEY", "")
        self.model = model
        self.base = base
        self.timeout = timeout
        self.tries = tries
        self.journal = Journal()
        self.calls = 0
        if not self.key:
            raise RuntimeError("no TYPESAFEAI_KEY in the environment")

    # ── the one call everything else is built on ──────────────────────────────
    def ask(self, state: str, questions: dict) -> list:
        body = {"model": self.model, "state": state, "questions": questions}
        preflight(body)                       # raises BEFORE anything is sent
        req = urllib.request.Request(
            self.base, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json",
                     "Accept": "application/json",
                     "User-Agent": "jev-harness/0.1"},
        )
        last = {}
        t0 = time.time()
        for a in range(self.tries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    last = json.loads(r.read() or b"{}")
                break
            except urllib.error.HTTPError as e:
                if e.code in (502, 503, 504) and a < self.tries - 1:
                    time.sleep(0.5 + random.random() * 0.3)
                    continue
                last = {"error": f"HTTP {e.code}"}
                break
            except Exception:
                if a < self.tries - 1:
                    time.sleep(0.5)
                    continue
                last = {"error": "transport"}
        self.calls += 1
        answers = self._parse(questions, last)
        self.journal.add(body, last, answers, time.time() - t0)
        return answers

    def _parse(self, questions: dict, resp: dict) -> list:
        out = []
        got = resp.get("answers") or {}
        for qid, spec in questions.items():
            kind = spec.get("type")
            ans = got.get(qid)
            if not ans:
                out.append(Answer(qid, kind, None, 0.0, {}, None, False,
                                 resp.get("error", "no answer for this question")))
                continue
            dist = _dist(ans, kind)
            v = _verdict(dist, kind)
            p = dist.get(v, 0.0) if v else 0.0
            ok = v is not None and p > 0
            note = "" if ok else "no parseable verdict; treat as FAILURE, not a low score"
            out.append(Answer(qid, kind, v, p, dist, ans.get("confidence"), ok, note))
        return out          # <-- MISSING ON THE FIRST LIVE RUN. Without this the parser
                             # returns None, the journal crashes, and the library looks
                             # like a transport bug rather than a missing return.

    # ── the two primitives worth having ──────────────────────────────────────
    def choice(self, state: str, instructions: str, criteria: dict, qid="q") -> Answer:
        """A judgement over a fixed label set. The whole point of the model.

        `criteria` maps each LABEL to what that label means. A label whose meaning is
        not written down is a label the model has to guess at, and it will guess
        consistently, which is the dangerous part.
        """
        (a,) = self.ask(state, {qid: {"type": "choice", "instructions": instructions,
                                       "criteria": criteria}})
        return a

    def noul(self, state: str, instructions: str, qid="q") -> Answer:
        """A calibrated probability of yes. One question per call by default: the noul
        contract does not carry a multi-question batch the way choice does, and a
        batched noul that silently answers about the wrong subject is worse than no noul."""
        (a,) = self.ask(state, {qid: {"type": "noul", "instructions": instructions}})
        return a

    def many_choices(self, state: str, specs: dict) -> dict:
        """Batched independent choices. They run in parallel and cannot see each other,
        which is the property you want: a set of mutually-blind judgements.

        Every spec MUST name its own subject. A batch of questions that rely on shared
        context is not a batch, it is one question asked four times.
        """
        answers = self.ask(state, specs)
        return {a.qid: a for a in answers}

    # ── the preflight a claim needs before it is a claim ────────────────────
    def selftest(self) -> dict:
        """Verify the model separates a true statement from a false one.

        A client that cannot pass this should not be used to gate anything. This is
        cheap, it is exact, and running it once per session prevents the failure where
        a broken request looks like a finding about the model.
        """
        crit = {"true": "This statement is factually correct.",
                "false": "This statement is factually incorrect.",
                "uncertain": "There is not enough information to judge it."}
        cases = [("The number two plus two equals four.", "true"),
                 ("The number two plus two equals five.", "false"),
                 ("Water is dry.", "false"),
                 ("Paris is the capital of France.", "true"),
                 ("Paris is the capital of Spain.", "false")]
        rows, ok = [], 0
        for stmt, want in cases:
            a = self.choice(stmt, f"Is this statement true or false? — STATEMENT: {stmt}", crit)
            good = a.verdict == want
            ok += good
            rows.append({"statement": stmt, "want": want, "got": a.verdict,
                         "p": a.probability, "ok": good,
                         "note": a.note})
        return {"passed": ok, "total": len(cases), "rows": rows,
                "verdict": "JUDGE VERIFIED" if ok == len(cases) else "JUDGE UNRELIABLE"}
