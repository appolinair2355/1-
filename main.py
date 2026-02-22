#!/usr/bin/env python3
"""
Bot Telegram de Prediction - Version Corrigee
Base sur main (94).py - Extraction et verification corrigees
Port: 10000
"""
import os
import sys
import asyncio
import logging
import re
import json
from datetime import datetime, timedelta
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# =====================================================
# CONFIGURATION
# =====================================================

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

# Configuration modifiable
TARGET_CONFIG = {
    'impairs': [3, 5],
    'pairs': [0, 8],
    'triggers': {2: 3, 4: 5, 9: 0, 7: 8}
}

SUIT_CYCLE = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']
SUIT_DISPLAY = {'♦️': '♦️ Carreau', '❤️': '❤️ Coeur', '♣️': '♣️ Trefle', '♠️': '♠️ Pique'}

# =====================================================
# VARIABLES GLOBALES
# =====================================================

bot_client = None

bot_state = {
    'cycle': SUIT_CYCLE.copy(),
    'cycle_pos': 0,
    'predictions': {},
    'history': [],
    'is_paused': False,
    'pause_end': None,
    'prediction_count': 0,
    'last_source_number': None,
    'last_prediction_number': None,
}

PAUSE_AFTER = 5
PAUSE_MINUTES = [3, 4, 5]

# =====================================================
# FONCTIONS UTILITAIRES (BASEES SUR main (94).py)
# =====================================================

def extract_game_number(message):
    """Extrait le numero du message - COPIE de main (94).py"""
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

def extract_suits_from_first_group(message_text):
    """Extrait les costumes du PREMIER groupe de parentheses - COPIE de main (94).py"""
    matches = re.findall(r"\(([^)]+)\)", message_text)
    if not matches:
        return []

    first_group = matches[0]

    # Normaliser les emojis
    normalized = first_group.replace('❤️', '♥️').replace('❤', '♥️')
    normalized = normalized.replace('♠️', '♠️').replace('♦️', '♦️').replace('♣️', '♣️')
    normalized = normalized.replace('♥️', '♥️')

    suits = []
    for suit in ['♥️', '♠️', '♦️', '♣️']:
        if suit in normalized:
            suits.append(suit)

    return suits

def is_message_editing(message_text):
    """Verifie si message en cours d'edition"""
    return message_text.strip().startswith('⏰')

def is_message_finalized(message_text):
    """Verifie si message finalise"""
    return '✅' in message_text or '🔰' in message_text

def is_target_number(n):
    """Verifie si numero est une cible"""
    if n in EXCLUDED_NUMBERS or n < 1 or n > 1440:
        return False
    last_digit = n % 10
    if n % 2 == 1:
        return last_digit in TARGET_CONFIG['impairs']
    else:
        return last_digit in TARGET_CONFIG['pairs']

def get_trigger_target(trigger_num):
    """Calcule la cible a partir du declencheur"""
    last_digit = trigger_num % 10
    target_last = TARGET_CONFIG['triggers'].get(last_digit)

    if target_last is None:
        return None

    # Calculer la cible
    target = (trigger_num // 10) * 10 + target_last

    # Si target est 0 (ex: trigger 9 -> target 0), c'est invalide
    if target == 0:
        target = trigger_num + 1  # Fallback: prendre le suivant
        if not is_target_number(target):
            return None

    return target

def get_next_suit():
    """Retourne prochain costume"""
    cycle = bot_state['cycle']
    pos = bot_state['cycle_pos']
    suit = cycle[pos % len(cycle)]
    bot_state['cycle_pos'] = (pos + 1) % len(cycle)
    return suit

def format_prediction(number, suit, status=None, emoji="⏳"):
    """Formate message prediction"""
    if status:
        return f"""🎰 PRÉDICTION #{number}
🎯 Couleur: {SUIT_DISPLAY.get(suit, suit)}
📊 Statut: {emoji} {status}"""
    return f"""🎰 PRÉDICTION #{number}
🎯 Couleur: {SUIT_DISPLAY.get(suit, suit)}
📊 Statut: ⏳"""

def determine_status(pred_suit, actual_suits, pred_num, actual_num):
    """Determine statut"""
    if pred_suit not in actual_suits:
        return ("PERDU", "❌")

    distance = abs(pred_num - actual_num)

    if distance == 0:
        return ("GAGNÉ", "✅0️⃣")
    elif distance == 1:
        return ("GAGNÉ", "✅1️⃣")
    elif distance == 2:
        return ("GAGNÉ", "✅2️⃣")
    elif distance == 3:
        return ("GAGNÉ", "✅3️⃣")
    else:
        return ("PERDU", "❌")

# =====================================================
# SERVEUR WEB
# =====================================================

async def handle_health(request):
    status = "PAUSED" if bot_state['is_paused'] else "RUNNING"
    last = bot_state['last_source_number']
    return web.Response(text=f"Bot {status} | Last source: #{last}", status=200)

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

# =====================================================
# PAUSE
# =====================================================

async def check_pause():
    if bot_state['is_paused'] and bot_state['pause_end']:
        if datetime.now() >= bot_state['pause_end']:
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            logger.info("✅ Pause terminee")
            await bot_client.send_message(ADMIN_ID, "✅ Pause terminee!")
            return True
    return not bot_state['is_paused']

async def start_pause():
    import random
    minutes = random.choice(PAUSE_MINUTES)
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=minutes)

    msg = f"Pause de {minutes}min"
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, f"⏸️ {msg}")
    logger.info(f"Pause {minutes} min")

