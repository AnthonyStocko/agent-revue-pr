"""IHM d'agent-revue-pr : démarrage à blanc (Bitbucket non configuré, aucun appel réseau)."""
import os

import dotenv
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_page_revue_sans_bitbucket(monkeypatch):
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("AGENT_AUTH", "0")
    monkeypatch.setenv("BITBUCKET_URL", "")
    monkeypatch.setenv("BITBUCKET_HTTP_TOKEN", "")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value == "🔍 Revue de PR"


def test_cli_aide():
    import subprocess
    import sys
    sortie = subprocess.run([sys.executable, "main.py", "--help"], capture_output=True, text=True, encoding="utf-8",
                            cwd=os.path.dirname(APP))
    assert sortie.returncode == 0 and "--pr-url" in sortie.stdout
