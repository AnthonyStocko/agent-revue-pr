"""Tests isolés comme dans agent-scrum-master : réseau coupé hors 127.0.0.1, git borné, journaux temporaires."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_configure(config):
    config.addinivalue_line("markers", "reseau: test autorisé à joindre le réseau réel (aucun par défaut)")


LOCAL = ("127.0.0.1", "::1", "localhost", "0.0.0.0", "")


def _local(hote) -> bool:
    return str(hote).lower() in LOCAL or str(hote).startswith("127.")


@pytest.fixture(autouse=True)
def _git_borne(tmp_path_factory, monkeypatch):
    """
    Git ne remonte jamais au-dessus du dossier temporaire de pytest : un dossier de test qui n'est pas un dépôt
    échoue (« not a git repository ») au lieu d'atteindre un dépôt parent du poste (ex. le dossier personnel), où
    add/commit écriraient et parcourraient tout le profil.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path_factory.getbasetemp().parent))


@pytest.fixture(autouse=True)
def _reseau_coupe(request, monkeypatch):
    """
    Aucun appel réseau réel en test (Bitbucket, Jira, Jenkins, groundcover… avec les jetons du .env du poste) :
    toute connexion hors de la machine échoue tout de suite (ConnectionRefusedError, comme un service injoignable).
    127.0.0.1 reste permis (AppTest, serveurs de test). Un test qui a vraiment besoin du réseau : marqueur reseau.
    """
    if request.node.get_closest_marker("reseau"):
        return
    import socket
    connect, resolve = socket.socket.connect, socket.getaddrinfo

    def connect_local(sock, adresse):
        if isinstance(adresse, tuple) and not _local(adresse[0]):
            raise ConnectionRefusedError(f"réseau coupé en test : {adresse[0]}")
        return connect(sock, adresse)

    def resolve_local(hote, *args, **kwargs):
        if not _local(hote):
            raise socket.gaierror(f"réseau coupé en test : {hote}")
        return resolve(hote, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect_local)
    monkeypatch.setattr(socket, "getaddrinfo", resolve_local)
    # Jenkins : un seul essai, sans les reprises espacées de _get (2 + 4 + 6 s par appel vers un réseau coupé)
    from agent_socle import jenkins_tools

    def get_sans_reprise(url, timeout, attempts=3, **kwargs):
        _, auth = jenkins_tools._jenkins()
        return jenkins_tools.requests.get(url, auth=auth, timeout=timeout, **kwargs)

    monkeypatch.setattr(jenkins_tools, "_get", get_sans_reprise)


@pytest.fixture(autouse=True)
def _isolement(tmp_path, monkeypatch):
    """Connaissances partagées, journaux des exécutions et groundcover jamais ceux du poste (.env)."""
    monkeypatch.setenv("AGENT_KNOWLEDGE_DIR", str(tmp_path / "connaissances_partagees"))
    monkeypatch.setenv("GROUNDCOVER_MCP_ENABLED", "0")
    monkeypatch.setenv("AGENT_RUN_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("AGENT_JOURNAL_PATH", str(tmp_path / "journal_technique.log"))
