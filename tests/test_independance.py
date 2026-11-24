"""agent-revue-pr n'importe aucun autre agent : seulement agent_socle, ses propres modules tools/ et la bibliothèque."""
import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PROPRES = {p.stem for p in (RACINE / "tools").glob("*.py")}
INTERDITS = ("webhook_server", "mcp_lecture", "manager", "api")


def test_aucun_import_d_un_autre_agent():
    fautes = []
    for f in sorted(p for p in RACINE.rglob("*.py") if "tests" not in p.parts and ".venv" not in p.parts):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                noms = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module == "tools":
                noms = [f"tools.{a.name}" for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                noms = [n.module or ""]
            else:
                continue
            fautes += [f"{f.name}:{n.lineno} {nom}" for nom in noms
                       if nom.split(".")[0] in INTERDITS
                       or (nom.startswith("tools.") and nom.split(".")[1] not in PROPRES)]
    assert not fautes, fautes
