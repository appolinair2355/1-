# Bot de Prédiction Telegram

Bot de prédiction de costumes pour Telegram, déployable sur Render.com.

## Configuration

Toutes les configurations sont dans `config.py`:
- API Telegram (ID, Hash, Token)
- IDs des canaux (source et prédiction)
- Numéros exclus
- Cycles de costumes

## Règles de prédiction

1. **Logique inversée**:
   - Numéro **impair** reçu → prédit avec cycle **pair**
   - Numéro **pair** reçu → prédit avec cycle **impair**

2. **Numéros exclus** (ni déclencheurs ni prédictions):
   - 1086-1090
   - 1266-1270
   - 1386-1390

## Déploiement sur Render.com

1. Créer un compte sur [Render.com](https://render.com)
2. Connecter votre repository GitHub/GitLab
3. Cliquer sur "New" → "Web Service"
4. Sélectionner votre repository
5. Configurer:
   - **Name**: prediction-bot
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Plan**: Free
6. Cliquer "Create Web Service"

Le bot démarrera automatiquement et écoutera sur le port 10000.

## Commandes Admin

Envoyez ces commandes en message privé au bot:

- `/start` - Menu d'aide
- `/test <numero>` - Tester une prédiction
- `/info` - Informations du bot
- `/stats` - Statistiques et cycles
- `/excluded` - Liste des numéros exclus
- `/restart` - Redémarrer le bot

## Structure des fichiers

```
├── config.py          # Configuration (API, IDs, règles)
├── main.py            # Code principal (bot + serveur web)
├── requirements.txt   # Dépendances Python
└── render.yaml        # Configuration Render.com
```

## Logs

Les logs sont visibles dans le dashboard Render.com → Service → Logs.
