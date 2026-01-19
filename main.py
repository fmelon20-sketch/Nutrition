import os
import re
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from foods_database import FOODS_DATABASE, STANDARD_UNITS, get_food_info, search_foods

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")  # Ton chat ID pour les rappels
TIMEZONE = ZoneInfo("Europe/Paris")

# Objectifs journaliers
DAILY_GOALS = {
    "kcal": 3100,
    "proteines": 160,
    "lipides": 90,
    "glucides": 400
}

# Stockage des données (en mémoire, reset au redémarrage du serveur)
# Structure: {date_str: {"entries": [...], "totals": {...}}}
daily_data = {}
last_entry = None  # Pour le /undo

# ==================== FONCTIONS UTILITAIRES ====================

def get_today_key() -> str:
    """Retourne la clé pour aujourd'hui au format YYYY-MM-DD"""
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")

def init_day(date_key: str):
    """Initialise une nouvelle journée"""
    if date_key not in daily_data:
        daily_data[date_key] = {
            "entries": [],
            "totals": {"kcal": 0, "proteines": 0, "lipides": 0, "glucides": 0}
        }

def get_remaining() -> dict:
    """Calcule ce qu'il reste à consommer aujourd'hui"""
    today = get_today_key()
    init_day(today)
    
    totals = daily_data[today]["totals"]
    return {
        "kcal": DAILY_GOALS["kcal"] - totals["kcal"],
        "proteines": DAILY_GOALS["proteines"] - totals["proteines"],
        "lipides": DAILY_GOALS["lipides"] - totals["lipides"],
        "glucides": DAILY_GOALS["glucides"] - totals["glucides"]
    }

def create_progress_bar(current: float, goal: float, length: int = 8) -> str:
    """Crée une barre de progression compacte"""
    pct = min(100, (current / goal) * 100) if goal > 0 else 0
    filled = int(pct / (100 / length))
    empty = length - filled
    bar = "●" * filled + "○" * empty
    return f"{bar} {pct:.0f}%"

def format_status(totals: dict, remaining: dict, show_entries: bool = False) -> str:
    """Formate le message de statut"""
    msg = "📊 **Statut du jour**\n\n"

    # Tableau compact des macros
    macros_data = [
        ("🔥", "Kcal", totals['kcal'], DAILY_GOALS['kcal'], "", remaining['kcal']),
        ("🥩", "Prot", totals['proteines'], DAILY_GOALS['proteines'], "g", remaining['proteines']),
        ("🧈", "Lip", totals['lipides'], DAILY_GOALS['lipides'], "g", remaining['lipides']),
        ("🍚", "Gluc", totals['glucides'], DAILY_GOALS['glucides'], "g", remaining['glucides']),
    ]

    for emoji, name, current, goal, unit, rest in macros_data:
        bar = create_progress_bar(current, goal)
        if rest > 0:
            rest_txt = f"-{rest:.0f}{unit}"
        elif rest < 0:
            rest_txt = f"+{abs(rest):.0f}{unit}⚠️"
        else:
            rest_txt = "✓"
        msg += f"{emoji} {name}: {current:.0f}/{goal}{unit}\n"
        msg += f"    {bar} ({rest_txt})\n\n"

    return msg

