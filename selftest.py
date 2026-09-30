"""Run the harness against the live model, and print the manifest.

    TYPESAFEAI_KEY=... python3 selftest.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev_harness import Client

if __name__ == "__main__":
    if not os.environ.get("TYPESAFEAI_KEY"):
        print("  no TYPESAFEAI_KEY; skipping the live check")
        raise SystemExit(0)
    c = Client()
    r = c.selftest()
    print(f"  {r['verdict']}   {r['passed']}/{r['total']}")
    for row in r["rows"]:
        print(f"    {row['want']:6} want  got {str(row['got']):6} p={row['p']:.3f}  {row['statement'][:48]}")
    # a real judgement, and the full distribution rather than the argmax
    a = c.choice(
        "A 10x10 field is being corrected. The left and right sides of a seam disagree "
        "while every cell agrees with its own neighbours. The free local-noise statistic "
        "is blind to this. Does a wide-reading model beat it here?",
        "Does a wide-reading model beat a blind local statistic on cross-seam structure?",
        {"yes": "The model reads structure a local statistic provably cannot, and beats it.",
         "no": "The model does not beat the local statistic, or the comparison is uninformative.",
         "uncertain": "There is not enough information to judge."})
    print(f"\n  a real judgement, full distribution:")
    for k, v in sorted(a.distribution.items(), key=lambda t: -t[1]):
        print(f"    {k:10} {v:.4f}  {'#' * int(v * 40)}")
    print(f"  gap (max - mean) = {a.probability - sum(a.distribution.values())/max(1,len(a.distribution)):.4f}"
          f"   -> {'DISCRIMINATES' if (a.probability - sum(a.distribution.values())/max(1,len(a.distribution))) > 0.05 else 'FLAT -- do not trust the argmax'}")
    c.journal.save("selftest_journal.json")
    print(f"\n  {c.calls} calls journalled -> selftest_journal.json")
