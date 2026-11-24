"""IHM d'agent-revue-pr (port 8508) : relecture assistée des pull requests Bitbucket des collaborateurs.

Page « Revue de PR » d'agent-scrum-master reprise telle quelle ; l'analyse lance `main.py --step review-pr` de ce
dépôt. Les secrets restent dans le .env de AGENT_DATA_DIR (et ceux que transmet le manager).
"""
import logging
import os
import re
import sys

import streamlit as st
from dotenv import load_dotenv

from agent_socle import ihm
from agent_socle import auth_tools, config_commune
from agent_socle.chemins import DATA_DIR
from agent_socle.ihm import interruption_cause, run_main_step
from tools import pr_review

st.set_page_config(page_title="Revue de PR", page_icon="🔍", layout="wide")

# Même chargement que les autres agents : .env de AGENT_DATA_DIR, puis les accès transmis par le manager
ENV_PATH = os.path.join(DATA_DIR, ".env")
os.environ.setdefault("AGENT_SHELL_CLAUDE_CONFIG_DIR", os.environ.get("CLAUDE_CONFIG_DIR", ""))
logging.getLogger("dotenv.main").setLevel(logging.ERROR)
load_dotenv(ENV_PATH, override=True)
config_commune.reappliquer()
if not os.getenv("CLAUDE_CONFIG_DIR", "").strip():
    os.environ["CLAUDE_CONFIG_DIR"] = os.environ["AGENT_SHELL_CLAUDE_CONFIG_DIR"]

# Connexion OIDC (AGENT_AUTH) : rien n'est affiché ni exécuté avant elle
CONNECTED = auth_tools.require_login(st)

# Travaux en cours (agent_socle.ihm) : tâches de l'agent lancées hors de la session, contexte de page de l'auteur
ihm.AGENT, ihm.CONTEXTE = "revue-pr", ()
ihm.restaurer_contexte()
ihm.travaux_en_cours()


REVIEW_VERDICTS = {"approuver": "✅ Peut être approuvée", "changements_demandes": "⛔ Changements à demander",
                   "a_discuter": "💬 À discuter avec l'auteur"}


REVIEW_SEVERITIES = {"bloquant": "🔴 Bloquant", "majeur": "🟠 Majeur", "mineur": "🟡 Mineur", "suggestion": "💡 Suggestion"}


def review_label(pr: dict) -> str:
    return f"{pr['projet']}/{pr['depot']} #{pr['id']} — {pr['titre']} ({pr['auteur']})"


