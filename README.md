# agent-revue-pr

Relecture assistée des pull requests Bitbucket d'une fonctionnalité (lecture seule ; publication d'un commentaire
uniquement sur action de l'utilisateur). Code repris tel quel d'agent-scrum-master (phase 3 du découpage).

| | |
|---|---|
| IHM | `streamlit run app.py` (port 8508) |
| CLI | `python main.py --step review-pr --pr-url <adresse> [--pr-url …] [--feature <TICKET>]` |
| Dépendance interne | `agent-socle` (seule) : `pip install -e ../agent-socle` pendant le chantier |
| Données | `.tmp/pr_review` et `.env` de `AGENT_DATA_DIR` (défaut `..\agent-scrum-master`), jamais copiés |
| Conventions | `DEV_CONVENTIONS_PATH`, défaut `odatio-specific-code-conventions-dev.md` de `AGENT_DATA_DIR` |

`agent-scrum-master` délègue : `python main.py --step review-pr …` relance ce `main.py` (`AGENT_REVUE_PR_DIR`).
