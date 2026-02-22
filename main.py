#!/usr/bin/env python3
"""
Bot Telegram de Prediction - CORRIGÉ v9
Avec commande /settriggers pour modifier les déclencheurs
"""
import os
import sys
import asyncio
import logging
import re
import random
from datetime import datetime, timedelta
from pytz import timezone
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

# Configuration par défaut
TARGET_CONFIG = {
    'targets': [2, 4, 6, 8],      # Fins de numéro à prédire
    'triggers': [1, 3, 5, 7, 9],  # Fins de numéro déclencheurs (NOUVEAU)
    'cycle': ['❤️', '♦️', '♣️', '♠️', '♦️', '❤️', '♠️', '♣️'],
}

SUIT_DISPLAY = {'♦️': '♦️', '❤️': '❤️', '♣️': '♣️', '♠️': '♠️'}

PAUSE_AFTER = 5
PAUSE_MINUTES = [3, 4, 5]
PREDICTION_TIMEOUT = 10

BENIN_TZ = timezone('Africa/Porto-Novo')

# ============================================================
# BASE DE DONNÉES DES BLAGUES
# ============================================================

DEFAULT_JOKES = [
    "Si le Cameroun pouvait prendre un jeune de 25 ans comme président, le Cameroun remportera la coupe du monde ! 🏆🇨🇲",
    "Pourquoi les poissons n'aiment pas les ordinateurs ? Parce qu'ils ont peur du net ! 🐟💻",
    "Quelle est la différence entre une femme et une parachute ? Si la parachute ne s'ouvre pas, on meurt ! 😱",
    "Un homme entre dans un bar... et sort avec une femme. Le lendemain, il rentre dans le même bar... et ressort avec la même femme. Le barman dit : 'Tu aimes pas essayer autre chose ?' L'homme répond : 'J'ai essayé, mais ma femme m'a dit de rentrer !' 😂",
    "Pourquoi les plongeurs plongent-ils toujours en arrière et jamais en avant ? Parce que sinon ils tombent dans le bateau ! 🤿🚤",
    "Qu'est-ce qu'un chien sans pattes ? On l'appelle comme on veut, il ne viendra pas quand même ! 🐕",
    "Un gars dit à son pote : 'Je connais une blague sur les vaccins, mais je ne suis pas sûr que tout le monde l'attrape.' 💉😷",
    "Pourquoi les éléphants ne peuvent pas cacher dans les arbres ? Parce qu'ils sont trop gros ! 🐘🌳",
    "Qu'est-ce qui est jaune et qui attend ? Jonathan ! 🍋⏳",
    "Pourquoi les Canadiens sont-ils si bons au hockey ? Parce qu'ils ont froid et ils veulent aller au vestiaire vite ! 🏒❄️"
]

jokes_db = {}
next_joke_id = 1

