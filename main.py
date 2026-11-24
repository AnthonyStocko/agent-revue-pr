"""
CLI d'agent-revue-pr : --step review-pr, relecture assistée des pull requests d'une fonctionnalité (lecture seule).
Code repris tel quel d'agent-scrum-master (étape review-pr), qui y délègue : `main.py --step review-pr …`.
"""
import argparse
import io
import logging
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv

from agent_socle import cli, env_tools
from agent_socle.chemins import DATA_DIR
from agent_socle.cli import (_env_int, claude_effort, lean_session, odatio_docs_block, odatio_docs_tools,
                             render_prompt, report_token_usage, run_claude, share_knowledge)
from agent_socle.jira_tools import get_jira_issue_details
from tools import pr_review

# Modèles de prompts de l'agent (prompts/*.md), puis ceux du socle
DEFAULT_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
cli.DEFAULT_PROMPTS_DIR = DEFAULT_PROMPTS_DIR

# Force l'encodage UTF-8 sous Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Même .env que les autres agents (AGENT_DATA_DIR), jamais copié
ENV_PATH = os.path.join(DATA_DIR, ".env")
logging.getLogger("dotenv.main").setLevel(logging.ERROR)
load_dotenv(ENV_PATH)
if env_tools.check_env(ENV_PATH):
    print(f"[CONFIGURATION] ⚠️ {env_tools.check_line(env_tools.check_env(ENV_PATH))}")


REVIEW_TOOLS = ["Read", "Grep", "Glob"]


