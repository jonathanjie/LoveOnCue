#!/usr/bin/env python3
"""Score the live intent parser against labelled messages, including Singlish and texting shorthand.

    eval-intents.py --key-file PATH [--cases evals/intents.jsonl] [--model MODEL]

Each case lists the intent kinds that count as correct, and optionally the
minutes a delay or lateness must carry. Prints each miss and the accuracy.
This makes one model call per case, so it costs a little money.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wedding_ops.agent import MistralParser
from wedding_ops.config import DEFAULT_MISTRAL_MODEL, Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[1] / "evals/intents.jsonl")
    parser.add_argument("--model", default=DEFAULT_MISTRAL_MODEL)
    args = parser.parse_args()
    settings = Settings(mode="test", agent_mode="mistral", mistral_model=args.model,
                        mistral_api_key=args.key_file.read_text().strip())
    cases = [json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
    correct = 0
    with closing(MistralParser(settings)) as model:
        for case in cases:
            try:
                intent = model.parse(case["text"])
                kind, minutes = intent.kind, intent.minutes
            except Exception as error:  # A failed call counts as a miss, with the error type shown.
                kind, minutes = f"error:{type(error).__name__}", None
            ok = kind in case["expect"] and ("minutes" not in case or minutes == case["minutes"])
            correct += ok
            if not ok:
                wanted = "/".join(case["expect"]) + (f" ({case['minutes']} min)" if "minutes" in case else "")
                print(f"MISS  {case['text']!r}: got {kind}" + (f" ({minutes} min)" if minutes else "") + f", wanted {wanted}")
    print(f"\n{correct}/{len(cases)} correct ({100 * correct / len(cases):.0f}%) with {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