def init_jokes():
    global next_joke_id
    for i, joke in enumerate(DEFAULT_JOKES, 1):
        jokes_db[i] = {
            "text": joke,
            "added_by": ADMIN_ID,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    next_joke_id = len(DEFAULT_JOKES) + 1
    logger.info(f"✅ {len(DEFAULT_JOKES)} blagues chargées")

def add_joke(text, user_id):
    global next_joke_id
    joke_id = next_joke_id
    jokes_db[joke_id] = {
        "text": text,
        "added_by": user_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    next_joke_id += 1
    return joke_id

def delete_joke(joke_id):
    if joke_id in jokes_db:
        del jokes_db[joke_id]
        return True
    return False

def get_random_joke():
    if not jokes_db:
        return None
    return random.choice(list(jokes_db.values()))["text"]

def get_all_jokes():
    return {k: v["text"][:50] + "..." if len(v["text"]) > 50 else v["text"] 
            for k, v in jokes_db.items()}

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
    'artem_pause': False,
    'artem_pause_end': None,
    'artem_resume_time': None,
    'joke_task': None,
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

def is_trigger_number(number):
    """Vérifie si le numéro est un déclencheur"""
    last_digit = get_last_digit(number)
    return last_digit in TARGET_CONFIG['triggers']

def precompute_cycle():
    global bot_state
    
    targets = TARGET_CONFIG['targets']
    cycle = TARGET_CONFIG['cycle']
    precomputed = {}
    
    start_num = 6
    while get_last_digit(start_num) not in targets and start_num <= 1436:
        start_num += 1
    
    if start_num > 1436:
        logger.warning("⚠️ Aucun numéro cible trouvé")
        return
    
    cycle_pos = 0
    for num in range(start_num, 1437):
        if get_last_digit(num) in targets:
            precomputed[num] = cycle[cycle_pos % len(cycle)]
            cycle_pos += 1
    
    bot_state['precomputed_cycle'] = precomputed
    logger.info(f"📊 Cycle pré-calculé: {len(precomputed)} numéros")

def get_suit_for_number(number):
    return bot_state['precomputed_cycle'].get(number)

def get_trigger_target(trigger_num):
    """
    Cherche le prochain numéro cible après le déclencheur
    """
    for num in range(trigger_num + 1, 1437):
        if is_target_number(num):
            return num
    return None

# ============================================================
# FORMAT DES MESSAGES
# ============================================================

def format_prediction(number, suit, status=None):
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
📊 Statут : ⏹️ EXPIRÉ"""
    
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

def get_benin_time():
    return datetime.now(BENIN_TZ)

def format_benin_time(dt):
    return dt.strftime("%H:%M")

# ============================================================
# SYSTÈME DE PAUSE "ARTEM" AVEC BLAGUES
# ============================================================

async def send_joke():
    joke = get_random_joke()
    if joke:
        try:
            await bot_client.send_message(
                PREDICTION_CHANNEL_ID,
                f"😄 **Pause détente**\n\n{joke}\n\n_⏳ Les prédictions reprennent bientôt..._"
            )
            logger.info("😄 Blague envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi blague: {e}")

async def joke_loop():
    while bot_state['artem_pause']:
        wait_minutes = random.randint(15, 25)
        
        for _ in range(wait_minutes):
            if not bot_state['artem_pause']:
                return
            await asyncio.sleep(60)
        
        if bot_state['artem_pause']:
            await send_joke()

async def start_artem_pause(duration_str):
    global bot_state
    
    hours = 0
    minutes = 0
    
    h_match = re.search(r'(\d+)h', duration_str, re.IGNORECASE)
    if h_match:
        hours = int(h_match.group(1))
    
    m_match = re.search(r'(\d+)m', duration_str, re.IGNORECASE)
    if m_match:
        minutes = int(m_match.group(1))
    
    if hours == 0 and minutes == 0:
        try:
            hours = int(duration_str)
        except ValueError:
            return None, "Format invalide. Utilisez: 2h, 30m, 1h30m, ou juste 2"
    
    total_minutes = hours * 60 + minutes
    if total_minutes <= 0:
        return None, "Durée doit être positive"
    
    now = get_benin_time()
    end_time = now + timedelta(minutes=total_minutes)
    
    bot_state['artem_pause'] = True
    bot_state['artem_pause_end'] = datetime.now() + timedelta(minutes=total_minutes)
    bot_state['artem_resume_time'] = format_benin_time(end_time)
    
    if bot_state['joke_task'] and not bot_state['joke_task'].done():
        bot_state['joke_task'].cancel()
    
    bot_state['joke_task'] = asyncio.create_task(joke_loop())
    
    logger.info(f"⏸️ Pause artem: {hours}h{minutes}m, reprise à {bot_state['artem_resume_time']}")
    
    return {
        'duration': f"{hours}h{minutes}m" if minutes else f"{hours}h",
        'end_time': bot_state['artem_resume_time'],
        'total_minutes': total_minutes
    }, None

async def stop_artem_pause():
    global bot_state
    
    if not bot_state['artem_pause']:
        return False
    
    bot_state['artem_pause'] = False
    bot_state['artem_pause_end'] = None
    bot_state['artem_resume_time'] = None
    
    if bot_state['joke_task'] and not bot_state['joke_task'].done():
        bot_state['joke_task'].cancel()
        bot_state['joke_task'] = None
    
    logger.info("▶️ Pause artem terminée")
    return True

async def check_artem_pause():
    if bot_state['artem_pause'] and bot_state['artem_pause_end']:
        if datetime.now() >= bot_state['artem_pause_end']:
            await stop_artem_pause()
            await bot_client.send_message(
                PREDICTION_CHANNEL_ID,
                f"▶️ **Les prédictions reprennent !**\n\n🎰 Le bot est de retour en ligne."
            )
            await bot_client.send_message(ADMIN_ID, "✅ Pause artem terminée automatiquement")
            return True
    return not bot_state['artem_pause']

# ============================================================
# SERVEUR WEB
# ============================================================

async def handle_health(request):
    status = "PAUSED" if bot_state['is_paused'] else "RUNNING"
    if bot_state['artem_pause']:
        status = "ARTEM_PAUSE"
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
# PAUSE NORMALE ET TIMEOUT
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
    import random
    minutes = random.choice(PAUSE_MINUTES)
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=minutes)
    msg = f"⏸️ Pause de {minutes} min"
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, f"⏸️ {msg}")
    logger.info(f"Pause {minutes} min")

async def check_prediction_timeout(current_game):
    if verification_state['predicted_number'] is None:
        return False
    
    predicted_num = verification_state['predicted_number']
    
    if current_game > predicted_num + PREDICTION_TIMEOUT:
        logger.warning(f"⏰ PRÉDICTION #{predicted_num} EXPIRÉE")
        
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
# SYSTÈME DE PRÉDICTION ET VÉRIFICATION
# ============================================================

async def send_prediction(target_game, predicted_suit, base_game):
    if bot_state['artem_pause']:
        logger.info(f"⏸️ Prédiction #{target_game} bloquée (pause artem)")
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

        logger.info(f"🚀 PRÉDICTION #{target_game} ({predicted_suit}) lancée")
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
        logger.info(f"🎉 GAGNÉ! Check {current_check}")
        await update_prediction_status(status)
        return

    if current_check < 3:
        verification_state['current_check'] += 1
        next_num = predicted_num + verification_state['current_check']
        logger.info(f"❌ Check {current_check} échoué, prochain: #{next_num}")
    else:
        logger.info(f"💔 PERDU après 4 vérifications")
        await update_prediction_status("❌")

async def check_and_launch_prediction(game_number):
    
    if bot_state['artem_pause']:
        if await check_artem_pause():
            pass
        else:
            logger.info(f"⏸️ Prédiction bloquée - pause artem active")
            return
    
    await check_prediction_timeout(game_number)
    
    if verification_state['predicted_number'] is not None:
        logger.warning(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en attente.")
        return

    if not await check_pause():
        logger.info("⏸️ En pause")
        return

    # VÉRIFIER SI C'EST UN DÉCLENCHEUR
    if not is_trigger_number(game_number):
        logger.info(f"ℹ️ #{game_number} (_{get_last_digit(game_number)}) pas un déclencheur")
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

bla_state = {
    'waiting_for_text': False,
    'draft_text': None
}

async def handle_admin_commands(event):
    global bla_state
    
    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    cmd = parts[0].lower()

    if bla_state['waiting_for_text'] and cmd not in ['bla', 'cancelbla']:
        joke_text = text
        joke_id = add_joke(joke_text, event.sender_id)
        
        jokes_list = get_all_jokes()
        jokes_text = "\n".join([f"{k}. {v}" for k, v in jokes_list.items()])
        
        await event.respond(
            f"✅ **Blague #{joke_id} ajoutée!**\n\n"
            f"📋 **Liste des blagues:**\n{jokes_text}\n\n"
            f"💡 Pour supprimer: `/delbla <numéro>`"
        )
        
        bla_state['waiting_for_text'] = False
        return

    try:
        if cmd == '/start':
            await event.respond("""🤖 Commandes disponibles:

🎯 **Configuration Prédictions:**
/settargets <chiffres> - Fins de numéro à prédire
/settriggers <chiffres> - Fins de numéro déclencheurs (NOUVEAU)
/setcycle <emojis> - Cycle des costumes

⏸️ **Pause & Blagues:**
/artem <durée> - Pause temporaire avec blagues
/stopartem - Arrêter la pause artem

😄 **Gestion Blagues:**
/bla - Ajouter une blague
/cancelbla - Annuler l'ajout
/delbla <n> - Supprimer une blague
/listbla - Liste des blagues

⚙️ **Gestion Système:**
/reset - Reset complet
/forceunlock - Débloquer immédiatement
/pause /resume - Pause/Reprendre
/info - État complet
/showcycle - Afficher le cycle
/bilan - Statistiques""")

        # ============================================================
        # NOUVELLE COMMANDE: /settriggers
        # ============================================================

        elif cmd == '/settriggers':
            """Modifie les fins de numéro déclencheurs"""
            if len(parts) < 2:
                await event.respond(
                    f"📋 **Usage:** `/settriggers <chiffres>`\n\n"
                    f"**Description:** Définit quels numéros déclenchent une prédiction.\n\n"
                    f"**Exemples:**\n"
                    f"• `/settriggers 1,3,5,7,9` - Déclenche sur les impairs\n"
                    f"• `/settriggers 0,2,4,6,8` - Déclenche sur les pairs\n"
                    f"• `/settriggers 1,2,3` - Déclenche sur 1, 2, 3\n\n"
                    f"**Actuel:** {TARGET_CONFIG['triggers']}"
                )
                return

            try:
                new_triggers = [int(x.strip()) for x in parts[1].split(',') if x.strip()]
                
                # Validation 0-9
                for d in new_triggers:
                    if d < 0 or d > 9:
                        await event.respond(f"❌ {d} invalide (0-9 uniquement)")
                        return

                # Éviter les doublons et trier
                new_triggers = sorted(list(set(new_triggers)))
                
                TARGET_CONFIG['triggers'] = new_triggers
                
                await event.respond(
                    f"✅ **Déclencheurs modifiés!**\n\n"
                    f"🔔 Le bot réagira maintenant aux numéros finissant par: {new_triggers}\n\n"
                    f"💡 **Rappel:**\n"
                    f"• **Cibles** (à prédire): {TARGET_CONFIG['targets']}\n"
                    f"• **Déclencheurs** (qui lancent): {new_triggers}\n\n"
                    f"Exemple: Si déclencheur=1 et cible=2, quand le canal envoie #X1, le bot prédit #Y2 (le prochain numéro finissant par 2)"
                )

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        # ============================================================
        # COMMANDES EXISTANTES
        # ============================================================

        elif cmd == '/settargets':
            if len(parts) < 2:
                await event.respond(
                    f"📋 **Usage:** `/settargets <chiffres>`\n"
                    f"**Exemple:** `/settargets 2,4,6,8`\n"
                    f"**Actuel:** {TARGET_CONFIG['targets']}\n\n"
                    f"💡 Ce sont les fins de numéro que le bot va **prédire**"
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
                
                await event.respond(
                    f"✅ **Cibles modifiées:** {new_targets}\n"
                    f"🔄 Cycle recalculé: {len(bot_state['precomputed_cycle'])} numéros\n\n"
                    f"💡 **Configuration actuelle:**\n"
                    f"• **Déclencheurs:** {TARGET_CONFIG['triggers']}\n"
                    f"• **Cibles:** {new_targets}"
                )

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/setcycle':
            if len(parts) < 2:
                current = ' '.join(TARGET_CONFIG['cycle'])
                await event.respond(
                    f"📋 **Usage:** `/setcycle <emojis...>`\n"
                    f"**Exemple:** `/setcycle ❤️ ♦️ ♣️ ♠️`\n"
                    f"**Actuel:** {current}"
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
            
            await event.respond(
                f"✅ **Cycle modifié:** {' '.join(new_cycle)}\n"
                f"🔄 Recalculé: {len(bot_state['precomputed_cycle'])} numéros"
            )

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
                f"🎨 **Cycle pré-calculé**\n\n"
                f"**Configuration:**\n"
                f"• Déclencheurs: {TARGET_CONFIG['triggers']}\n"
                f"• Cibles: {TARGET_CONFIG['targets']}\n"
                f"• Cycle: {' '.join(TARGET_CONFIG['cycle'])}\n\n"
                f"**Début:**\n{cycle_str}\n\n"
                f"Total: {len(bot_state['precomputed_cycle'])} numéros"
            )

        elif cmd == '/artem':
            if len(parts) < 2:
                await event.respond(
                    "📋 **Usage:** `/artem <durée>`\n\n"
                    "**Formats:**\n"
                    "• `/artem 2h` - 2 heures\n"
                    "• `/artem 30m` - 30 minutes\n"
                    "• `/artem 1h30m` - 1h30\n\n"
                    "⏸️ Les prédictions s'arrêtent, des blagues sont envoyées."
                )
                return

            duration_str = parts[1]
            result, error = await start_artem_pause(duration_str)
            
            if error:
                await event.respond(f"❌ {error}")
                return
            
            canal_msg = (
                f"⏸️ **ARRÊT TEMPORAIRE DES PRÉDICTIONS**\n\n"
                f"🕐 Durée: **{result['duration']}**\n"
                f"🔄 Reprise à: **{result['end_time']}** (heure du Bénin)\n\n"
                f"😄 Des blagues seront envoyées pendant cette pause !\n\n"
                f"_🤖 Le bot reprendra automatiquement_"
            )
            await bot_client.send_message(PREDICTION_CHANNEL_ID, canal_msg)
            
            await event.respond(
                f"✅ **Pause artem démarrée**\n"
                f"⏱️ Durée: {result['total_minutes']} minutes\n"
                f"🕐 Reprise: {result['end_time']} (Bénin)\n\n"
                f"💡 `/stopartem` pour annuler"
            )
            
            await send_joke()

        elif cmd == '/stopartem':
            if not bot_state['artem_pause']:
                await event.respond("❌ Aucune pause artem active")
                return
            
            await stop_artem_pause()
            
            await bot_client.send_message(
                PREDICTION_CHANNEL_ID,
                f"▶️ **Les prédictions reprennent maintenant !**\n\n"
                f"🎰 Le bot est de retour en ligne.\n"
                f"_Pause artem annulée par l'administrateur_"
            )
            
            await event.respond("✅ Pause artem arrêtée manuellement")

        elif cmd == '/bla':
            bla_state['waiting_for_text'] = True
            await event.respond(
                "📝 **Ajout d'une blague**\n\n"
                "Écrivez votre blague directement.\n"
                "Ex: `Si le Cameroun pouvait...`\n\n"
                "❌ `/cancelbla` pour annuler"
            )

        elif cmd == '/cancelbla':
            if bla_state['waiting_for_text']:
                bla_state['waiting_for_text'] = False
                await event.respond("❌ Ajout de blague annulé")
            else:
                await event.respond("❌ Aucune blague en cours")

        elif cmd == '/delbla':
            if len(parts) < 2:
                jokes_list = get_all_jokes()
                if not jokes_list:
                    await event.respond("📭 Aucune blague")
                    return
                
                jokes_text = "\n".join([f"{k}. {v}" for k, v in jokes_list.items()])
                await event.respond(f"📋 **Blagues:**\n{jokes_text}\n\n💡 `/delbla <numéro>`")
                return
            
            try:
                joke_id = int(parts[1])
                if delete_joke(joke_id):
                    await event.respond(f"✅ Blague #{joke_id} supprimée")
                else:
                    await event.respond(f"❌ Blague #{joke_id} introuvable")
            except ValueError:
                await event.respond("❌ Numéro invalide")

        elif cmd == '/listbla':
            jokes_list = get_all_jokes()
            if not jokes_list:
                await event.respond("📭 Aucune blague enregistrée")
                return
            
            total = len(jokes_list)
            jokes_text = "\n".join([f"{k}. {v}" for k, v in list(jokes_list.items())[:15]])
            
            if total > 15:
                jokes_text += f"\n... et {total - 15} autres"
            
            await event.respond(f"📋 **{total} blagues:**\n\n{jokes_text}")

        elif cmd == '/reset':
            old_pred = verification_state['predicted_number']
            bot_state['predictions_count'] = 0
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            reset_verification_state()
            
            if bot_state['artem_pause']:
                await stop_artem_pause()
            
            await event.respond(f"🔄 RESET! Système libéré!")

        elif cmd == '/forceunlock':
            old_pred = verification_state['predicted_number']
            reset_verification_state()
            await event.respond(f"🔓 FORCÉ! #{old_pred} annulée. Système libre!")

        elif cmd == '/info':
            last_src = bot_state['last_source_number']
            last_pred = bot_state['last_prediction_number']
            current_pred = verification_state['predicted_number']

            if bot_state['artem_pause']:
                status = f"⏸️ ARTEM (reprise {bot_state['artem_resume_time']})"
            elif bot_state['is_paused']:
                status = "⏸️ PAUSE"
            else:
                status = "▶️ ACTIF"
            
            verif_info = "Aucune"
            if current_pred:
                next_check = current_pred + verification_state['current_check']
                verif_info = f"#{current_pred} (check {verification_state['current_check']}/3, attend #{next_check})"

            targets = TARGET_CONFIG['targets']
            examples = []
            for num in range(6, 50):
                if len(examples) >= 4:
                    break
                if get_last_digit(num) in targets:
                    suit = get_suit_for_number(num)
                    if suit:
                        examples.append(f"#{num}{suit}")

            jokes_count = len(jokes_db)

            msg = f"""📊 **STATUT**

🟢 **État:** {status}
🎯 **Source:** #{last_src}
🔍 **Prédiction:** #{last_pred if last_pred else 'Aucune'}
🔎 **Vérification:** {verif_info}

🎯 **CONFIGURATION:**
• Déclencheurs: {TARGET_CONFIG['triggers']}
• Cibles: {TARGET_CONFIG['targets']}
• Cycle: {' '.join(TARGET_CONFIG['cycle'])}
• Pré-calcul: {len(bot_state['precomputed_cycle'])} numéros

📝 **Exemples:** {' | '.join(examples)}
😄 **Blagues:** {jokes_count} enregistrées

💡 `/reset` ou `/forceunlock` si bloqué"""

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
• ✅0️⃣: {stats_bilan['win_details'].get('✅0️⃣', 0)}
• ✅1️⃣: {stats_bilan['win_details'].get('✅1️⃣', 0)}
• ✅2️⃣: {stats_bilan['win_details'].get('✅2️⃣', 0)}
• ✅3️⃣: {stats_bilan['win_details'].get('✅3️⃣', 0)}""")

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

        init_jokes()
        precompute_cycle()

        startup = f"""🤖 **BOT PRÉDICTION DÉMARRÉ** (v9)

🎯 **Configuration:**
• Déclencheurs: {TARGET_CONFIG['triggers']}
• Cibles: {TARGET_CONFIG['targets']}
• Cycle: {' '.join(TARGET_CONFIG['cycle'])}

📊 **Pré-calcul:** {len(bot_state['precomputed_cycle'])} numéros
😄 **Blagues:** {len(jokes_db)} chargées

🆕 **Nouvelle commande:** `/settriggers` pour modifier les déclencheurs

/start pour toutes les commandes"""

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
            if bot_state['is_paused']:
                await check_pause()
            if bot_state['artem_pause']:
                await check_artem_pause()
            
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logger.info("👋 Arrêt")
    finally:
        if bot_state['joke_task'] and not bot_state['joke_task'].done():
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
