#!/usr/bin/env python3
"""
Bot Telegram de Prediction - CORRIGÉ v7
Avec gestion des pauses personnalisées et système de blagues
"""
import os
import sys
import asyncio
import logging
import re
import random
from datetime import datetime, timedelta
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

API_ID = 29177661
API_HASH = "a8639172fa8d35dbfd8ea46286d349ab"
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7815360317:AAGsrFzeUZrHOjujf5aY2UjlBj4GOblHSig')

SOURCE_CHANNEL_ID = -1002682552255
PREDICTION_CHANNEL_ID = -1003430118891
ADMIN_ID = 1190237801
PORT = int(os.getenv('PORT', 10000))

EXCLUDED_NUMBERS = set(
    list(range(1086, 1091)) +
    list(range(1266, 1271)) +
    list(range(1386, 1391))
)

TARGET_CONFIG = {
    'targets': [2, 4, 6, 8],
    'cycle': ['❤️', '♦️', '♣️', '♠️', '♦️', '❤️', '♠️', '♣️'],
}

SUIT_DISPLAY = {'♦️': '♦️', '❤️': '❤️', '♣️': '♣️', '♠️': '♠️'}

PAUSE_AFTER = 5
# Cycle de pause par défaut modifiable
PAUSE_CYCLE_MINUTES = [3, 5, 4]  # Cycle par défaut: 3min, 5min, 4min
PAUSE_CYCLE_INDEX = 0  # Index actuel dans le cycle

PREDICTION_TIMEOUT = 10

# ============================================================
# VARIABLES GLOBALES
# ============================================================

bot_client = None

bot_state = {
    'predictions_count': 0,
    'is_paused': False,
    'pause_end': None,
    'last_source_number': 0,
    'last_prediction_number': None,
    'predictions_history': [],
    'precomputed_cycle': {},
    'is_stopped': False,  # Arrêt temporaire complet
    'stop_end': None,     # Fin de l'arrêt temporaire
    'joke_task': None,    # Tâche d'envoi de blagues
}

verification_state = {
    'predicted_number': None,
    'predicted_suit': None,
    'current_check': 0,
    'message_id': None,
    'channel_id': None,
    'status': None,
    'base_game': None,
    'timestamp': None
}

stats_bilan = {
    'total': 0, 'wins': 0, 'losses': 0,
    'win_details': {'✅0️⃣': 0, '✅1️⃣': 0, '✅2️⃣': 0, '✅3️⃣': 0},
    'loss_details': {'❌': 0}
}

# ============================================================
# SYSTÈME DE BLAGUES (10 blagues par défaut)
# ============================================================

DEFAULT_JOKES = [
    "🎰 Pourquoi les cartes ne jouent-elles jamais au football ? Parce qu'elles ont peur des tacles ! ⚽",
    "🃏 Quelle est la carte la plus drôle ? Le joker, bien sûr ! Il a toujours un as dans sa manche... ou pas ! 😄",
    "♠️ Pourquoi le cœur a-t-il perdu au poker ? Parce qu'il montrait toujours ses sentiments ! 💔",
    "🎲 Qu'est-ce qu'un dé dit à un autre dé ? 'On se retrouve au casino ce soir ?' 🎰",
    "♦️ Pourquoi les diamants sont-ils si chers ? Parce qu'ils ont beaucoup de carats... et de caractère ! 💎",
    "🍀 Quelle est la différence entre un joueur de poker et un magicien ? Le magicien perd son chapeau, le joueur perd sa chemise ! 🎩",
    "♣️ Pourquoi les trèfles portent-ils bonheur ? Parce qu'ils n'ont pas besoin de travailler, ils sont déjà dans les cartes ! 🍀",
    "🎰 Que fait une carte quand elle est fatiguée ? Elle se couche... sur le tapis vert ! 😴",
    "❤️ Pourquoi le roi de cœur est-il toujours amoureux ? Parce qu'il a toujours un cœur sur la main ! 👑",
    "🃏 Qu'est-ce qu'un as qui ment ? Un as... du bluff ! 😎"
]

# Chargement des blagues (avec persistance possible)
JOKES_LIST = DEFAULT_JOKES.copy()

# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def extract_game_number(message):
    match = re.search(r"#N\s*(\d+)", message, re.IGNORECASE)
    if match:
        return int(match.group(1))

    patterns = [
        r"^#(\d+)",
        r"N\s*(\d+)",
        r"Numéro\s*(\d+)",
        r"Game\s*(\d+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None

def get_last_digit(number):
    return number % 10

def extract_suits_from_first_group(message_text):
    matches = re.findall(r"\(([^)]+)\)", message_text)
    if not matches:
        return []

    first_group = matches[0]
    normalized = first_group.replace('❤️', '♥️').replace('❤', '♥️')
    normalized = normalized.replace('♠️', '♠️').replace('♦️', '♦️').replace('♣️', '♣️')

    suits = []
    for suit in ['♥️', '♠️', '♦️', '♣️']:
        if suit in normalized:
            suits.append(suit)

    return suits

def is_message_editing(message_text):
    return message_text.strip().startswith('⏰')

def is_message_finalized(message_text):
    return '✅' in message_text or '🔰' in message_text

def is_target_number(number):
    if number in EXCLUDED_NUMBERS or number < 1 or number > 1440:
        return False
    last_digit = get_last_digit(number)
    return last_digit in TARGET_CONFIG['targets']

def precompute_cycle():
    global bot_state
    
    targets = TARGET_CONFIG['targets']
    cycle = TARGET_CONFIG['cycle']
    precomputed = {}
    
    start_num = 6
    while get_last_digit(start_num) not in targets and start_num <= 1436:
        start_num += 1
    
    if start_num > 1436:
        logger.warning("⚠️ Aucun numéro cible trouvé entre 6 et 1436")
        return
    
    logger.info(f"🔄 Pré-calcul du cycle à partir de #{start_num}")
    
    cycle_pos = 0
    for num in range(start_num, 1437):
        if get_last_digit(num) in targets:
            precomputed[num] = cycle[cycle_pos % len(cycle)]
            cycle_pos += 1
    
    bot_state['precomputed_cycle'] = precomputed
    
    examples = list(precomputed.items())[:10]
    logger.info(f"📊 Cycle pré-calculé: {len(precomputed)} numéros")
    logger.info(f"📝 Exemples: {examples}")

def get_suit_for_number(number):
    return bot_state['precomputed_cycle'].get(number)

def get_trigger_target(trigger_num):
    for num in range(trigger_num + 1, 1437):
        if is_target_number(num):
            return num
    return None

def format_prediction(number, suit, status=None):
    """Messages de prédiction selon les formats spécifiés"""
    suit_name = SUIT_DISPLAY.get(suit, suit)
    
    if status == "pending" or status is None:
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ⏳ En attente"""
    
    elif status == "✅0️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅0️⃣ GAGNÉ"""
    
    elif status == "✅1️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅1️⃣ GAGNÉ"""
    
    elif status == "✅2️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅2️⃣ GAGNÉ"""
    
    elif status == "✅3️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅3️⃣ GAGNÉ"""
    
    elif status == "❌":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : PERDU"""
    
    elif status == "⏹️":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ⏹️ Expiré"""
    
    else:
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : {status}"""

def reset_verification_state():
    global verification_state
    verification_state = {
        'predicted_number': None,
        'predicted_suit': None,
        'current_check': 0,
        'message_id': None,
        'channel_id': None,
        'status': None,
        'base_game': None,
        'timestamp': None
    }

# ============================================================
# SERVEUR WEB
# ============================================================

async def handle_health(request):
    status = "STOPPED" if bot_state['is_stopped'] else ("PAUSED" if bot_state['is_paused'] else "RUNNING")
    last = bot_state['last_source_number']
    pred = verification_state['predicted_number'] or 'Libre'
    return web.Response(text=f"Bot {status} | Source: #{last} | Pred: #{pred}", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Serveur web port {PORT}")
    return runner

# ============================================================
# SYSTÈME DE PAUSE ET ARRÊT TEMPORAIRE
# ============================================================

async def check_pause():
    if bot_state['is_paused'] and bot_state['pause_end']:
        if datetime.now() >= bot_state['pause_end']:
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['predictions_count'] = 0
            logger.info("✅ Pause terminee")
            await bot_client.send_message(ADMIN_ID, "✅ Pause terminee!")
            return True
    return not bot_state['is_paused']

async def start_pause():
    global PAUSE_CYCLE_INDEX
    # Utilise le cycle de pause configuré
    minutes = PAUSE_CYCLE_MINUTES[PAUSE_CYCLE_INDEX % len(PAUSE_CYCLE_MINUTES)]
    PAUSE_CYCLE_INDEX += 1
    
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=minutes)
    msg = f"⏸️ Pause de {minutes} min (cycle: {PAUSE_CYCLE_MINUTES}, index: {PAUSE_CYCLE_INDEX})"
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, f"⏸️ {msg}")
    logger.info(f"Pause {minutes} min")

async def check_prediction_timeout(current_game):
    if verification_state['predicted_number'] is None:
        return False
    
    predicted_num = verification_state['predicted_number']
    
    if current_game > predicted_num + PREDICTION_TIMEOUT:
        logger.warning(f"⏰ PRÉDICTION #{predicted_num} EXPIRÉE (actuel: #{current_game})")
        
        try:
            predicted_suit = verification_state['predicted_suit']
            updated_text = format_prediction(predicted_num, predicted_suit, "⏹️")
            
            await bot_client.edit_message(
                verification_state['channel_id'],
                verification_state['message_id'],
                updated_text
            )
            
            await bot_client.send_message(
                ADMIN_ID, 
                f"⚠️ Prédiction #{predicted_num} expirée. Système libéré."
            )
            
        except Exception as e:
            logger.error(f"Erreur mise à jour expiration: {e}")
        
        reset_verification_state()
        return True
    
    return False

# ============================================================
# SYSTÈME DE BLAGUES DURANT L'ARRÊT TEMPORAIRE
# ============================================================

async def send_jokes_during_stop():
    """Envoie des blagues toutes les 5 minutes pendant l'arrêt temporaire"""
    global JOKES_LIST
    
    if not JOKES_LIST:
        logger.warning("⚠️ Aucune blague disponible")
        return
    
    joke_index = 0
    used_jokes = []
    
    while bot_state['is_stopped']:
        # Vérifie si l'arrêt est terminé
        if bot_state['stop_end'] and datetime.now() >= bot_state['stop_end']:
            logger.info("⏰ Fin de l'arrêt temporaire programmée")
            await stop_temporary_stop()
            break
        
        # Sélectionne une blague non utilisée récemment
        available_jokes = [j for j in JOKES_LIST if j not in used_jokes]
        if not available_jokes:
            used_jokes = []  # Reset si toutes utilisées
            available_jokes = JOKES_LIST
        
        joke = random.choice(available_jokes)
        used_jokes.append(joke)
        
        try:
            await bot_client.send_message(
                PREDICTION_CHANNEL_ID, 
                f"😄 **BLAGUE DU MOMENT** (Arrêt temporaire)\n\n{joke}\n\n⏳ Prochaine dans 5 min..."
            )
            logger.info(f"😄 Blague envoyée ({len(used_jokes)}/{len(JOKES_LIST)})")
        except Exception as e:
            logger.error(f"❌ Erreur envoi blague: {e}")
        
        # Attend 5 minutes
        for _ in range(30):  # Vérifie toutes les 10 secondes si l'arrêt est annulé
            if not bot_state['is_stopped']:
                break
            await asyncio.sleep(10)

async def start_temporary_stop(minutes):
    """Démarre l'arrêt temporaire avec envoi de blagues"""
    global PAUSE_CYCLE_MINUTES
    
    if bot_state['is_stopped']:
        await bot_client.send_message(ADMIN_ID, "⚠️ Arrêt temporaire déjà en cours!")
        return False
    
    bot_state['is_stopped'] = True
    bot_state['stop_end'] = datetime.now() + timedelta(minutes=minutes)
    
    # Annule toute prédiction en cours
    if verification_state['predicted_number'] is not None:
        reset_verification_state()
    
    # Message d'annonce
    msg = f"""🛑 **ARRÊT TEMPORAIRE ACTIVÉ**

⏱️ Durée: {minutes} minutes
😄 Blagues: Toutes les 5 minutes ({len(JOKES_LIST)} disponibles)
🎰 Prédictions: ARRÊTÉES

Cycle de pause actuel: {PAUSE_CYCLE_MINUTES}"""
    
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, f"🛑 Arrêt temporaire démarré ({minutes} min)")
    
    # Démarre la tâche de blagues
    bot_state['joke_task'] = asyncio.create_task(send_jokes_during_stop())
    logger.info(f"🛑 Arrêt temporaire démarré: {minutes} min")
    return True