def render_review_result(result: dict, current: list) -> None:
    """Résultat de la revue d'une fonctionnalité : verdict, cohérence, commentaires par PR à cocher et publier."""
    by_label = {p["repere"]: p for p in result.get("prs") or []}
    commits = {pr_review.pr_label(p): p.get("commit") for p in current}
    stale = any(commits.get(l) and commits[l] != p.get("commit") for l, p in by_label.items()) or \
        set(commits) != set(by_label)
    st.markdown(f"#### {REVIEW_VERDICTS.get(result['verdict'], result['verdict'])} · risque {result['risque']}")
    if stale:
        st.warning("Les PR ont changé depuis cette analyse (nouveaux commits, ou PR ajoutée / retirée) : relance-la.",
                   icon=":material/update:")
    st.markdown(result["resume"])
    if result.get("coherence"):
        st.markdown(f"**Cohérence entre les PR** : {result['coherence']}")
    if result.get("conformite_ticket"):
        st.caption(f"Ticket : {result['conformite_ticket']}")
    if result.get("points_positifs"):
        with st.expander(f"Points positifs ({len(result['points_positifs'])})"):
            st.markdown("\n".join(f"- {p}" for p in result["points_positifs"]))
    if result.get("questions"):
        with st.expander(f"Questions à poser aux auteurs ({len(result['questions'])})"):
            st.markdown("\n".join(f"- {q}" for q in result["questions"]))
    if result.get("tests"):
        st.caption(f"Tests : {result['tests']}")
    comments = result.get("commentaires") or []
    st.markdown(f"**Commentaires proposés ({len(comments)})** — coche ceux à publier, modifie-les si besoin.")
    key = "review_" + re.sub(r"\W", "_", result.get("fonctionnalite") or "+".join(by_label))
    for label in by_label:
        mine = [(i, c) for i, c in enumerate(comments) if c.get("pr") == label]
        if not mine:
            continue
        st.markdown(f"**{label}** — {by_label[label]['titre']} ({len(mine)})")
        for index, comment in mine:
            with st.container(border=True):
                where = comment["fichier"] + (f":{comment['ligne']}" if comment.get("ligne") else "")
                head = f"{REVIEW_SEVERITIES.get(comment['gravite'], comment['gravite'])} · `{where}`"
                if comment.get("publie"):
                    st.markdown(f"{head} — ✔️ publié")
                    st.caption(comment["message"])
                    continue
                where = comment.get("ancrage") or ("ligne" if comment.get("ancrable") else "general")
                st.checkbox(head + {"ligne": "", "fichier": " (posé sur le fichier : ligne hors des parties "
                                                             "modifiées)",
                                    "general": " (commentaire général : fichier hors de la PR)"}.get(where, ""),
                            key=f"{key}_pick_{index}", value=comment["gravite"] in ("bloquant", "majeur"))
                st.text_area("Commentaire", comment["message"] + (f"\n\n```\n{comment['suggestion']}\n```"
                                                                   if comment.get("suggestion") else ""),
                             key=f"{key}_text_{index}", label_visibility="collapsed", height=110)
    picked = [i for i, c in enumerate(comments) if not c.get("publie") and st.session_state.get(f"{key}_pick_{i}")]
    with st.container(horizontal=True, vertical_alignment="center"):
        publish = st.button(f"Publier sur Bitbucket ({len(picked)})", type="primary", icon=":material/send:",
                            disabled=not picked, key=f"{key}_publish")
        st.caption("Chaque commentaire est publié sous ton nom, sur la bonne ligne de la bonne PR. Rien n'est approuvé "
                   "ni refusé automatiquement.")
    if publish:
        done, errors = 0, []
        for index in picked:
            comment = comments[index]
            pr = by_label.get(comment.get("pr"))
            if not pr:
                errors.append(f"{comment['fichier']} : PR inconnue ({comment.get('pr')})")
                continue
            lines_map = {path: {int(k): v for k, v in m.items()}
                         for path, m in ((result.get("lignes") or {}).get(comment["pr"]) or {}).items()}
            text = (st.session_state.get(f"{key}_text_{index}") or comment["message"]).strip()
            try:
                pr_review.post_comment(pr["projet"], pr["depot"], pr["id"], text, comment["fichier"],
                                       comment.get("ligne"), lines_map)
                comment["publie"], comment["message"] = True, text
                done += 1
            except pr_review.BitbucketError as e:
                errors.append(f"{comment['pr']} {comment['fichier']}:{comment.get('ligne')} — {e}")
        pr_review.save_result(pr_review.feature_id(list(by_label.values()), result.get("fonctionnalite", "")), result)
        if done:
            st.success(f"{done} commentaire(s) publié(s).", icon=":material/task_alt:")
        for error in errors:
            st.error(error)
        if done and not errors:
            st.rerun()


