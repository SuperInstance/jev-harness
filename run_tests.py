"""Tests, with no pytest dependency -- the library ships where pytest may not exist."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev_harness.client import preflight, MalformedRequest, _verdict, _dist

def test_preflight_refuses_the_request_that_caused_a_retraction():
    try:
        preflight({"model": "m", "state": {"not": "a string"},
                   "questions": {"q": {"type": "choice", "instructions": "i",
                                       "criteria": {"a": "x", "b": "y"}}}})
    except MalformedRequest:
        return
    raise AssertionError("preflight allowed `state` to be an object")

def test_preflight_refuses_an_invented_options_field():
    try:
        preflight({"model": "m", "state": "s",
                   "questions": {"q": {"type": "choice", "options": ["a", "b"],
                                       "instructions": "i",
                                       "criteria": {"a": "x", "b": "y"}}}})
    except MalformedRequest:
        return
    raise AssertionError("preflight allowed an `options` field; there is none in the contract")

def test_preflight_refuses_a_one_option_choice():
    try:
        preflight({"model": "m", "state": "s",
                   "questions": {"q": {"type": "choice", "instructions": "i",
                                       "criteria": {"a": "x"}}}})
    except MalformedRequest:
        return
    raise AssertionError("a choice with one option is not a choice")

def test_preflight_allows_the_documented_shape():
    preflight({"model": "m", "state": "s",
               "questions": {"q": {"type": "choice", "instructions": "i",
                                   "criteria": {"a": "x", "b": "y"}}}})

def test_preflight_accepts_noul_and_score():
    preflight({"model": "m", "state": "s",
               "questions": {"n": {"type": "noul", "instructions": "i"},
                             "s": {"type": "score", "criteria": [{"text": "low"}, {"text": "high"}]}}})

def test_verdict_reads_the_structured_field_not_prose():
    """The failure that mattered: a reply that OPENS 'on the right track' and later says
    a different thing must not be read as whichever word appeared last."""
    dist = {"true": 0.4, "false": 0.6}
    assert _verdict(dist, "choice") == "false"
    assert _verdict({}, "choice") is None, "an empty distribution has no verdict"

def test_noul_is_expanded_into_a_two_point_distribution():
    d = _dist({"noul": 0.8}, "noul")
    assert abs(d["yes"] - 0.8) < 1e-9 and abs(d["no"] - 0.2) < 1e-9, d
    assert _verdict(d, "noul") == "yes"

def test_a_near_half_noul_is_uncertainty_not_intensity():
    d = _dist({"noul": 0.5}, "noul")
    assert _verdict(d, "noul") == "yes"   # ties resolve, which is exactly the trap
    # the harness must make that visible rather than silently pick a side
    assert abs(d["yes"] - d["no"]) < 1e-9

if __name__ == "__main__":
    ok = fail = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name](); ok += 1; print(f"  PASS  {name}")
        except Exception as e:
            fail += 1; print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n  {ok} passed, {fail} failed")
    sys.exit(1 if fail else 0)
