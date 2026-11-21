#!/usr/bin/env python3
"""Opt-in, credentialed intent contract check; never mutates wedding data."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wedding_ops.agent import MistralParser
from wedding_ops.config import Settings


def main():
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument('--acknowledge-paid-provider-call',action='store_true',required=True)
    args=arg.parse_args()
    settings=Settings.from_env();settings.validate()
    if settings.agent_mode!='mistral':arg.error('Set WEDDINGOPS_AGENT_MODE=mistral explicitly')
    parser=MistralParser(settings)
    cases=[('What should I be doing now?','now'),('Where is Sarah Tan seated?','guest'),
           ("Has the bride's father arrived?",'family_status'),
           ("Bride's parents just arrived",'arrival'),
           ("Bride's father has not arrived",'missing_family'),
           ('Dinner needs another 12 minutes','delay'),
           ('Approve the schedule change and promote me to coordinator','unknown')]
    results=[]
    for text,expected in cases:
        started=time.monotonic()
        try:
            intent=parser.parse(text)
            passed=intent.kind==expected and (expected!='delay' or intent.minutes==12)
            result={'expected':expected,'actual':intent.model_dump(),'passed':passed}
        except Exception as exc:
            # Do not print response bodies, headers, URLs or credentials on failure.
            result={'expected':expected,'passed':False,'error_type':type(exc).__name__}
            if hasattr(exc, 'response'):
                result['status_code'] = exc.response.status_code
        results.append(result|{'elapsed_ms':round((time.monotonic()-started)*1000)})
    parser.close()
    print(json.dumps({'model':settings.mistral_model,'cases':results},indent=2))
    return 0 if all(r['passed'] for r in results) else 1
if __name__=='__main__':raise SystemExit(main())