def render_review_tab() -> None:
    st.markdown("### Relire les fonctionnalités de tes collaborateurs")
    st.caption("Une fonctionnalité = toutes ses pull requests (backend, interface, Studio…), reliées par leur ticket "
               "Jira et relues ENSEMBLE : diff et code de chaque PR, ticket, conventions de l'équipe, commentaires déjà "
               "posés. Tu choisis ce qui est publié.")
    if not pr_review.configured():
        st.warning("Renseigne BITBUCKET_URL et BITBUCKET_HTTP_TOKEN dans l'onglet Configuration.",
                   icon=":material/key:")
        return
    with st.container(horizontal=True, vertical_alignment="bottom"):
        role = st.segmented_control("PR", ["À relire", "Où je participe", "Les miennes", "Par projet"],
                                    default="À relire", key="review_role") or "À relire"
        projects_input = ""
        if role == "Par projet":
            projects_input = st.text_input("Projets Bitbucket", key="review_projects_list",
                                           value=os.getenv("REVIEW_PROJECTS", "").strip() or "OXY",
                                           help="Clés de projets Bitbucket séparées par des virgules (ex. OXY, "
                                                "APPAREL) : toutes leurs PR ouvertes, quel que soit ton rôle. Valeur "
                                                "par défaut : REVIEW_PROJECTS du .env.").strip().upper()
        refresh = st.button("Actualiser", icon=":material/refresh:", key="review_refresh")
    roles = {"À relire": "REVIEWER", "Où je participe": "PARTICIPANT", "Les miennes": "AUTHOR"}
    cache_key = (f"review_projet_{projects_input}" if role == "Par projet" else f"review_inbox_{roles[role]}")
    if refresh or cache_key not in st.session_state:
        try:
            if role == "Par projet":
                with st.spinner(f"Lecture des PR ouvertes de {projects_input or '…'}…"):
                    found, problems = pr_review.project_prs(projects_input.split(","))
                for problem in problems[:5]:
                    st.warning(problem, icon=":material/warning:")
                st.session_state[cache_key] = found
            else:
                st.session_state[cache_key] = pr_review.review_inbox(roles[role])
        except pr_review.BitbucketError as e:
            st.error(str(e))
            st.session_state[cache_key] = []
    features = {g["cle"]: g for g in pr_review.group_by_feature(st.session_state.get(cache_key) or [])}
    url = st.text_input("Ou adresse d'une PR de la fonctionnalité", key="review_url",
                        placeholder="https://git.kiscloud.io/projects/APPAREL/repos/odatio-app/pull-requests/42")
    group = None
    if url.strip():
        try:
            project, repo, number = pr_review.parse_pr_url(url)
            pr = pr_review.pr_details(project, repo, number)
            key = (pr["jira"] or [None])[0] or f"{project}/{repo}#{number}"
            group = features.get(key) or {"cle": key, "titre": pr["titre"], "prs": [pr]}
            if pr["id"] not in [p["id"] for p in group["prs"] if p["depot"] == repo]:
                group = {**group, "prs": group["prs"] + [pr]}
        except (ValueError, pr_review.BitbucketError) as e:
            st.error(str(e))
    elif features:
        choice = st.selectbox(f"Fonctionnalités ({len(features)})", list(features), key="review_choice",
                              format_func=lambda k: f"{k} — {features[k]['titre']} ({len(features[k]['prs'])} PR)")
        group = features.get(choice)
    else:
        st.info("Aucune pull request ouverte dans cette liste.", icon=":material/inbox:")
    if not group:
        return
    key = group["cle"]
    has_ticket = bool(pr_review.JIRA_KEY.fullmatch(key))
    # Toutes les PR ouvertes du ticket dans les projets concernés (une fois par fonctionnalité, ou à la demande)
    found_key = f"review_found_{key}"
    with st.container(border=True):
        extra = st.text_input("Autres projets Bitbucket où chercher (facultatif)", key=f"review_projects_{key}",
                              placeholder="ex. STD, STUDIO", disabled=not has_ticket)
        search = st.button("Rechercher les autres PR de la fonctionnalité", icon=":material/travel_explore:",
                           key=f"review_search_{key}", disabled=not has_ticket)
        if has_ticket and (search or found_key not in st.session_state):
            projects = [p["projet"] for p in group["prs"]] + [p.strip() for p in extra.split(",") if p.strip()]
            with st.spinner(f"Recherche des PR ouvertes citant {key}…"):
                st.session_state[found_key] = pr_review.feature_prs(key, projects, group["prs"])
        prs = st.session_state.get(found_key) or group["prs"]
        st.markdown(f"**{key} — {group['titre']}** : {len(prs)} PR"
                    + ("" if has_ticket else " (aucun ticket Jira cité : la PR est relue seule)"))
        chosen = []
        for pr in prs:
            label = pr_review.pr_label(pr)
            if st.checkbox(f"{review_label(pr)} · `{pr['source']}` → `{pr['cible']}`", value=True,
                           key=f"review_pick_{key}_{label}"):
                chosen.append(pr)
            if pr.get("url"):
                st.caption(f"[Ouvrir dans Bitbucket]({pr['url']})")
        identifier = pr_review.feature_id(chosen, key if has_ticket else "")
        result = pr_review.load_result(identifier) if chosen else {}
        if st.button(("Relancer l'analyse" if result else "Analyser la fonctionnalité") + f" ({len(chosen)} PR)",
                     type="primary" if not result else "secondary", icon=":material/troubleshoot:",
                     disabled=not chosen, key=f"review_run_{identifier}"):
            cmd = [sys.executable, "main.py", "--step", "review-pr"] + (["--feature", key] if has_ticket else [])
            for pr in chosen:
                cmd += ["--pr-url", pr.get("url") or f"{pr_review.base_url()}/projects/{pr['projet']}/repos/"
                                                     f"{pr['depot']}/pull-requests/{pr['id']}"]
            with st.spinner(f"Analyse de la fonctionnalité ({len(chosen)} PR : code, ticket, conventions)…"):
                code = run_main_step(cmd)
            if code == 0:
                st.rerun()
            st.error(f"Analyse interrompue : {interruption_cause(code)}.")
        if result:
            render_review_result(result, chosen)


st.title("🔍 Revue de PR")
if CONNECTED:
    st.caption(f"Connecté : {auth_tools.label(CONNECTED)}")
render_review_tab()

# Choix de la page enregistrés pour la reconnexion (.tmp/sessions/<auteur>/<agent>.json)
ihm.memoriser_contexte()