def parse_food_entry(text: str) -> list:
    """
    Parse une entrée alimentaire du type "200g pâtes" ou "3 oeufs"
    Retourne une liste de tuples (aliment, quantité_en_g, macros)
    """
    results = []
    
    # Patterns possibles:
    # "200g pâtes", "200 g pâtes", "200 pâtes", "pâtes 200g"
    # "3 oeufs", "1 banane", "2 yaourts"
    # "1 verre de lait", "1 bouteille skyr"
    
    # Nettoyer le texte
    text = text.lower().strip()
    
    # Séparer par virgules ou "et" pour plusieurs aliments
    items = re.split(r'[,\n]+|\bet\b', text)
    
    for item in items:
        item = item.strip()
        if not item:
            continue
        
        # Pattern: nombre + unité optionnelle + aliment
        # Ex: "200g pates", "3 oeufs", "1 verre lait"
        pattern = r'^(\d+(?:[.,]\d+)?)\s*(g|gr|grammes?|ml|cl|l|kg)?\s*(?:de\s+|d\')?(.+)$'
        match = re.match(pattern, item)
        
        if not match:
            # Pattern inversé: aliment + nombre + unité
            pattern_inv = r'^(.+?)\s+(\d+(?:[.,]\d+)?)\s*(g|gr|grammes?|ml|cl|l|kg)?$'
            match = re.match(pattern_inv, item)
            if match:
                food_name = match.group(1).strip()
                quantity = float(match.group(2).replace(',', '.'))
                unit = match.group(3) or ''
            else:
                # Pas de pattern reconnu
                logger.warning(f"Pattern non reconnu: {item}")
                continue
        else:
            quantity = float(match.group(1).replace(',', '.'))
            unit = match.group(2) or ''
            food_name = match.group(3).strip()
        
        # Nettoyer le nom de l'aliment
        food_name = food_name.strip()
        
        # Convertir en grammes
        if unit in ['kg']:
            grams = quantity * 1000
        elif unit in ['cl']:
            grams = quantity * 10
        elif unit in ['l']:
            grams = quantity * 1000
        elif unit in ['ml']:
            grams = quantity
        elif unit in ['g', 'gr', 'gramme', 'grammes', '']:
            # Si pas d'unité, vérifier si c'est une unité standard
            if unit == '' and quantity <= 20:  # Probablement une quantité d'unités
                # Chercher dans les unités standards
                unit_grams = None
                for std_name, std_grams in STANDARD_UNITS.items():
                    if std_name in food_name or food_name in std_name:
                        unit_grams = std_grams
                        break
                
                if unit_grams:
                    grams = quantity * unit_grams
                else:
                    # Vérifier si l'aliment a une unité standard
                    food_info = get_food_info(food_name)
                    if food_info and food_name in STANDARD_UNITS:
                        grams = quantity * STANDARD_UNITS[food_name]
                    else:
                        grams = quantity  # Assume grammes par défaut
            else:
                grams = quantity
        else:
            grams = quantity
        
        # Chercher l'aliment dans la base
        food_info = get_food_info(food_name)
        
        if food_info:
            kcal, prot, lip, gluc = food_info
            # Calculer pour la quantité
            ratio = grams / 100
            macros = {
                "kcal": kcal * ratio,
                "proteines": prot * ratio,
                "lipides": lip * ratio,
                "glucides": gluc * ratio
            }
            results.append((food_name, grams, macros))
        else:
            # Aliment non trouvé
            results.append((food_name, grams, None))
    
    return results

