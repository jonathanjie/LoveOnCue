#!/usr/bin/env python3
"""Explicit operator action: configure this cell's webhook and Mini App menu, not messages."""
from pathlib import Path
import argparse,re,sys
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wedding_ops.config import Settings


def configure(settings: Settings, username: str, transport=None) -> dict:
    settings.validate()
    if settings.mode!='production' or not settings.public_url.startswith('https://'):
        raise ValueError('Use a commissioned production-mode HTTPS cell with a separate development bot')
    if not settings.telegram_bot_token or not re.fullmatch(r'[A-Za-z0-9_-]{24,256}',settings.telegram_webhook_secret):
        raise ValueError('Set bot credentials and a valid 24-256 character webhook secret')
    expected=settings.telegram_bot_username.lstrip('@')
    if not expected or username.lstrip('@').lower()!=expected.lower():
        raise ValueError('Confirm the exact configured bot username')
    with httpx.Client(timeout=15,follow_redirects=False,transport=transport) as client:
        def call(method,payload):
            try:
                response=client.post(f'https://api.telegram.org/bot{settings.telegram_bot_token}/{method}',json=payload)
                response.raise_for_status();data=response.json()
                if not data.get('ok'):raise RuntimeError(f'{method} was rejected; check provider status privately')
                return data['result']
            except (httpx.HTTPError,ValueError,KeyError) as exc:
                # Exception strings may include the credential-bearing request URL.
                raise RuntimeError(f'{method} failed ({type(exc).__name__}); no credentials logged') from None
        identity=call('getMe',{})
        if not identity.get('is_bot') or identity.get('username','').lower()!=expected.lower():
            raise ValueError('Token belongs to a different bot; nothing configured')
        call('setWebhook',{'url':settings.public_url+'/api/telegram/webhook',
                          'secret_token':settings.telegram_webhook_secret,'allowed_updates':['message'],
                          'drop_pending_updates':False})
        call('setChatMenuButton',{'menu_button':{'type':'web_app','text':'WeddingOps','web_app':{'url':settings.public_url}}})
    return {'status':'configured','bot_username':expected,'messages_sent':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-bot-username',required=True)
    args=parser.parse_args()
    try:print(configure(Settings.from_env(),args.confirm_bot_username))
    except (ValueError,RuntimeError) as exc:parser.exit(1,str(exc)+'\n')
if __name__=='__main__':main()
