#!/usr/bin/env python3
"""Capture the installed runtime dependency closure, not the unrelated build environment.
This is a version lock, not a hash-verified supply-chain audit. Review before updating.
"""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name
import tomllib
root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/'pyproject.toml').read_text())['project']
queue=list(project['dependencies']); versions={}; env=default_environment();env['extra']=''
while queue:
    requirement=Requirement(queue.pop())
    if requirement.marker and not requirement.marker.evaluate(env):continue
    name=canonicalize_name(requirement.name)
    if name in versions:continue
    dist=distribution(requirement.name)
    versions[name]=dist.version
    for dep in dist.requires or []:
        parsed=Requirement(dep)
        if not parsed.marker or parsed.marker.evaluate(env):queue.append(dep)
header='# Observed installed runtime dependency closure, 2026-10-03, CPython 3.13 Linux.\n# Version-pinned; package hashes and independent vulnerability review are still required.\n'
(root/'requirements-runtime.lock').write_text(header+'\n'.join(f'{name}=={version}' for name,version in sorted(versions.items()))+'\n')
print(f'Wrote {len(versions)} dependency versions')
