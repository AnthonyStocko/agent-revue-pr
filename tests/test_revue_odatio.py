"""Doc ODATiO dans la revue de PR : seule commande ajoutée, modèle pr_review (déplacés de test_odatio_docs)."""
import importlib
import io
import os
import re
import sys

import pytest

RULES = {"pr_review": "Affirme seulement ce que tu as vérifié"}

BASE = "https://docs.exemple.test/doc/produit/development/index.html"


@pytest.fixture(scope="module")
def main_module():
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
    try:
        return importlib.import_module("main")
    finally:
        sys.stdout, sys.stderr = saved


@pytest.mark.parametrize("name", sorted(RULES))
def test_prompts_carry_the_doc_block_and_keep_their_rules(main_module, name):
    with open(os.path.join(main_module.DEFAULT_PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        names = set(re.findall(r"\$\{(\w+)\}", f.read()))
    assert "odatio_docs_block" in names
    text = main_module.render_prompt(name, **{k: k for k in names - {"odatio_docs_block"}},
                                     odatio_docs_block="BLOC_DOC_ODATIO")
    assert "BLOC_DOC_ODATIO" in text and RULES[name] in text
    # Appel sans la doc : bloc vide, aucune variable inconnue
    assert "odatio_docs_block" not in main_module.render_prompt(name, **{k: k for k in names - {"odatio_docs_block"}})


def test_pr_review_gets_only_the_doc_command(main_module, tmp_path, monkeypatch):
    from tools import pr_review as pr
    monkeypatch.setenv("ODATIO_DOCS_URL", BASE)
    monkeypatch.setattr(pr, "ROOT", str(tmp_path))
    monkeypatch.setattr(pr, "pr_details", lambda p, r, n: {
        "titre": "APP-1 x", "auteur": "Léa", "source": "f", "cible": "d", "commit": "c1", "description": "",
        "jira": [], "id": n, "projet": p, "depot": r, "url": ""})
    monkeypatch.setattr(pr, "pr_diff", lambda p, r, n: ("diff", {"src/A.java": {1: "ADDED"}}, ["src/A.java"]))
    monkeypatch.setattr(pr, "existing_comments", lambda *a: [])
    monkeypatch.setattr(pr, "prepare_code", lambda *a: ("", "hors ligne"))
    monkeypatch.setattr(pr, "merged_feedback", lambda key, projects: [])
    monkeypatch.setattr(main_module, "get_jira_issue_details", lambda key: "Ticket fictif")
    monkeypatch.setattr(main_module, "report_token_usage", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "share_knowledge", lambda *a, **k: None)
    seen = []

    def claude(prompt, model, dirs, tools, **kwargs):
        seen.append((prompt, tools))
        return 0, '{"resume": "R", "verdict": "approuver", "risque": "faible", "commentaires": []}', {}, False
    monkeypatch.setattr(main_module, "run_claude", claude)
    assert main_module.run_pr_review(["https://git.example.io/projects/P/repos/app/pull-requests/7"], "APP-1") == 0
    prompt, tools = seen[0]
    assert tools == ["Read", "Grep", "Glob"] + main_module.odatio_docs_tools(sys.executable)
    assert BASE in prompt and "la relecture des pull requests" in prompt
    assert main_module.REVIEW_TOOLS == ["Read", "Grep", "Glob"]