# ==================== HANDLERS TELEGRAM ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /start"""
    msg = """🏋️ **Nutrition Bot** - Prise de Masse

📊 **Objectifs journaliers:**
🔥 3100 kcal | 🥩 160g prot | 🧈 90g lip | 🍚 400g gluc

💬 **Comment m'utiliser:**
Envoie ce que tu manges: `200g pâtes` ou `3 oeufs`

📋 **Commandes:**
/status /history /add /undo /search /help

Let's go! 💪"""

    await update.message.reply_text(msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /help"""
    msg = """📖 **Aide**

**Formats:** `200g poulet`, `3 oeufs`, `1 verre lait`

**Unités:** œuf=60g, verre=200ml, yaourt=125g, banane=120g

**Ajout rapide:** `/add 150kcal 10p 5l 8g`
**Sauvegarder:** `/add nom|kcal|prot|lip|gluc`

**Rappels:** 12h, 18h, 23h

/status /history /undo /search /list"""

    await update.message.reply_text(msg, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /status"""
    today = get_today_key()
    init_day(today)
    
    totals = daily_data[today]["totals"]
    remaining = get_remaining()
    
    msg = format_status(totals, remaining)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /history - affiche les 3 derniers jours"""
    msg = "📅 **Historique**\n\n"

    today = datetime.now(TIMEZONE)

    for i in range(3):
        date = today - timedelta(days=i)
        date_key = date.strftime("%Y-%m-%d")
        date_display = date.strftime("%d/%m")

        if i == 0:
            label = "Auj."
        elif i == 1:
            label = "Hier"
        else:
            label = date.strftime("%a")

        if date_key in daily_data and daily_data[date_key]["entries"]:
            totals = daily_data[date_key]["totals"]
            prot_pct = (totals["proteines"] / DAILY_GOALS["proteines"]) * 100

            if prot_pct >= 90:
                status = "🟢"
            elif prot_pct >= 70:
                status = "🟡"
            else:
                status = "🔴"

            msg += f"{status} **{label}** {date_display}\n"
            msg += f"   {totals['kcal']:.0f}kcal | {totals['proteines']:.0f}p | {totals['lipides']:.0f}l | {totals['glucides']:.0f}g\n\n"
        else:
            msg += f"⚪ **{label}** {date_display} - Aucune donnée\n\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /undo - annule la dernière entrée"""
    global last_entry
    
    today = get_today_key()
    init_day(today)
    
    if not daily_data[today]["entries"]:
        await update.message.reply_text("❌ Aucune entrée à annuler aujourd'hui.")
        return
    
    # Retirer la dernière entrée
    last = daily_data[today]["entries"].pop()
    
    # Mettre à jour les totaux
    daily_data[today]["totals"]["kcal"] -= last["macros"]["kcal"]
    daily_data[today]["totals"]["proteines"] -= last["macros"]["proteines"]
    daily_data[today]["totals"]["lipides"] -= last["macros"]["lipides"]
    daily_data[today]["totals"]["glucides"] -= last["macros"]["glucides"]
    
    msg = f"↩️ **Entrée annulée:**\n"
    msg += f"   {last['quantity']:.0f}g {last['food']}\n"
    msg += f"   ({last['macros']['kcal']:.0f} kcal, {last['macros']['proteines']:.1f}g prot)\n\n"
    
    remaining = get_remaining()
    msg += f"⏳ **Reste:** {remaining['kcal']:.0f} kcal | {remaining['proteines']:.0f}g prot"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def add_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /add - deux modes disponibles:
    1. Ajout rapide: /add 30g 150kcal 10p 5l 8g (ajoute directement au journal)
    2. Ajout base: /add nom|kcal|prot|lip|gluc (sauvegarde dans la base)
    """
    global last_entry

    if not context.args or len(context.args) < 1:
        msg = """📝 **Ajouter**

**Ajout rapide:** `/add 150kcal 10p 5l 8g`
**Sauvegarder:** `/add nom|kcal|prot|lip|gluc`"""
        await update.message.reply_text(msg, parse_mode='Markdown')
        return

    full_args = ' '.join(context.args)

    # Mode 2: Ajout à la base (contient |)
    if '|' in full_args:
        parts = full_args.split('|')

        if len(parts) != 5:
            await update.message.reply_text("❌ Format: `/add nom|kcal|prot|lip|gluc`", parse_mode='Markdown')
            return

        try:
            name = parts[0].strip().lower()
            kcal = float(parts[1])
            prot = float(parts[2])
            lip = float(parts[3])
            gluc = float(parts[4])

            FOODS_DATABASE[name] = (kcal, prot, lip, gluc)

            msg = f"✅ **{name}** ajouté (100g)\n"
            msg += f"🔥{kcal} | 🥩{prot}g | 🧈{lip}g | 🍚{gluc}g\n\n"
            msg += f"→ Utilise: `{name} 100g`"

            await update.message.reply_text(msg, parse_mode='Markdown')

        except ValueError:
            await update.message.reply_text("❌ Les valeurs doivent être des nombres.", parse_mode='Markdown')
        return

    # Mode 1: Ajout rapide (format: /add 30g 150kcal 10p 5l 8g)
    # Pattern pour parser: quantité + macros
    pattern = r'(\d+(?:[.,]\d+)?)\s*(g|gr|grammes?)\s+(\d+(?:[.,]\d+)?)\s*kcal\s+(\d+(?:[.,]\d+)?)\s*p\s+(\d+(?:[.,]\d+)?)\s*l\s+(\d+(?:[.,]\d+)?)\s*g'
    match = re.match(pattern, full_args.lower())

    if not match:
        # Essayer format alternatif: /add 150kcal 10p 5l 8g (sans quantité, assume 1 portion)
        pattern_no_qty = r'(\d+(?:[.,]\d+)?)\s*kcal\s+(\d+(?:[.,]\d+)?)\s*p\s+(\d+(?:[.,]\d+)?)\s*l\s+(\d+(?:[.,]\d+)?)\s*g'
        match_no_qty = re.match(pattern_no_qty, full_args.lower())

        if match_no_qty:
            grams = 100  # Assume 100g par défaut
            kcal = float(match_no_qty.group(1).replace(',', '.'))
            prot = float(match_no_qty.group(2).replace(',', '.'))
            lip = float(match_no_qty.group(3).replace(',', '.'))
            gluc = float(match_no_qty.group(4).replace(',', '.'))
        else:
            msg = "❌ Format non reconnu.\n\n"
            msg += "**Ajout rapide:** `/add 30g 150kcal 10p 5l 8g`\n"
            msg += "**Sauvegarder:** `/add nom|kcal|prot|lip|gluc`"
            await update.message.reply_text(msg, parse_mode='Markdown')
            return
    else:
        grams = float(match.group(1).replace(',', '.'))
        kcal = float(match.group(3).replace(',', '.'))
        prot = float(match.group(4).replace(',', '.'))
        lip = float(match.group(5).replace(',', '.'))
        gluc = float(match.group(6).replace(',', '.'))

    # Ajouter directement au journal du jour
    today = get_today_key()
    init_day(today)

    macros = {
        "kcal": kcal,
        "proteines": prot,
        "lipides": lip,
        "glucides": gluc
    }

    entry = {
        "food": f"ajout manuel ({grams:.0f}g)",
        "quantity": grams,
        "macros": macros,
        "time": datetime.now(TIMEZONE).strftime("%H:%M")
    }

    daily_data[today]["entries"].append(entry)
    last_entry = entry

    # Mettre à jour les totaux
    for key in ["kcal", "proteines", "lipides", "glucides"]:
        daily_data[today]["totals"][key] += macros[key]

    remaining = get_remaining()
    totals = daily_data[today]["totals"]

    msg = f"✅ **Ajout rapide** ({grams:.0f}g)\n"
    msg += f"🔥{kcal:.0f} | 🥩{prot:.0f}g | 🧈{lip:.0f}g | 🍚{gluc:.0f}g\n\n"

    msg += "**Progression:**\n"
    for key, emoji in [("kcal", "🔥"), ("proteines", "🥩"), ("lipides", "🧈"), ("glucides", "🍚")]:
        pct = min(100, (totals[key] / DAILY_GOALS[key]) * 100)
        bar = create_progress_bar(totals[key], DAILY_GOALS[key])
        rest = remaining[key]
        unit = "" if key == "kcal" else "g"
        rest_txt = f"-{rest:.0f}{unit}" if rest > 0 else "✓"
        msg += f"{emoji} {bar} ({rest_txt})\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def search_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /search - chercher un aliment"""
    if not context.args:
        await update.message.reply_text("Usage: `/search poulet`", parse_mode='Markdown')
        return
    
    query = ' '.join(context.args)
    results = search_foods(query)
    
    if not results:
        await update.message.reply_text(f"❌ Aucun aliment trouvé pour '{query}'")
        return
    
    msg = f"🔍 **Résultats pour '{query}':**\n\n"
    
    for food in results[:8]:
        info = FOODS_DATABASE[food]
        msg += f"• **{food}** (100g)\n"
        msg += f"   {info[0]} kcal | {info[1]}g P | {info[2]}g L | {info[3]}g G\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def list_foods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour /list - liste les catégories d'aliments"""
    msg = """📋 **Catégories disponibles:**

• Viandes (poulet, boeuf, porc, dinde...)
• Poissons (saumon, thon, cabillaud...)
• Œufs & produits laitiers
• Féculents (pâtes, riz, pain...)
• Légumes (~35 variétés)
• Fruits (~25 variétés)
• Oléagineux & graines
• Huiles & matières grasses
• Compléments (whey, barres...)

**Total: ~170 aliments**

Utilise `/search [terme]` pour chercher un aliment spécifique."""

    await update.message.reply_text(msg, parse_mode='Markdown')

async def handle_food_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pour les messages texte (entrées alimentaires)"""
    global last_entry

    text = update.message.text

    # Ignorer les commandes
    if text.startswith('/'):
        return

    today = get_today_key()
    init_day(today)

    # Parser l'entrée
    entries = parse_food_entry(text)

    if not entries:
        await update.message.reply_text("❓ Je n'ai pas compris. Essaie: `200g poulet` ou `3 oeufs`", parse_mode='Markdown')
        return

    msg = "✅ **Enregistré**\n\n"
    not_found = []

    for food_name, grams, macros in entries:
        if macros:
            entry = {
                "food": food_name,
                "quantity": grams,
                "macros": macros,
                "time": datetime.now(TIMEZONE).strftime("%H:%M")
            }
            daily_data[today]["entries"].append(entry)
            last_entry = entry

            for key in ["kcal", "proteines", "lipides", "glucides"]:
                daily_data[today]["totals"][key] += macros[key]

            msg += f"• {grams:.0f}g {food_name}\n"
            msg += f"  🔥{macros['kcal']:.0f} | 🥩{macros['proteines']:.0f}g | 🧈{macros['lipides']:.0f}g | 🍚{macros['glucides']:.0f}g\n\n"
        else:
            not_found.append(food_name)

    if not_found:
        msg += f"⚠️ Non trouvé: {', '.join(not_found)}\n"
        msg += "→ `/add 150kcal 10p 5l 8g`\n\n"

    remaining = get_remaining()
    totals = daily_data[today]["totals"]

    msg += "**Progression:**\n"
    for key, emoji in [("kcal", "🔥"), ("proteines", "🥩"), ("lipides", "🧈"), ("glucides", "🍚")]:
        bar = create_progress_bar(totals[key], DAILY_GOALS[key])
        rest = remaining[key]
        unit = "" if key == "kcal" else "g"
        rest_txt = f"-{rest:.0f}{unit}" if rest > 0 else "✓"
        msg += f"{emoji} {bar} ({rest_txt})\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

# ==================== RAPPELS PROGRAMMÉS ====================

async def send_reminder(context: ContextTypes.DEFAULT_TYPE, reminder_type: str):
    """Envoie un rappel programmé"""
    if not CHAT_ID:
        logger.warning("CHAT_ID non configuré, rappel ignoré")
        return
    
    today = get_today_key()
    init_day(today)
    
    totals = daily_data[today]["totals"]
    remaining = get_remaining()
    
    if reminder_type == "midi":
        msg = "🕛 **POINT MIDI**\n\n"
    elif reminder_type == "soir":
        msg = "🕕 **POINT 18H**\n\n"
    else:  # recap
        msg = "🌙 **RÉCAP DE LA JOURNÉE**\n\n"
    
    msg += format_status(totals, remaining)
    
    if reminder_type == "recap":
        # Ajouter les détails des entrées
        if daily_data[today]["entries"]:
            msg += "\n\n📝 **Entrées du jour:**\n"
            for entry in daily_data[today]["entries"]:
                msg += f"   • {entry['time']} - {entry['quantity']:.0f}g {entry['food']}\n"
        
        # Évaluation finale
        prot_pct = (totals['proteines'] / DAILY_GOALS['proteines']) * 100
        if prot_pct >= 100:
            msg += "\n\n🏆 **Objectif protéines atteint !** Bien joué 💪"
        elif prot_pct >= 90:
            msg += "\n\n👍 **Presque !** Tu y es presque, continue comme ça !"
        else:
            msg += f"\n\n⚠️ **Attention:** Seulement {prot_pct:.0f}% des protéines. Pense à ajuster demain !"
    
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Erreur envoi rappel: {e}")

async def midnight_reset(context: ContextTypes.DEFAULT_TYPE):
    """Reset à minuit - nettoie les anciennes données (garde 3 jours)"""
    today = datetime.now(TIMEZONE)
    cutoff = today - timedelta(days=4)
    
    keys_to_delete = []
    for date_key in daily_data.keys():
        try:
            date = datetime.strptime(date_key, "%Y-%m-%d")
            if date < cutoff.replace(tzinfo=None):
                keys_to_delete.append(date_key)
        except:
            pass
    
    for key in keys_to_delete:
        del daily_data[key]
    
    logger.info(f"Reset minuit effectué. Données supprimées: {keys_to_delete}")

def setup_scheduler(application: Application):
    """Configure les tâches programmées"""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    
    # Rappel midi (12h00)
    scheduler.add_job(
        send_reminder,
        'cron',
        hour=12,
        minute=0,
        args=[application, "midi"]
    )
    
    # Rappel 18h
    scheduler.add_job(
        send_reminder,
        'cron',
        hour=18,
        minute=0,
        args=[application, "soir"]
    )
    
    # Récap 23h
    scheduler.add_job(
        send_reminder,
        'cron',
        hour=23,
        minute=0,
        args=[application, "recap"]
    )
    
    # Reset minuit
    scheduler.add_job(
        midnight_reset,
        'cron',
        hour=0,
        minute=1,
        args=[application]
    )
    
    scheduler.start()
    logger.info("Scheduler démarré avec rappels à 12h, 18h, 23h")

# ==================== MAIN ====================

def main():
    """Fonction principale"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN non défini!")
        return
    
    # Créer l'application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Ajouter les handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("undo", undo))
    application.add_handler(CommandHandler("add", add_food))
    application.add_handler(CommandHandler("search", search_food))
    application.add_handler(CommandHandler("list", list_foods))
    
    # Handler pour les messages texte (entrées alimentaires)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_food_message))
    
    # Configurer le scheduler pour les rappels
    setup_scheduler(application)
    
    # Lancer le bot
    logger.info("🚀 Bot Nutrition démarré!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
