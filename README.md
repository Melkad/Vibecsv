# Vibecsv
agent csv

---

# csv-data-analyst

Agent analyste de données conversationnel construit avec le SDK Agent de Mistral (`mistralai-agents`).

- L'utilisateur donne un **lien vers un CSV dans son Google Drive** et pose des questions en langage naturel.
- L'agent utilise le **connecteur Google Drive** (enregistré dans Studio, OAuth Google) pour localiser et lire le fichier.
- Il dispose de **4 outils fixes côté client** (aucune exécution de code arbitraire, pas d'interpréteur de code, pas de bac à sable) :
  - `load_csv` : charge le contenu CSV dans la session (mémorisé pour toute la conversation) ;
  - `describe_columns` : décrit chaque colonne (type, nulls, distincts, min/max/moyenne, valeurs fréquentes) ;
  - `filter_rows` : filtre les lignes (`==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`, `isin`) ;
  - `aggregate_by_group` : agrégats par groupe (`sum`, `mean`, `median`, `min`, `max`, `count`, `nunique`, `std`).
- Toutes les réponses citent des **chiffres réels** issus des outils.
- La **mémoire** est assurée par la session : le fichier chargé et l'historique de la conversation persistent entre les questions de suivi (les sessions déployées sont stockées par Mistral et survivent aux redémarrages).

## Prérequis

1. Un compte Mistral avec une **clé API** (`MISTRAL_API_KEY`, créée dans [console.mistral.ai](https://console.mistral.ai) → API keys).
2. Un **connecteur Google Drive** enregistré dans votre workspace Studio : [console.mistral.ai/build/connectors](https://console.mistral.ai/build/connectors) → connecteur Google Drive → authentification OAuth avec votre compte Google. Par défaut l'agent référence le connecteur nommé `google_drive_mcp` ; si vous l'avez nommé autrement, changez `DRIVE_CONNECTOR_NAME` dans `main.py`.

## Test local des outils (sans clé API)

```bash
pip install mistralai-agents pandas
python tests/test_tools.py
```

## Déploiement géré sur Mistral Cloud

```bash
export MISTRAL_API_KEY=...        # clé API de votre workspace
pip install uv                     # ou: curl -LsSf https://astral.sh/uv/install.sh | sh
uv lock                            # génère uv.lock (déjà présent dans ce dépôt)
agents deploy --name csv-data-analyst .
```

`agents deploy` construit l'image à partir du `Dockerfile` et du commit, et déploie un **worker géré par Mistral** dans votre workspace. L'agent apparaît ensuite dans Studio et dans `agents list`.

Pour discuter en ligne de commande avec l'agent déployé :

```bash
agents chat --agent csv-data-analyst
```

## Interagir avec l'agent via Vibe

Vibe se connecte à votre workspace Studio via le **serveur MCP Mistral** :

```bash
export MISTRAL_API_KEY=...
vibe mcp add mistralai \
  --url https://api.mistral.ai/mcp \
  --transport streamable-http \
  --api-key-env MISTRAL_API_KEY
```

Dans une session Vibe, les outils Studio du serveur `mistralai` (groupés par capacité : agents, sessions, etc.) permettent de :

1. lister les agents déployés de votre workspace (`agents list` côté CLI donne la même vue) ;
2. **créer une session** sur `csv-data-analyst` (ou reprendre une session existante par son id) ;
3. **envoyer vos messages** dans la session : donnez le lien Google Drive du CSV, posez vos questions, puis vos questions de suivi dans la même session — l'agent se souvient du fichier et de la conversation.

Exemple de session dans Vibe : « Crée une session sur l'agent `csv-data-analyst`, puis envoie : "Voici mon fichier https://drive.google.com/file/d/... — quelles sont les ventes totales par région ?" », puis « Et pour le mois de février uniquement ? ».

## Structure

- `main.py` : définition de l'agent, des 4 outils et du connecteur Google Drive.
- `tests/test_tools.py` : tests locaux des outils sur `sample.csv`.
- `Dockerfile`, `.python-version`, `pyproject.toml`, `uv.lock` : packaging pour `agents deploy`.
