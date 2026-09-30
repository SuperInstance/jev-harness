# jev-harness

A client for the TypeSafe.ai **Jev** System One model that cannot fail quietly.

## Why this exists

I published a claim that the model "does not discriminate," on the strength of four
requests and a control that agreed with me. **Both were mine, not the model's.** The
requests used `state` as an object and invented an `options` field. The control was built
from the same call path as the probes, so it confirmed the fault rather than auditing it.

**A malformed request to this API does not raise. It returns a well-formed, confidently
unhelpful answer.** That is the most dangerous property of the interface, and it is why this
library checks every request *before* it leaves the process and scores every response from
its structured field rather than from prose.

## What it guarantees

1. **`preflight()` refuses to send a request that does not match the documented contract.**
   A library that cannot send a malformed request cannot produce a malformed finding.
2. **Answers are scored, never string-matched out of prose.** A reply with no parseable
   verdict is `None`, and `None` is a **failure** — not a low score. Collapsing those two is
   how a broken control reports agreement with a broken thing.
3. **Every call is journalled**, so any published number can be re-checked against the
   exact request that produced it.

## The contract

```
POST https://api.typesafe.ai/v1/systemone
{"model": "jev-1.13.0",
 "state": "<a STRING>",
 "questions": {"<qid>": {"type": "choice",
                         "instructions": "<the question>",
                         "criteria": {"<label>": "<what the label MEANS>"}}}}
```

- `state` is a **string**. Sending a dict does not error.
- **There is no `options` field.** The option set **is** the keys of `criteria`.
- A label whose meaning is not written down is a label the model has to guess at — and it
  guesses *consistently*, which is the dangerous part.

## Use

```python
from jev_harness import Client

c = Client()
c.selftest()                      # 5 true/false controls; refuse to proceed if it fails

a = c.choice(
    state="<the situation, as a string>",
    instructions="<one narrow question>",
    criteria={"yes": "<what yes means>",
              "no":  "<what no means>",
              "uncertain": "<when to abstain>"},
)
print(a.verdict, a.probability, a.distribution)   # read the DISTRIBUTION, not just argmax
c.journal.save("run.json")
```

## Reading a `choice` answer

A confident argmax over a flat distribution is a failure mode, not a result. The harness
reports the **gap** — `max - mean` — because a gap near zero means the model did not
discriminate, and a caller who only reads the argmax cannot see that.

## Tests

```
python3 run_tests.py     # 7 tests, no pytest needed
python3 selftest.py      # live, needs TYPESAFEAI_KEY
```

## The bug this library shipped with first

`_parse()` had no `return` statement. It was found by **running it against the live model**,
not by reading it — the preflight tests all passed while the library could not parse a
response. That is the same lesson as every other one this project has learned: **an
instrument that has never been run has never been tested.**

## What it is not

A truth oracle. Jev is a calibrated judgement about a stated question, and it is only as
good as the question. It was used here to gate a compile/decompose boundary, to score
selection, and to verify itself — never to decide whether an answer is correct.
