"""Operator integration configuration with mocked external transport only."""
import importlib.util,json
from pathlib import Path
import httpx,pytest
from wedding_ops.config import Settings
spec=importlib.util.spec_from_file_location('telegram_configuration',Path(__file__).resolve().parents[1]/'scripts/configure-telegram.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def settings():
    return Settings(mode='production',database_url='postgresql+psycopg://fixture',wedding_id='fixture-cell',
        public_url='https://fixture.example.invalid',telegram_bot_token='FAKE-NOT-A-CREDENTIAL',
        telegram_webhook_secret='fictional_secret_value_for_mock_test',telegram_bot_username='WeddingOpsFixtureBot')

def test_configure_telegram_checks_identity_then_scopes_webhook_and_menu():
    calls=[]
    def transport(req):
        method=req.url.path.split('/')[-1];calls.append((method,json.loads(req.content)))
        return httpx.Response(200,json={'ok':True,'result':{'is_bot':True,'username':'WeddingOpsFixtureBot'} if method=='getMe' else True})
    result=module.configure(settings(),'WeddingOpsFixtureBot',httpx.MockTransport(transport))
    assert result['messages_sent']==0
    assert [c[0] for c in calls]==['getMe','setWebhook','setChatMenuButton']
    assert calls[1][1]['allowed_updates']==['message'] and not calls[1][1]['drop_pending_updates']

def test_wrong_bot_never_changes_configuration():
    calls=[]
    def transport(req):
        calls.append(req)
        return httpx.Response(200,json={'ok':True,'result':{'is_bot':True,'username':'AnotherBot'}})
    with pytest.raises(ValueError):module.configure(settings(),'WeddingOpsFixtureBot',httpx.MockTransport(transport))
    assert len(calls)==1
