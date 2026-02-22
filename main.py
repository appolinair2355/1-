#!/usr/bin/env python3
"""
Bot Telegram de Prediction - CORRIGÉ v6
Messages simplifiés
"""
import os
import sys
import asyncio
import logging
import re
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
PAUSE_MINUTES = [3, 4, 5]
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
    """Messages de prédiction simplifiés"""
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
📊 Statут : ✅ Gagné"""
    
    elif status == "✅1️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅ Gagné (N+1)"""
    
    elif status == "✅2️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅ Gagné (N+2)"""
    
    elif status == "✅3️⃣":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ✅ Gagné (N+3)"""
    
    elif status == "❌":
        return f"""🤖 Бот №2
🎰 Прогноз #{number}
🎯 Couleur : {suit_name} Cœur
📊 Statут : ❌ Perdu"""
    
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
    status = "PAUSED" if bot_state['is_paused'] else "RUNNING"
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
# PAUSE ET TIMEOUT
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
# SYSTÈME DE PRÉDICTION ET VÉRIFICATION
# ============================================================

async def send_prediction(target_game, predicted_suit, base_game):
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

            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"
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

🟢 **État:** {status}
🎯 **Source:** #{last_src}
🔍 **Prédiction:** #{last_pred if last_pred else 'Aucune'}
🔎 **Vérification:** {verif_info}
📊 **Pause:** {bot_state['predictions_count']}/{PAUSE_AFTER}

🎯 **CIBLES:** {TARGET_CONFIG['targets']}
🎨 **Cycle:** {' '.join(TARGET_CONFIG['cycle'])}
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

        startup = f"""🤖 **BOT PRÉDICTION DÉMARRÉ** (v6)

🎯 **Cibles:** {TARGET_CONFIG['targets']}
🎨 **Cycle:** {' '.join(TARGET_CONFIG['cycle'])}
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
            if bot_state['is_paused']:
                await check_pause()
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logger.info("👋 Arrêt")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)
