# 🏋️ Bot Nutrition - Prise de Masse

Bot Telegram pour suivre ta consommation de macros et atteindre tes objectifs de prise de masse.

## 🎯 Objectifs configurés

| Macro | Objectif |
|-------|----------|
| Calories | 3100 kcal |
| Protéines | 160g |
| Lipides | 90g |
| Glucides | 400g |

## ✨ Fonctionnalités

- **Tracking simple**: Envoie "200g poulet" ou "3 oeufs" et le bot calcule tout
- **Feedback instantané**: À chaque entrée, vois ce qu'il te reste à consommer
- **Rappels automatiques**: 12h, 18h, 23h (recap)
- **Historique**: 3 derniers jours
- **170+ aliments** dans la base de données
- **Annulation**: `/undo` pour corriger une erreur

## 📋 Commandes

| Commande | Description |
|----------|-------------|
| `/start` | Message de bienvenue |
| `/status` | État actuel du jour |
| `/history` | 3 derniers jours |
| `/undo` | Annuler dernière entrée |
| `/add nom\|kcal\|prot\|lip\|gluc` | Ajouter un aliment |
| `/search terme` | Chercher un aliment |
| `/list` | Liste des catégories |
| `/help` | Aide détaillée |

## 🚀 Déploiement

### Étape 1: Créer le bot Telegram

1. Va sur Telegram et cherche **@BotFather**
2. Envoie `/newbot`
3. Choisis un nom (ex: "Nutrition Franck")
4. Choisis un username (ex: `franck_nutrition_bot`)
5. **Copie le token** qui ressemble à: `7123456789:AAHxxx...`

### Étape 2: Récupérer ton Chat ID

1. Va sur Telegram et cherche **@userinfobot**
2. Envoie `/start`
3. **Copie ton "Id"** (c'est un nombre genre `123456789`)

### Étape 3: GitHub

1. Va sur https://github.com/new
2. Nom du repo: `nutrition-bot`
3. **Private** (recommandé)
4. Clique "Create repository"

5. Dans ton terminal local:
```bash
# Clone le repo
git clone https://github.com/TON_USERNAME/nutrition-bot.git
cd nutrition-bot

# Copie les fichiers du bot (main.py, foods_database.py, requirements.txt)
# Puis:
git add .
git commit -m "Initial commit"
git push origin main
```

### Étape 4: Railway

1. Va sur https://railway.app et connecte-toi avec GitHub

2. Clique **"New Project"** → **"Deploy from GitHub repo"**

3. Sélectionne ton repo `nutrition-bot`

4. Une fois le projet créé, va dans **Variables** (onglet en haut)

5. Ajoute ces variables:
   ```
   TELEGRAM_TOKEN = 7123456789:AAHxxx... (ton token BotFather)
   CHAT_ID = 123456789 (ton ID de userinfobot)
   ```

6. Railway va automatiquement redéployer

7. Vérifie dans **Deployments** que le statut est ✅

### Étape 5: Tester

1. Va sur Telegram
2. Cherche ton bot par son username
3. Envoie `/start`
4. Teste avec `200g poulet`

## 🔧 Configuration avancée

### Modifier les objectifs

Dans `main.py`, modifie le dictionnaire `DAILY_GOALS`:

```python
DAILY_GOALS = {
    "kcal": 3100,      # Modifier ici
    "proteines": 160,   # Modifier ici
    "lipides": 90,      # Modifier ici
    "glucides": 400     # Modifier ici
}
```

### Ajouter des aliments

Soit via la commande `/add`:
```
/add galette de riz|380|8|2|82
```

Soit directement dans `foods_database.py`:
```python
"mon aliment": (kcal, proteines, lipides, glucides),
```

### Modifier les heures de rappel

Dans `main.py`, fonction `setup_scheduler()`:
```python
scheduler.add_job(..., hour=12, ...)  # Rappel midi
scheduler.add_job(..., hour=18, ...)  # Rappel soir
scheduler.add_job(..., hour=23, ...)  # Récap
```

## 📁 Structure des fichiers

```
nutrition-bot/
├── main.py              # Bot principal
├── foods_database.py    # Base de données 170+ aliments
├── requirements.txt     # Dépendances Python
└── README.md           # Ce fichier
```

## ⚠️ Notes importantes

- Les données sont en mémoire → reset si Railway redéploie
- Pour une persistance, il faudrait ajouter une base de données (Redis, PostgreSQL...)
- Le bot garde l'historique des 3 derniers jours max

## 🐛 Dépannage

**Le bot ne répond pas:**
- Vérifie que le token est correct dans Railway
- Check les logs dans Railway → Deployments → View Logs

**Les rappels ne fonctionnent pas:**
- Vérifie que CHAT_ID est bien configuré
- Le bot doit tourner en continu sur Railway

**Aliment non reconnu:**
- Utilise `/search` pour trouver le bon nom
- Ou ajoute-le avec `/add`

---

Made with 💪 pour la prise de masse