async def stop_temporary_stop():
    """Arrête l'arrêt temporaire et relance les prédictions"""
    if not bot_state['is_stopped']:
        return False
    
    bot_state['is_stopped'] = False
    bot_state['stop_end'] = None
    
    # Annule la tâche de blagues si en cours
    if bot_state['joke_task']:
        bot_state['joke_task'].cancel()
        try:
            await bot_state['joke_task']
        except asyncio.CancelledError:
            pass
        bot_state['joke_task'] = None
    
    msg = """✅ **ARRÊT TEMPORAIRE TERMINÉ**

🤖 Le bot reprend les prédictions!
🎰 Bonne chance à tous! 🍀"""
    
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, "✅ Arrêt temporaire terminé - Prédictions relancées")
    logger.info("✅ Arrêt temporaire terminé")
    return True

# ============================================================
# SYSTÈME DE PRÉDICTION ET VÉRIFICATION
# ============================================================

async def send_prediction(target_game, predicted_suit, base_game):
    # Vérifie si arrêt temporaire
    if bot_state['is_stopped']:
        logger.info("🛑 Prédiction bloquée: arrêt temporaire en cours")
        return False
    
    if verification_state['predicted_number'] is not None:
        logger.error(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en cours!")
        return False

    try:
        prediction_text = format_prediction(target_game, predicted_suit, "pending")
        sent_msg = await bot_client.send_message(PREDICTION_CHANNEL_ID, prediction_text)

        verification_state.update({
            'predicted_number': target_game,
            'predicted_suit': predicted_suit,
            'current_check': 0,
            'message_id': sent_msg.id,
            'channel_id': PREDICTION_CHANNEL_ID,
            'status': 'pending',
            'base_game': base_game,
            'timestamp': datetime.now()
        })

        bot_state['last_prediction_number'] = target_game
        bot_state['predictions_count'] += 1
        bot_state['predictions_history'].append({
            'number': target_game,
            'suit': predicted_suit,
            'trigger': base_game,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })

        logger.info(f"🚀 PRÉDICTION #{target_game} ({predicted_suit}) lancée [déclencheur #{base_game}]")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi prédiction: {e}")
        return False

async def update_prediction_status(status):
    global stats_bilan

    if verification_state['predicted_number'] is None:
        logger.error("❌ Aucune prédiction à mettre à jour")
        return False

    try:
        predicted_num = verification_state['predicted_number']
        predicted_suit = verification_state['predicted_suit']

        updated_text = format_prediction(predicted_num, predicted_suit, status)

        await bot_client.edit_message(
            verification_state['channel_id'],
            verification_state['message_id'],
            updated_text
        )

        if status in ['✅0️⃣', '✅1️⃣', '✅2️⃣', '✅3️⃣']:
            stats_bilan['total'] += 1
            stats_bilan['wins'] += 1
            stats_bilan['win_details'][status] = stats_bilan['win_details'].get(status, 0) + 1
            logger.info(f"🎉 #{predicted_num} GAGNÉ ({status})")
        elif status == '❌':
            stats_bilan['total'] += 1
            stats_bilan['losses'] += 1
            logger.info(f"💔 #{predicted_num} PERDU")
        elif status == '⏹️':
            logger.info(f"⏹️ #{predicted_num} EXPIRÉ")

        logger.info(f"🔓 SYSTÈME LIBÉRÉ")
        reset_verification_state()
        return True

    except Exception as e:
        logger.error(f"❌ Erreur mise à jour statut: {e}")
        return False

async def process_verification_step(game_number, message_text):
    if verification_state['predicted_number'] is None:
        return

    predicted_num = verification_state['predicted_number']
    predicted_suit = verification_state['predicted_suit']
    current_check = verification_state['current_check']

    expected_number = predicted_num + current_check
    if game_number != expected_number:
        logger.warning(f"⚠️ Reçu #{game_number} != attendu #{expected_number}")
        return

    suits = extract_suits_from_first_group(message_text)
    logger.info(f"🔍 Vérification #{game_number}: premier groupe = {suits}, attendu = {predicted_suit}")

    predicted_normalized = predicted_suit.replace('❤️', '♥️').replace('❤', '♥️')

    if predicted_normalized in suits:
        status = f"✅{current_check}️⃣"
        logger.info(f"🎉 GAGNÉ! Costume {predicted_suit} trouvé dans premier groupe au check {current_check}")
        await update_prediction_status(status)
        return

    if current_check < 3:
        verification_state['current_check'] += 1
        next_num = predicted_num + verification_state['current_check']
        logger.info(f"❌ Check {current_check} échoué sur #{game_number}, prochain: #{next_num}")
    else:
        logger.info(f"💔 PERDU après 4 vérifications (jusqu'à #{game_number})")
        await update_prediction_status("❌")

async def check_and_launch_prediction(game_number):
    
    # Vérifie arrêt temporaire
    if bot_state['is_stopped']:
        logger.info("🛑 Prédiction bloquée: arrêt temporaire")
        return
    
    await check_prediction_timeout(game_number)
    
    if verification_state['predicted_number'] is not None:
        logger.warning(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en attente.")
        return

    if not await check_pause():
        logger.info("⏸️ En pause")
        return

    target_num = get_trigger_target(game_number)
    
    if not target_num:
        logger.info(f"ℹ️ #{game_number} pas de cible disponible après")
        return

    suit = get_suit_for_number(target_num)
    if not suit:
        logger.warning(f"⚠️ Cible #{target_num} n'a pas de costume dans le cycle")
        return

    if target_num <= game_number:
        logger.error(f"❌ ERREUR: Cible #{target_num} <= déclencheur #{game_number}")
        return

    success = await send_prediction(target_num, suit, game_number)

    if success and bot_state['predictions_count'] >= PAUSE_AFTER:
        await start_pause()

# ============================================================
# TRAITEMENT DES MESSAGES SOURCE
# ============================================================

async def process_source_message(event, is_edit=False):
    try:
        message_text = event.message.message
        game_number = extract_game_number(message_text)

        if game_number is None:
            return

        is_editing = is_message_editing(message_text)
        is_finalized = is_message_finalized(message_text)
        last_digit = get_last_digit(game_number)

        log_type = "ÉDITÉ" if is_edit else "NOUVEAU"
        log_status = "⏰" if is_editing else ("✅" if is_finalized else "📝")
        logger.info(f"📩 {log_status} {log_type}: #{game_number} (_{last_digit})")

        bot_state['last_source_number'] = game_number

        if verification_state['predicted_number'] is not None:
            predicted_num = verification_state['predicted_number']
            current_check = verification_state['current_check']
            expected_number = predicted_num + current_check

            if game_number > predicted_num + PREDICTION_TIMEOUT:
                logger.warning(f"⏰ Prédiction #{predicted_num} obsolète")
                await check_prediction_timeout(game_number)
            
            elif game_number == expected_number:
                if is_editing and not is_finalized:
                    logger.info(f"⏳ #{game_number} en édition, attente...")
                    return

                if is_finalized or not is_editing:
                    logger.info(f"✅ Vérification #{game_number}...")
                    await process_verification_step(game_number, message_text)
                    
                    if verification_state['predicted_number'] is None:
                        logger.info("✅ Vérification terminée, traitement du déclencheur...")
                        await check_and_launch_prediction(game_number)
                    return
                else:
                    logger.info(f"⏳ Attente finalisation #{game_number}")
                    return
            else:
                logger.info(f"⏭️ Attente #{expected_number}, reçu #{game_number}")

        await check_and_launch_prediction(game_number)

    except Exception as e:
        logger.error(f"❌ Erreur traitement message: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ============================================================
# COMMANDES ADMIN
# ============================================================

async def handle_admin_commands(event):
    global PAUSE_CYCLE_MINUTES, PAUSE_CYCLE_INDEX, JOKES_LIST
    
    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    cmd = parts[0].lower()

    try:
        if cmd == '/start':
            await event.respond("""🤖 Commandes:

/settargets <chiffres> - Fins à prédire (ex: /settargets 2,4,6,8)
/setcycle <emojis> - Cycle costumes (ex: /setcycle ❤️ ♦️ ♣️ ♠️)
/setpausecycle <minutes> - Cycle pause (ex: /setpausecycle 3,5,4)
/stop <minutes> - Arrêt temporaire avec blagues
/stopnow - Arrêter immédiatement l'arrêt temporaire
/jokes - Gérer les blagues (voir sous-commandes)
/reset - Reset
/forceunlock - Débloquer
/pause /resume - Pause/Reprendre
/info - État complet
/showcycle - Afficher le cycle
/bilan - Statistiques""")

        elif cmd == '/settargets':
            if len(parts) < 2:
                await event.respond(
                    f"📋 Usage: `/settargets <chiffres>`\n"
                    f"Ex: `/settargets 2,4,6,8`\n"
                    f"Actuel: {TARGET_CONFIG['targets']}"
                )
                return

            try:
                new_targets = [int(x.strip()) for x in parts[1].split(',') if x.strip()]
                
                for d in new_targets:
                    if d < 0 or d > 9:
                        await event.respond(f"❌ {d} invalide (0-9)")
                        return

                new_targets = sorted(list(set(new_targets)))
                TARGET_CONFIG['targets'] = new_targets
                precompute_cycle()
                
                first_targets = [n for n in range(6, 50) if get_last_digit(n) in new_targets][:4]
                example = " | ".join([f"#{n}{get_suit_for_number(n)}" for n in first_targets if get_suit_for_number(n)])
                
                await event.respond(
                    f"✅ Fins de numéro: {new_targets}\n"
                    f"🔄 Cycle recalculé: {len(bot_state['precomputed_cycle'])} numéros\n"
                    f"📝 Début: {example}"
                )

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/setcycle':
            if len(parts) < 2:
                current = ' '.join(TARGET_CONFIG['cycle'])
                await event.respond(
                    f"📋 Usage: `/setcycle <emojis...>`\n"
                    f"Ex: `/setcycle ❤️ ♦️ ♣️ ♠️`\n"
                    f"Actuel: {current}"
                )
                return

            new_cycle = parts[1:]
            valid = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid]

            if invalid:
                await event.respond(f"❌ Invalides: {invalid}. Valides: {valid}")
                return

            TARGET_CONFIG['cycle'] = new_cycle
            precompute_cycle()
            
            targets = TARGET_CONFIG['targets']
            first_nums = [n for n in range(6, 50) if get_last_digit(n) in targets][:6]
            example = " ".join([f"#{n}{get_suit_for_number(n)}" for n in first_nums if get_suit_for_number(n)])
            
            await event.respond(
                f"✅ Cycle: {' '.join(new_cycle)}\n"
                f"🔄 Recalculé: {len(bot_state['precomputed_cycle'])} numéros\n"
                f"📝 Exemple: {example}"
            )

        elif cmd == '/setpausecycle':
            """Modifie le cycle des pauses"""
            if len(parts) < 2:
                await event.respond(
                    f"📋 Usage: `/setpausecycle <minutes>`\n"
                    f"Ex: `/setpausecycle 3,5,4` ou `/setpausecycle 5,10`\n"
                    f"Actuel: {PAUSE_CYCLE_MINUTES}\n"
                    f"Prochain index: {PAUSE_CYCLE_INDEX % len(PAUSE_CYCLE_MINUTES)}"
                )
                return

            try:
                new_cycle = [int(x.strip()) for x in parts[1].split(',') if x.strip()]
                
                if not new_cycle:
                    await event.respond("❌ Veuillez fournir au moins une valeur")
                    return
                
                for m in new_cycle:
                    if m < 1 or m > 60:
                        await event.respond(f"❌ {m} invalide (1-60 minutes)")
                        return

                PAUSE_CYCLE_MINUTES = new_cycle
                PAUSE_CYCLE_INDEX = 0  # Reset l'index
                
                await event.respond(
                    f"✅ **Cycle de pause modifié!**\n\n"
                    f"🔄 Nouveau cycle: {PAUSE_CYCLE_MINUTES}\n"
                    f"📊 {len(PAUSE_CYCLE_MINUTES)} valeur(s)\n"
                    f"🎯 Prochaine pause: {PAUSE_CYCLE_MINUTES[0]} min"
                )
                logger.info(f"Cycle de pause modifié: {PAUSE_CYCLE_MINUTES}")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/stop':
            """Arrêt temporaire avec blagues"""
            if len(parts) < 2:
                await event.respond(
                    f"📋 Usage: `/stop <minutes>`\n"
                    f"Ex: `/stop 30` (arrêt de 30 minutes avec blagues)\n"
                    f"Blagues disponibles: {len(JOKES_LIST)}"
                )
                return

            try:
                minutes = int(parts[1])
                if minutes < 5 or minutes > 120:
                    await event.respond("❌ Durée invalide (5-120 minutes)")
                    return

                success = await start_temporary_stop(minutes)
                if success:
                    await event.respond(f"✅ Arrêt temporaire démarré: {minutes} min")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/stopnow':
            """Arrête immédiatement l'arrêt temporaire"""
            if not bot_state['is_stopped']:
                await event.respond("❌ Aucun arrêt temporaire en cours")
                return
            
            await stop_temporary_stop()
            await event.respond("✅ Arrêt temporaire terminé manuellement")

        elif cmd == '/jokes':
            """Gestion des blagues"""
            if len(parts) < 2:
                # Affiche la liste des sous-commandes
                jokes_preview = "\n".join([f"{i+1}. {j[:50]}..." for i, j in enumerate(JOKES_LIST[:5])])
                if len(JOKES_LIST) > 5:
                    jokes_preview += f"\n... et {len(JOKES_LIST) - 5} autres"
                
                await event.respond(
                    f"😄 **Gestion des blagues**\n\n"
                    f"📊 Total: {len(JOKES_LIST)} blagues\n\n"
                    f"**Sous-commandes:**\n"
                    f"`/jokes list` - Voir toutes les blagues\n"
                    f"`/jokes add <texte>` - Ajouter une blague\n"
                    f"`/jokes del <numéro>` - Supprimer une blague\n"
                    f"`/jokes edit <numéro> <texte>` - Modifier une blague\n"
                    f"`/jokes reset` - Réinitialiser les blagues par défaut\n\n"
                    f"**Aperçu:**\n{jokes_preview}"
                )
                return

            subcmd = parts[1].lower()

            if subcmd == 'list':
                # Liste toutes les blagues
                if not JOKES_LIST:
                    await event.respond("📭 Aucune blague enregistrée")
                    return
                
                jokes_text = ""
                for i, joke in enumerate(JOKES_LIST, 1):
                    jokes_text += f"**{i}.** {joke}\n\n"
                    # Évite les messages trop longs
                    if i % 5 == 0 and i < len(JOKES_LIST):
                        await event.respond(jokes_text)
                        jokes_text = ""
                
                if jokes_text:
                    await event.respond(jokes_text)

            elif subcmd == 'add':
                if len(parts) < 3:
                    await event.respond("📋 Usage: `/jokes add <votre blague>`")
                    return
                
                new_joke = ' '.join(parts[2:])
                JOKES_LIST.append(new_joke)
                await event.respond(f"✅ Blague ajoutée! (Total: {len(JOKES_LIST)})\n\n📝 {new_joke}")

            elif subcmd == 'del':
                if len(parts) < 3:
                    await event.respond("📋 Usage: `/jokes del <numéro>`\nEx: `/jokes del 3`")
                    return
                
                try:
                    idx = int(parts[2]) - 1
                    if idx < 0 or idx >= len(JOKES_LIST):
                        await event.respond(f"❌ Numéro invalide (1-{len(JOKES_LIST)})")
                        return
                    
                    deleted = JOKES_LIST.pop(idx)
                    await event.respond(f"🗑️ Blague #{idx+1} supprimée!\n\n📝 {deleted[:100]}...")
                except ValueError:
                    await event.respond("❌ Veuillez entrer un numéro valide")

            elif subcmd == 'edit':
                if len(parts) < 4:
                    await event.respond("📋 Usage: `/jokes edit <numéro> <nouveau texte>`\nEx: `/jokes edit 2 Nouvelle blague ici`")
                    return
                
                try:
                    idx = int(parts[2]) - 1
                    if idx < 0 or idx >= len(JOKES_LIST):
                        await event.respond(f"❌ Numéro invalide (1-{len(JOKES_LIST)})")
                        return
                    
                    old_joke = JOKES_LIST[idx]
                    new_joke = ' '.join(parts[3:])
                    JOKES_LIST[idx] = new_joke
                    
                    await event.respond(
                        f"✏️ Blague #{idx+1} modifiée!\n\n"
                        f"**Ancien:**\n{old_joke[:100]}...\n\n"
                        f"**Nouveau:**\n{new_joke}"
                    )
                except ValueError:
                    await event.respond("❌ Veuillez entrer un numéro valide")

            elif subcmd == 'reset':
                JOKES_LIST.clear()
                JOKES_LIST.extend(DEFAULT_JOKES)
                await event.respond(f"🔄 Blagues réinitialisées! ({len(JOKES_LIST)} blagues par défaut)")

            else:
                await event.respond("❓ Sous-commande inconnue. Utilisez `/jokes` pour voir la liste")

        elif cmd == '/showcycle':
            targets = TARGET_CONFIG['targets']
            lines = []
            
            count = 0
            for num in range(6, 1437):
                if count >= 20:
                    break
                if get_last_digit(num) in targets:
                    suit = get_suit_for_number(num)
                    if suit:
                        lines.append(f"#{num}{suit}")
                        count += 1
            
            cycle_str = " → ".join(lines)
            await event.respond(
                f"🎨 **Cycle** (fins: {targets})\n"
                f"{' '.join(TARGET_CONFIG['cycle'])}\n\n"
                f"Début:\n{cycle_str}\n\n"
                f"Total: {len(bot_state['precomputed_cycle'])} numéros"
            )

        elif cmd == '/reset':
            old_pred = verification_state['predicted_number']
            bot_state['predictions_count'] = 0
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            reset_verification_state()
            await event.respond(f"🔄 RESET!{f' (prédiction #{old_pred} effacée)' if old_pred else ''} Système libéré!")

        elif cmd == '/forceunlock':
            old_pred = verification_state['predicted_number']
            reset_verification_state()
            await event.respond(f"🔓 FORCÉ! #{old_pred} annulée. Système libre!")

        elif cmd == '/info':
            last_src = bot_state['last_source_number']
            last_pred = bot_state['last_prediction_number']
            current_pred = verification_state['predicted_number']

            # Détermine le statut global
            if bot_state['is_stopped']:
                status = "🛑 ARRÊT TEMPORAIRE"
                stop_remaining = bot_state['stop_end'] - datetime.now()
                stop_info = f"\n⏱️ Restant: {stop_remaining.seconds // 60} min"
            elif bot_state['is_paused']:
                status = "⏸️ PAUSE"
                stop_info = ""
            else:
                status = "▶️ ACTIF"
                stop_info = ""

            verif_info = "Aucune"
            if current_pred:
                next_check = current_pred + verification_state['current_check']
                remaining = PREDICTION_TIMEOUT - (last_src - current_pred)
                verif_info = f"#{current_pred} (check {verification_state['current_check']}/3, #{next_check}, timeout {remaining})"

            targets = TARGET_CONFIG['targets']
            examples = []
            for num in range(6, 50):
                if len(examples) >= 4:
                    break
                if get_last_digit(num) in targets:
                    suit = get_suit_for_number(num)
                    if suit:
                        examples.append(f"#{num}{suit}")

            msg = f"""📊 **STATUT**

🟢 **État:** {status}{stop_info}
🎯 **Source:** #{last_src}
🔍 **Prédiction:** #{last_pred if last_pred else 'Aucune'}
🔎 **Vérification:** {verif_info}
📊 **Pause:** {bot_state['predictions_count']}/{PAUSE_AFTER}

🎯 **CIBLES:** {TARGET_CONFIG['targets']}
🎨 **Cycle:** {' '.join(TARGET_CONFIG['cycle'])}
⏸️ **Cycle pause:** {PAUSE_CYCLE_MINUTES} (index: {PAUSE_CYCLE_INDEX % len(PAUSE_CYCLE_MINUTES)})
😄 **Blagues:** {len(JOKES_LIST)} disponibles
📊 **Pré-calcul:** {len(bot_state['precomputed_cycle'])} numéros
📝 **Exemples:** {' | '.join(examples)}

💡 `/reset` ou `/forceunlock` si bloqué"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\n⏸️ **Pause:** {remaining.seconds // 60} min"

            await event.respond(msg)

        elif cmd == '/bilan':
            if stats_bilan['total'] == 0:
                await event.respond("📊 Aucune prédiction")
                return

            win_rate = (stats_bilan['wins'] / stats_bilan['total']) * 100
            await event.respond(f"""📊 **BILAN**

🎯 **Total:** {stats_bilan['total']}
✅ **Victoires:** {stats_bilan['wins']} ({win_rate:.1f}%)
❌ **Défaites:** {stats_bilan['losses']}

**Détails:**
• N: {stats_bilan['win_details'].get('✅0️⃣', 0)}
• N+1: {stats_bilan['win_details'].get('✅1️⃣', 0)}
• N+2: {stats_bilan['win_details'].get('✅2️⃣', 0)}
• N+3: {stats_bilan['win_details'].get('✅3️⃣', 0)}""")

        elif cmd == '/pause':
            bot_state['is_paused'] = True
            await bot_client.send_message(PREDICTION_CHANNEL_ID, "⏸️ Pause")
            await event.respond("⏸️ En pause")

        elif cmd == '/resume':
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            await event.respond("▶️ Repris!")

        else:
            await event.respond("❓ Commande inconnue. /start pour la liste.")

    except Exception as e:
        logger.error(f"Erreur commande: {e}")
        await event.respond(f"❌ Erreur: {str(e)}")

# ============================================================
# DÉMARRAGE
# ============================================================

async def start_bot():
    global bot_client

    session = os.getenv('TELEGRAM_SESSION', '')
    bot_client = TelegramClient(StringSession(session), API_ID, API_HASH)

    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connecté")

        @bot_client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def source_handler(event):
            await process_source_message(event, is_edit=False)

        @bot_client.on(events.MessageEdited(chats=SOURCE_CHANNEL_ID))
        async def edit_handler(event):
            await process_source_message(event, is_edit=True)

        @bot_client.on(events.NewMessage(pattern='/'))
        async def admin_handler(event):
            if event.sender_id == ADMIN_ID:
                await handle_admin_commands(event)

        precompute_cycle()

        targets = TARGET_CONFIG['targets']
        examples = []
        for num in range(6, 30):
            if len(examples) >= 6:
                break
            if get_last_digit(num) in targets:
                suit = get_suit_for_number(num)
                if suit:
                    examples.append(f"#{num}{suit}")

        startup = f"""🤖 **BOT PRÉDICTION DÉMARRÉ** (v7)

🎯 **Cibles:** {TARGET_CONFIG['targets']}
🎨 **Cycle:** {' '.join(TARGET_CONFIG['cycle'])}
⏸️ **Cycle pause:** {PAUSE_CYCLE_MINUTES}
😄 **Blagues:** {len(JOKES_LIST)} disponibles
📊 **Pré-calcul:** {len(bot_state['precomputed_cycle'])} numéros

📝 **Exemples:** {' → '.join(examples)}

/start pour les commandes"""

        await bot_client.send_message(ADMIN_ID, startup)
        return bot_client

    except Exception as e:
        logger.error(f"Erreur: {e}")
        return None

async def main():
    logger.info("🚀 Démarrage...")

    web = await start_web_server()
    client = await start_bot()

    if not client:
        return

    logger.info("✅ Bot opérationnel")

    try:
        while True:
            # Vérifie l'arrêt temporaire
            if bot_state['is_stopped']:
                if bot_state['stop_end'] and datetime.now() >= bot_state['stop_end']:
                    logger.info("⏰ Fin programmée de l'arrêt temporaire")
                    await stop_temporary_stop()
            
            # Vérifie la pause normale
            elif bot_state['is_paused']:
                await check_pause()
            
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logger.info("👋 Arrêt")
    finally:
        # Nettoyage
        if bot_state['joke_task']:
            bot_state['joke_task'].cancel()
        await client.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)
