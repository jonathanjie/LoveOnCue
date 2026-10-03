#!/usr/bin/env python3
"""Generate public engineering contracts without opening any user database."""
from pathlib import Path
import json,sys
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'src'))
from wedding_ops.api import create_app
from wedding_ops.config import Settings
from wedding_ops.db import Database
from wedding_ops.schemas import CommandRequest, Intent
from wedding_ops.policy import GRANTS
out=root/'docs/contracts';out.mkdir(parents=True,exist_ok=True)
database=Database('sqlite://')
app=create_app(Settings(mode='test'),database)
for name,value in [('openapi.json',app.openapi()),('commands.schema.json',CommandRequest.model_json_schema()),('intent.schema.json',Intent.model_json_schema()),('permissions.json',{role:sorted(grants) for role,grants in sorted(GRANTS.items())})]:
 (out/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
database.close()
print('Exported OpenAPI, command, intent and permission contracts')