def run_pr_review(pr_urls: list, feature: str = "") -> int:
    """
    Revue assistée d'une FONCTIONNALITÉ (lecture seule) : toutes ses pull requests Bitbucket relues ensemble — diff et
    code de chaque PR, ticket(s) Jira, conventions de l'équipe, commentaires déjà posés. Résultat (résumé, cohérence
    entre les PR, verdict, commentaires ligne par ligne rattachés à leur PR) enregistré pour l'onglet « Revue de PR ».
    Rien n'est publié sur Bitbucket ici. Renvoie le code de sortie.
    """
    urls = [u for u in dict.fromkeys(u.strip() for u in pr_urls or [] if u and u.strip())]
    if not urls:
        print("[REVUE PR] ❌ Aucune pull request à relire (--pr-url).")
        return 2
    run_dir = os.path.join(pr_review.ROOT, "runs", re.sub(r"[^\w.-]", "_", feature or "pr")
                           + f"_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    os.makedirs(run_dir, exist_ok=True)
    prs, blocks, comments, maps, dirs, keys = [], [], [], {}, [run_dir], []
    for url in urls:
        try:
            project, repo, number = pr_review.parse_pr_url(url)
            pr = pr_review.pr_details(project, repo, number)
            diff, lines_map, files = pr_review.pr_diff(project, repo, number)
            existing = pr_review.existing_comments(project, repo, number)
        except (ValueError, pr_review.BitbucketError) as e:
            print(f"[REVUE PR] ❌ {url} : {e}")
            return 2
        label = pr_review.pr_label(pr)
        diff_file = os.path.join(run_dir, f"{label.replace('#', '_')}.diff")
        with open(diff_file, "w", encoding="utf-8") as f:
            f.write(diff)
        code, why = pr_review.prepare_code(project, repo, number, pr["commit"])
        print(f"[REVUE PR] {label} — {pr['titre']} ({pr['auteur']}, {len(files)} fichier(s)) : "
              + (f"code {code}" if code else f"⚠️ diff seul ({why})"))
        if code:
            dirs.append(code)
        blocks.append(f"- PR « {label} » : {project}/{repo} #{number} — {pr['titre']} ; auteur {pr['auteur']} ; "
                      f"{pr['source']} → {pr['cible']} ; {len(files)} fichier(s)\n  diff : '{diff_file}'\n  code : "
                      + (f"'{code}'" if code else "indisponible (diff seul : formule en question ce que tu ne peux "
                                                  "pas vérifier)")
                      + (f"\n  description : {' '.join(pr['description'].split())[:800]}" if pr["description"] else ""))
        comments += [{**c, "pr": label} for c in existing]
        maps[label] = lines_map
        keys += pr["jira"]
        prs.append({**pr, "repere": label, "fichiers": files})
    feature = feature or (keys[0] if keys else "")
    # Remarques déjà faites sur les PR FUSIONNÉES du même ticket (dans les projets des PR relues et REVIEW_PROJECTS)
    merged = []
    if feature:
        projects = [p["projet"] for p in prs] + [x.strip() for x in os.getenv("REVIEW_PROJECTS", "").split(",")]
        try:
            merged = pr_review.merged_feedback(feature, projects)
        except pr_review.BitbucketError as e:
            print(f"[REVUE PR] ⚠️ PR fusionnées de {feature} non lues : {e}")
        print(f"[REVUE PR] {len(merged)} PR fusionnée(s) de {feature} avec des remarques à reprendre.")
    tickets = []
    for key in list(dict.fromkeys(([feature] if feature else []) + keys))[:4]:
        try:
            tickets.append(f"{key} :\n{get_jira_issue_details(key)[:5000]}")
        except Exception as e:  # noqa: BLE001 — Jira facultatif pour une revue
            tickets.append(f"{key} : lecture impossible ({type(e).__name__})")
    conventions = os.getenv("DEV_CONVENTIONS_PATH", "").strip() or os.path.join(
        DATA_DIR, "odatio-specific-code-conventions-dev.md")
    if os.path.exists(conventions):
        dirs.append(os.path.dirname(conventions))
    prompt = render_prompt(
        "pr_review", relecteur=os.getenv("JIRA_EMAIL", "").split("@")[0] or "l'utilisateur", nb_prs=len(prs),
        token_saving_rules="\n" + render_prompt("token_saving_rules"),
        odatio_docs_block=odatio_docs_block(sys.executable, "revue"),
        fonctionnalite=(f"{feature} — " if feature else "") + prs[0]["titre"],
        jira="\n\n".join(tickets) or "(aucun ticket cité dans les titres, branches ou descriptions)",
        prs="\n".join(blocks),
        conventions=f"'{conventions}'" if os.path.exists(conventions) else "(fichier de conventions absent)",
        commentaires_existants="\n".join(f"- [{c['pr']}] {c['auteur']} — {c['fichier'] or 'général'}"
                                         + (f":{c['ligne']}" if c["ligne"] else "") + f" : {c['texte'][:200]}"
                                         for c in comments[:60]) or "(aucun)",
        commentaires_fusionnees="\n".join(
            f"- PR fusionnée « {m['pr']} » ({m['titre']}, {m['auteur']}) :\n" + "\n".join(
                f"  - {c['auteur']} — {c['fichier'] or 'général'}" + (f":{c['ligne']}" if c["ligne"] else "")
                + f" : {c['texte'][:300]}" for c in m["commentaires"][:25]) for m in merged)
        or "(aucune PR fusionnée commentée pour ce ticket)")
    model = os.getenv("CLAUDE_MODEL_REVIEW", "").strip() or "sonnet"
    effort = claude_effort("CLAUDE_EFFORT_REVIEW")
    turns = _env_int("REVIEW_MAX_TURNS", 40) + 15 * (len(prs) - 1)
    # Lecture seule : outils de lecture, plus la seule commande de la doc ODATiO si elle est configurée
    returncode, output, usage, limit_hit = run_claude(prompt, model, list(dict.fromkeys(dirs)),
                                                      REVIEW_TOOLS + odatio_docs_tools(sys.executable),
                                                      extra_args=("--max-turns", str(turns)), cwd=run_dir,
                                                      effort=effort, lean=lean_session())
    report_token_usage(f"REVUE-{feature or prs[0]['repere']}", "review-pr", model, usage, len(prompt), returncode,
                       effort)
    review = pr_review.parse_review(output)
    if limit_hit or not (review["resume"] or review["commentaires"]):
        print("[REVUE PR] ❌ Pas de résultat exploitable" + (" (quota atteint)." if limit_hit else "."))
        return 1
    # Chaque commentaire est rattaché à sa PR ; ancrage vérifié en Python (ligne hors du diff : commentaire général)
    # Placement : la PR (repère donné, sinon celle dont le diff contient le fichier), le chemin exact du diff, puis la
    # ligne si elle est dans le diff, sinon le fichier ; un fichier hors des PR reste un commentaire général
    single = prs[0]["repere"] if len(prs) == 1 else ""
    for comment in review["commentaires"]:
        label = comment.get("pr") if comment.get("pr") in maps else single or next(
            (l for l, m in maps.items() if pr_review.diff_path(m, comment["fichier"])), prs[0]["repere"])
        resolved, where = pr_review.placement(maps[label], comment["fichier"], comment["ligne"])
        comment.update(pr=label, fichier=resolved or comment["fichier"], ancrage=where,
                       ancrable=where == "ligne", publie=False)
    identifier = pr_review.feature_id(prs, feature)
    pr_review.save_result(identifier, {
        **review, "fonctionnalite": feature, "prs": [{k: p[k] for k in ("repere", "projet", "depot", "id", "titre",
                                                                        "auteur", "commit", "url", "fichiers")}
                                                     for p in prs],
        "lignes": {l: {path: {str(k): v for k, v in m.items()} for path, m in lm.items()} for l, lm in maps.items()},
        "date": datetime.now().isoformat(timespec="seconds")})
    print(f"[REVUE PR] ✅ Analyse terminée ({len(prs)} PR) : {review['verdict']}, {len(review['commentaires'])} "
          f"commentaire(s) proposé(s).")
    # Revue déposée dans le répertoire de connaissances partagé (projet Jira du ticket, sinon projet Bitbucket)
    saved = pr_review.load_result(identifier)
    project = feature.split("-", 1)[0] if feature else prs[0]["projet"]
    share_knowledge(pr_review.review_markdown(saved), project, "revue-pr",
                    f"Revue {feature or prs[0]['repere']} — {prs[0]['titre']}"[:90],
                    tickets=[feature] if feature else [], composants=sorted({p["depot"] for p in prs}),
                    tags=["revue-pr"])
    return 0


def main():
    parser = argparse.ArgumentParser(description="Agent Revue de PR - relecture des pull requests Bitbucket")
    parser.add_argument("--step", choices=["review-pr"], default="review-pr", help="Étape du traitement")
    parser.add_argument("--pr-url", action="append", default=[],
                        help="review-pr : adresse d'une pull request de la fonctionnalité (option répétable : toutes les "
                             "PR de la fonctionnalité sont relues ensemble)")
    parser.add_argument("--feature", default="", help="review-pr : ticket Jira de la fonctionnalité relue")
    # Arguments des autres étapes (délégation depuis agent-scrum-master) : ignorés, comme avant
    args, _ = parser.parse_known_args()
    sys.exit(run_pr_review(args.pr_url, args.feature))


if __name__ == "__main__":
    main()
