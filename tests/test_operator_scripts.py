"""Operator integration configuration with mocked external transport only."""
import importlib.util,json
import sys
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
    assert calls[1][1]['allowed_updates']==['message', 'callback_query'] and not calls[1][1]['drop_pending_updates']

def test_wrong_bot_never_changes_configuration():
    calls=[]
    def transport(req):
        calls.append(req)
        return httpx.Response(200,json={'ok':True,'result':{'is_bot':True,'username':'AnotherBot'}})
    with pytest.raises(ValueError):module.configure(settings(),'WeddingOpsFixtureBot',httpx.MockTransport(transport))
    assert len(calls)==1



def test_worker_tick_does_not_load_web_server(db, monkeypatch, capsys):
    from wedding_ops.cli import main

    monkeypatch.setitem(sys.modules, "wedding_ops.api", None)
    monkeypatch.setenv("WEDDINGOPS_MODE", "test")
    monkeypatch.setenv("WEDDINGOPS_DATABASE_URL", db.engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("WEDDINGOPS_WEDDING_ID", "demo-wedding")
    monkeypatch.setenv("WEDDINGOPS_AGENT_MODE", "deterministic")
    monkeypatch.setenv("WEDDINGOPS_SEND_NOTIFICATIONS", "false")
    monkeypatch.setattr(sys, "argv", ["weddingops", "worker", "--once"])

    main()

    assert json.loads(capsys.readouterr().out)["transport"] == "simulated"


def test_telegram_rehearsal_uses_distinct_roles_and_ignores_deployed_settings(monkeypatch):
    import subprocess

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("WEDDINGOPS_MODE", "production")
    monkeypatch.setenv("WEDDINGOPS_DATABASE_URL", "postgresql+psycopg://unused.invalid/production")
    monkeypatch.setenv("WEDDINGOPS_AGENT_MODE", "mistral")
    monkeypatch.setenv("WEDDINGOPS_SEND_NOTIFICATIONS", "true")
    result = subprocess.run([
        sys.executable, str(root / "scripts/rehearse-telegram.py"),
        "--as", "coordinator", "/brief",
        "--as", "banquet", "/brief",
        "--as", "registration-a", "/guest Sarah Tan",
    ], cwd=root, capture_output=True, text=True, check=True)
    assert "Coordinator brief" in result.stdout
    assert "Your role does not permit this action" in result.stdout
    assert "Sarah Tan: Table 18" in result.stdout
    assert "Sent to Telegram" not in result.stdout


def test_worker_checks_outbox_after_a_slow_inbound_job(db, monkeypatch, capsys):
    from types import SimpleNamespace
    from wedding_ops import cli
    from wedding_ops.telegram import TelegramIngress

    job_times = []
    def process_job(_):
        job_times.append(3)
        return True

    monkeypatch.setattr(TelegramIngress, "process_one", process_job)
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: sum(job_times)))
    monkeypatch.setenv("WEDDINGOPS_MODE", "test")
    monkeypatch.setenv("WEDDINGOPS_DATABASE_URL", db.engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("WEDDINGOPS_AGENT_MODE", "deterministic")
    monkeypatch.setenv("WEDDINGOPS_SEND_NOTIFICATIONS", "false")
    monkeypatch.setattr(sys, "argv", ["weddingops", "worker", "--once"])

    cli.main()

    assert len(job_times) == 1
    assert json.loads(capsys.readouterr().out)["transport"] == "simulated"
