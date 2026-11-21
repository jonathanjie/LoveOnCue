# LoveOnCue Telegram user tester

Drives `@LoveOnCue_bot` from a real Telegram user account, so staging tests can
send messages and press inline buttons without a phone. It is a development
tool. It is not part of the app and has its own dependencies.

## Risk

A Telethon session can act as the whole Telegram account. The tool only opens
the bot chat, but that is a rule in this code, not a limit on the session.
Keep the session in a root-only directory. Prefer a separate test account.
To revoke access, end the session in Telegram: **Settings → Devices**.

## Install on the VPS

```bash
sudo install -d -m 0700 /opt/loveoncue-tester /etc/loveoncue-tester
sudo cp tools/telegram_tester/* /opt/loveoncue-tester/
sudo chmod 0755 /opt/loveoncue-tester/role.sh
sudo python3.12 -m venv /opt/loveoncue-tester/.venv
sudo /opt/loveoncue-tester/.venv/bin/pip install -r /opt/loveoncue-tester/requirements.txt
```

## Log in once

A person runs this in an interactive SSH session and types the login code:

```bash
ssh -t jons-openclaw@194.233.68.86 sudo /opt/loveoncue-tester/.venv/bin/python /opt/loveoncue-tester/loveoncue_tester.py login
```

## Use

```bash
sudo /opt/loveoncue-tester/.venv/bin/python /opt/loveoncue-tester/loveoncue_tester.py send /help
sudo /opt/loveoncue-tester/.venv/bin/python /opt/loveoncue-tester/loveoncue_tester.py tap "My tasks"
sudo /opt/loveoncue-tester/.venv/bin/python /opt/loveoncue-tester/loveoncue_tester.py history 5
```

`tap` presses only callback buttons. It refuses link and Mini App buttons.

```bash
sudo /opt/loveoncue-tester/.venv/bin/python /opt/loveoncue-tester/loveoncue_tester.py photo --caption "Table 12 setup"
```

`photo` sends a generated striped test card unless you give an image path.

## Switch roles

One Telegram account can play every staging role. `role.sh` moves the
account's link to another fixture member through the app's operator CLI. The
CLI refuses unless the app runs with `WEDDINGOPS_REHEARSAL=true`, and there is
no chat command for it.

```bash
sudo /opt/loveoncue-tester/role.sh members
sudo /opt/loveoncue-tester/role.sh coordinator
sudo /opt/loveoncue-tester/role.sh banquet
```