# =====================================================
# COMMANDES ADMIN
# =====================================================

async def handle_admin_commands(event):
    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    cmd = parts[0].lower()

    try:
        if cmd == '/start':
            await event.reply("""🤖 Commandes:

/settargets <impairs> <pairs> <triggers> - Modifier cibles
/setcycle <emojis> - Modifier cycle
/reset - Reset tout
/info - Voir etat (avec dernier numero source)
/next - Prochain costume
/history - Historique
/pause - Pause
/resume - Reprendre""")

        elif cmd == '/settargets':
            if len(parts) < 4:
                await event.reply(
                    f"Usage: /settargets 3,5 0,8 2:3,4:5,9:0,7:8\n"
                    f"Actuel: Impairs {TARGET_CONFIG['impairs']}, Pairs {TARGET_CONFIG['pairs']}, Triggers {TARGET_CONFIG['triggers']}"
                )
                return

            try:
                impairs = [int(x.strip()) for x in parts[1].split(',')]
                pairs = [int(x.strip()) for x in parts[2].split(',')]
                triggers = {}
                for pair in parts[3].split(','):
                    if ':' in pair:
                        t, c = pair.split(':')
                        triggers[int(t)] = int(c)

                TARGET_CONFIG['impairs'] = impairs
                TARGET_CONFIG['pairs'] = pairs
                TARGET_CONFIG['triggers'] = triggers

                await event.reply(f"✅ Cibles modifiees!\nImpairs: {impairs}\nPairs: {pairs}\nTriggers: {triggers}")

            except Exception as e:
                await event.reply(f"❌ Erreur: {e}")

        elif cmd == '/setcycle':
            if len(parts) < 2:
                await event.reply(f"Usage: /setcycle ♦️ ♣️ ❤️ ♠️\nActuel: {' '.join(bot_state['cycle'])}")
                return

            new_cycle = parts[1:]
            valid = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid]

            if invalid:
                await event.reply(f"Invalides: {invalid}")
                return

            bot_state['cycle'] = new_cycle
            bot_state['cycle_pos'] = 0
            await event.reply(f"✅ Cycle: {' '.join(new_cycle)}")

        elif cmd == '/reset':
            old_count = len(bot_state['history'])
            bot_state['predictions'] = {}
            bot_state['history'] = []
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            bot_state['cycle_pos'] = 0
            bot_state['last_prediction_number'] = None

            await event.reply(f"🔄 RESET! {old_count} predictions effacees. Pret!")
            logger.info("RESET execute")

        elif cmd == '/info':
            pending = len([p for p in bot_state['predictions'].values() if not p.get('resolved')])
            last_src = bot_state['last_source_number']
            last_pred = bot_state['last_prediction_number']

            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"

            msg = f"""📊 ETAT

{status}
Dernier numero source: #{last_src if last_src else 'Aucun'}
Derniere prediction: #{last_pred if last_pred else 'Aucune'}
Predictions avant pause: {bot_state['prediction_count']}/{PAUSE_AFTER}
En attente: {pending}

Cycle: {' '.join(bot_state['cycle'])}
Position: {bot_state['cycle_pos']}
Cibles: Impairs {TARGET_CONFIG['impairs']}, Pairs {TARGET_CONFIG['pairs']}
Triggers: {TARGET_CONFIG['triggers']}
Historique: {len(bot_state['history'])}"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\nPause: {remaining.seconds // 60} min"

            await event.reply(msg)

        elif cmd == '/next':
            cycle = bot_state['cycle']
            pos = bot_state['cycle_pos']
            next_suit = cycle[pos % len(cycle)]
            await event.reply(f"🎯 Prochain: {SUIT_DISPLAY.get(next_suit, next_suit)}")

        elif cmd == '/history':
            if not bot_state['history']:
                await event.reply("Aucune prediction")
                return

            text = "📜 Historique (5 dernieres):\n\n"
            for p in bot_state['history'][-5:]:
                status = f"{p.get('emoji', '⏳')} {p.get('status', '...')}" if p.get('status') else "⏳"
                text += f"#{p['number']} - {status}\n"
            await event.reply(text)

        elif cmd == '/pause':
            bot_state['is_paused'] = True
            await bot_client.send_message(PREDICTION_CHANNEL_ID, "Pause")
            await event.reply("⏸️ En pause")

        elif cmd == '/resume':
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            await event.reply("▶️ Repris!")

        else:
            await event.reply("Commande inconnue. /start pour la liste.")

    except Exception as e:
        logger.error(f"Erreur commande: {e}")
        await event.reply(f"❌ Erreur: {str(e)}")

# =====================================================
# GESTION MESSAGES SOURCE (CORRIGE)
# =====================================================

async def update_prediction(pred_num, suit, status, emoji):
    """Met a jour prediction existante"""
    if pred_num not in bot_state['predictions']:
        return

    pred = bot_state['predictions'][pred_num]
    new_text = format_prediction(pred_num, suit, status, emoji)

    try:
        await bot_client.edit_message(
            PREDICTION_CHANNEL_ID,
            pred['message_id'],
            new_text
        )

        pred['status'] = status
        pred['emoji'] = emoji
        pred['resolved'] = True

        logger.info(f"✅ #{pred_num} mis a jour: {status}")

    except Exception as e:
        logger.error(f"❌ Erreur edition: {e}")

async def handle_source_message(event, is_edit=False):
    """Traite messages source - CORRIGE"""
    try:
        message_text = event.message.message

        # ============================================================
        # ETAPE 1: EXTRAIRE NUMERO (methode de main (94).py)
        # ============================================================
        game_number = extract_game_number(message_text)

        if game_number is None:
            logger.debug("Aucun numero trouve")
            return

        # Mettre a jour dernier numero source
        bot_state['last_source_number'] = game_number

        is_editing = is_message_editing(message_text)
        is_finalized = is_message_finalized(message_text)

        log_type = "EDIT" if is_edit else "NEW"
        log_status = "⏰" if is_editing else ("✅" if is_finalized else "📝")
        logger.info(f"{log_status} {log_type}: #{game_number}")

        # ============================================================
        # ETAPE 2: VERIFICATION PREDICTION EN COURS
        # ============================================================
        for pred_num, pred_data in list(bot_state['predictions'].items()):
            if pred_data.get('resolved'):
                continue

            # Verifier sur pred_num, pred_num+1, pred_num+2, pred_num+3
            for offset in range(4):
                check_num = pred_num + offset

                if check_num == game_number and (is_finalized or not is_editing):
                    suits = extract_suits_from_first_group(message_text)

                    if suits:
                        status, emoji = determine_status(
                            pred_data['suit'], suits, pred_num, game_number
                        )

                        await update_prediction(pred_num, pred_data['suit'], status, emoji)

                        await bot_client.send_message(ADMIN_ID,
                            f"✅ #{pred_num} verifie sur #{game_number} (+{offset}): {status}")

                        await asyncio.sleep(2)
                    break

        # ============================================================
        # ETAPE 3: ATTENTE FINALISATION
        # ============================================================
        if is_editing:
            logger.info(f"⏰ #{game_number} en edition, attente")
            return

        # ============================================================
        # ETAPE 4: BLOQUANT - VERIFIER SI PREDICTION EN COURS
        # ============================================================
        unresolved = [p for p in bot_state['predictions'].values() if not p.get('resolved')]
        if unresolved:
            logger.info(f"⏳ {len(unresolved)} prediction(s) non resolue(s)")
            return

        # ============================================================
        # ETAPE 5: VERIFIER PAUSE
        # ============================================================
        if not await check_pause():
            logger.info("⏸️ En pause")
            return

        # ============================================================
        # ETAPE 6: VERIFIER SI DECLENCHEUR
        # ============================================================
        last_digit = game_number % 10

        if last_digit not in TARGET_CONFIG['triggers']:
            logger.info(f"ℹ️ #{game_number} pas un declencheur (_{last_digit})")
            return

        # Calculer cible
        target_num = get_trigger_target(game_number)

        if target_num is None:
            logger.warning(f"⚠️ Pas de cible pour #{game_number}")
            return

        # Verifier cible valide
        if target_num in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Cible #{target_num} exclue")
            return

        if not is_target_number(target_num):
            logger.info(f"🚫 Cible #{target_num} invalide")
            return

        # Verifier si deja predit
        if target_num in bot_state['predictions']:
            logger.info(f"⚠️ #{target_num} deja predit")
            return

        # ============================================================
        # ETAPE 7: ENVOYER PREDICTION
        # ============================================================
        suit = get_next_suit()
        msg_text = format_prediction(target_num, suit)

        sent = await bot_client.send_message(PREDICTION_CHANNEL_ID, msg_text)

        pred = {
            'number': target_num,
            'suit': suit,
            'message_id': sent.id,
            'trigger': game_number,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'resolved': False
        }

        bot_state['predictions'][target_num] = pred
        bot_state['history'].append(pred.copy())
        bot_state['last_prediction_number'] = target_num
        bot_state['prediction_count'] += 1

        logger.info(f"✅ PREDICTION: #{game_number} (_{last_digit}) → #{target_num} | {suit}")

        await bot_client.send_message(ADMIN_ID,
            f"🎯 #{target_num} ({suit}) depuis #{game_number}")

        # Verifier pause
        if bot_state['prediction_count'] >= PAUSE_AFTER:
            await start_pause()

    except Exception as e:
        logger.error(f"❌ Erreur: {e}")
        import traceback
        logger.error(traceback.format_exc())

# =====================================================
# DEMARRAGE
# =====================================================

async def start_bot():
    global bot_client

    session = os.getenv('TELEGRAM_SESSION', '')
    bot_client = TelegramClient(StringSession(session), API_ID, API_HASH)

    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connecte")

        @bot_client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def source_handler(event):
            await handle_source_message(event, is_edit=False)

        @bot_client.on(events.MessageEdited(chats=SOURCE_CHANNEL_ID))
        async def edit_handler(event):
            await handle_source_message(event, is_edit=True)

        @bot_client.on(events.NewMessage(pattern='/'))
        async def admin_handler(event):
            if event.sender_id == ADMIN_ID:
                await handle_admin_commands(event)

        startup = f"""🤖 Bot Demarre!

🎯 Cibles: {TARGET_CONFIG['impairs']} (impairs) | {TARGET_CONFIG['pairs']} (pairs)
🔗 Triggers: {TARGET_CONFIG['triggers']}
🎨 Cycle: {' '.join(bot_state['cycle'])}
⏸️ Pause: {PAUSE_AFTER} predictions ({min(PAUSE_MINUTES)}-{max(PAUSE_MINUTES)} min)

Commandes: /start, /settargets, /setcycle, /reset, /info"""

        await bot_client.send_message(ADMIN_ID, startup)
        return bot_client

    except Exception as e:
        logger.error(f"Erreur: {e}")
        return None

async def main():
    logger.info("🚀 Demarrage...")

    web = await start_web_server()
    client = await start_bot()

    if not client:
        return

    logger.info("✅ Bot operationnel")

    try:
        while True:
            if bot_state['is_paused']:
                await check_pause()
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logger.info("👋 Arret")
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
