#!/usr/bin/env python3
"""
Bot Telegram de Prediction - Base sur main (94)(1).py
Logique: Cibles _3,_5 (impairs) et _0,_8 (pairs)
Declencheurs: _2,_4,_9,_7
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

# Configuration modifiable par /settargets
TARGET_CONFIG = {
    'impairs': [3, 5],
    'pairs': [0, 8],
    'triggers': {2: 3, 4: 5, 9: 0, 7: 8}
}

SUIT_CYCLE = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']
SUIT_DISPLAY = {'♦️': '♦️ Carreau', '❤️': '❤️ Coeur', '♣️': '♣️ Trefle', '♠️': '♠️ Pique'}

PAUSE_AFTER = 5
PAUSE_MINUTES = [3, 4, 5]

# ============================================================
# VARIABLES GLOBALES (comme main (94)(1).py)
# ============================================================

bot_client = None

bot_state = {
    'cycle': SUIT_CYCLE.copy(),
    'cycle_pos': 0,
    'predictions_count': 0,
    'is_paused': False,
    'pause_end': None,
    'last_source_number': 0,
    'last_prediction_number': None,
    'predictions_history': [],
}

# Etat de verification (comme verification_state dans main (94)(1).py)
verification_state = {
    'predicted_number': None,
    'predicted_suit': None,
    'current_check': 0,
    'message_id': None,
    'channel_id': None,
    'status': None,
    'base_game': None
}

stats_bilan = {
    'total': 0, 'wins': 0, 'losses': 0,
    'win_details': {'✅0️⃣': 0, '✅1️⃣': 0, '✅2️⃣': 0, '✅3️⃣': 0},
    'loss_details': {'❌': 0}
}

# ============================================================
# FONCTIONS UTILITAIRES (COPIEES de main (94)(1).py)
# ============================================================

def extract_game_number(message):
    """Extrait le numero de jeu du message (supporte #N, #R, #X, etc.)"""
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
    """Extrait les costumes du PREMIER groupe de parentheses"""
    matches = re.findall(r"\(([^)]+)\)", message_text)
    if not matches:
        return []

    first_group = matches[0]

    normalized = first_group.replace('❤️', '♥️').replace('❤', '♥️')
    normalized = normalized.replace('♠️', '♠️').replace('♦️', '♦️').replace('♣️', '♣️')
    normalized = normalized.replace('♥️', '♥️')

    suits = []
    for suit in ['♥️', '♠️', '♦️', '♣️']:
        if suit in normalized:
            suits.append(suit)

    return suits

def is_message_editing(message_text):
    """Verifie si le message est en cours d'edition (commence par ⏰)"""
    return message_text.strip().startswith('⏰')

def is_message_finalized(message_text):
    """Verifie si le message est finalise (contient ✅ ou 🔰)"""
    return '✅' in message_text or '🔰' in message_text

def is_target_number(n):
    """Verifie si le numero est une cible"""
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

    target = (trigger_num // 10) * 10 + target_last

    # Si target est 0, prendre le suivant (cas special pour _0)
    if target == 0:
        target = trigger_num + 1
        if not is_target_number(target):
            return None

    return target

def get_next_suit():
    """Retourne le prochain costume du cycle"""
    cycle = bot_state['cycle']
    pos = bot_state['cycle_pos']
    suit = cycle[pos % len(cycle)]
    bot_state['cycle_pos'] = (pos + 1) % len(cycle)
    return suit

def format_prediction(number, suit, status=None, emoji="⏳"):
    """Formate le message de prediction"""
    if status:
        return f"""🎰 **PRÉDICTION #{number}**
🎯 Couleur: {SUIT_DISPLAY.get(suit, suit)}
📊 Statut: {emoji} {status}"""
    return f"""🎰 **PRÉDICTION #{number}**
🎯 Couleur: {SUIT_DISPLAY.get(suit, suit)}
⏳ Statut: EN ATTENTE DU RÉSULTAT..."""

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
# PAUSE
# ============================================================

async def check_pause():
    """Verifie si la pause est terminee"""
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
    """Demarre une pause aleatoire"""
    import random
    minutes = random.choice(PAUSE_MINUTES)
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=minutes)

    msg = f"Pause de {minutes}min"
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, f"⏸️ {msg}")
    logger.info(f"Pause {minutes} min")

# ============================================================
# SYSTEME DE PREDICTION ET VERIFICATION (comme main (94)(1).py)
# ============================================================

async def send_prediction(target_game, predicted_suit, base_game):
    """Envoie une prediction au canal - COPIE de main (94)(1).py"""
    global verification_state

    if verification_state['predicted_number'] is not None:
        logger.error(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en cours!")
        return False

    try:
        prediction_text = format_prediction(target_game, predicted_suit)
        sent_msg = await bot_client.send_message(PREDICTION_CHANNEL_ID, prediction_text)

        verification_state = {
            'predicted_number': target_game,
            'predicted_suit': predicted_suit,
            'current_check': 0,
            'message_id': sent_msg.id,
            'channel_id': PREDICTION_CHANNEL_ID,
            'status': 'pending',
            'base_game': base_game
        }

        bot_state['last_prediction_number'] = target_game
        bot_state['predictions_count'] += 1
        bot_state['predictions_history'].append({
            'number': target_game,
            'suit': predicted_suit,
            'trigger': base_game,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })

        logger.info(f"🚀 PRÉDICTION #{target_game} ({predicted_suit}) LANCÉE")
        logger.info(f"🔍 Attente vérification: #{target_game} (check 0/3)")

        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi prédiction: {e}")
        return False

async def update_prediction_status(status):
    """Met a jour le statut de la prediction - COPIE de main (94)(1).py"""
    global verification_state, stats_bilan

    if verification_state['predicted_number'] is None:
        logger.error("❌ Aucune prédiction à mettre à jour")
        return False

    try:
        predicted_num = verification_state['predicted_number']
        predicted_suit = verification_state['predicted_suit']

        if status == "❌":
            status_text = "❌ PERDU"
        else:
            status_text = f"{status} GAGNÉ"

        updated_text = format_prediction(predicted_num, predicted_suit, status_text, status)

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

        logger.info(f"🔓 SYSTÈME LIBÉRÉ - Nouvelle prédiction possible")

        # Reset verification_state
        verification_state = {
            'predicted_number': None, 'predicted_suit': None,
            'current_check': 0, 'message_id': None,
            'channel_id': None, 'status': None, 'base_game': None
        }

        return True

    except Exception as e:
        logger.error(f"❌ Erreur mise à jour statut: {e}")
        return False

async def process_verification_step(game_number, message_text):
    """Traite UNE étape de vérification - COPIE de main (94)(1).py"""
    global verification_state

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
    logger.info(f"🔍 Vérification #{game_number}: premier groupe contient {suits}, attendu {predicted_suit}")

    if predicted_suit in suits:
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
    """Verifie et lance une prediction - ADAPTE pour la logique de l'utilisateur"""

    if verification_state['predicted_number'] is not None:
        logger.warning(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en attente. Déclencheur #{game_number} ignoré.")
        return

    if not await check_pause():
        logger.info("⏸️ En pause")
        return

    # Verifier si c'est un declencheur
    last_digit = game_number % 10
    if last_digit not in TARGET_CONFIG['triggers']:
        logger.info(f"ℹ️ #{game_number} pas un déclencheur (_{last_digit})")
        return

    target_num = get_trigger_target(game_number)
    if not target_num:
        logger.warning(f"⚠️ Pas de cible pour #{game_number}")
        return

    if target_num in EXCLUDED_NUMBERS:
        logger.info(f"🚫 Cible #{target_num} exclue")
        return

    if not is_target_number(target_num):
        logger.info(f"🚫 Cible #{target_num} invalide")
        return

    suit = get_next_suit()
    success = await send_prediction(target_num, suit, game_number)

    if success and bot_state['predictions_count'] >= PAUSE_AFTER:
        await start_pause()

async def process_source_message(event, is_edit=False):
    """Traite les messages du canal source - COPIE de main (94)(1).py"""
    global bot_state

    try:
        message_text = event.message.message
        game_number = extract_game_number(message_text)

        if game_number is None:
            return

        is_editing = is_message_editing(message_text)
        is_finalized = is_message_finalized(message_text)

        log_type = "ÉDITÉ" if is_edit else "NOUVEAU"
        log_status = "⏰" if is_editing else ("✅" if is_finalized else "📝")
        logger.info(f"📩 {log_status} {log_type}: #{game_number}")

        # Mettre a jour dernier numero source
        bot_state['last_source_number'] = game_number

        # ============================================================
        # VERIFICATION PREDICTION EN COURS
        # ============================================================
        if verification_state['predicted_number'] is not None:
            predicted_num = verification_state['predicted_number']
            current_check = verification_state['current_check']
            expected_number = predicted_num + current_check

            if is_editing and game_number == expected_number:
                logger.info(f"⏳ Message #{game_number} en édition, attente finalisation (✅/🔰)")
                return

            if game_number == expected_number:
                if is_finalized or not is_editing:
                    logger.info(f"✅ Numéro #{game_number} finalisé/disponible, vérification...")
                    await process_verification_step(game_number, message_text)

                    if verification_state['predicted_number'] is not None:
                        logger.info(f"⏳ Prédiction #{verification_state['predicted_number']} toujours en cours")
                        return
                    else:
                        logger.info("✅ Vérification terminée, système libre")
                else:
                    logger.info(f"⏳ Attente finalisation pour #{game_number}")
            else:
                logger.info(f"⏭️ Attente #{expected_number}, reçu #{game_number}")

            return

        # ============================================================
        # LANCER NOUVELLE PREDICTION
        # ============================================================
        await check_and_launch_prediction(game_number)

    except Exception as e:
        logger.error(f"❌ Erreur traitement message: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ============================================================
# COMMANDES ADMIN (comme main (94)(1).py)
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

/settargets <impairs> <pairs> <triggers> - Modifier cibles
/setcycle <emojis> - Modifier cycle
/reset - Reset tout et debloquer
/info - Voir etat complet
/next - Prochain costume
/bilan - Statistiques
/pause - Pause
/resume - Reprendre""")

        elif cmd == '/settargets':
            if len(parts) < 4:
                await event.respond(
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

                await event.respond(f"✅ Cibles modifiées!\nImpairs: {impairs}\nPairs: {pairs}\nTriggers: {triggers}")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/setcycle':
            if len(parts) < 2:
                await event.respond(f"Usage: /setcycle ♦️ ♣️ ❤️ ♠️\nActuel: {' '.join(bot_state['cycle'])}")
                return

            new_cycle = parts[1:]
            valid = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid]

            if invalid:
                await event.respond(f"Invalides: {invalid}")
                return

            bot_state['cycle'] = new_cycle
            bot_state['cycle_pos'] = 0
            await event.respond(f"✅ Cycle: {' '.join(new_cycle)}")

        elif cmd == '/reset':
            """Reset complet et debloque"""
            global verification_state
            old_pred = verification_state['predicted_number']

            bot_state['predictions_count'] = 0
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['cycle_pos'] = 0

            verification_state = {
                'predicted_number': None, 'predicted_suit': None,
                'current_check': 0, 'message_id': None,
                'channel_id': None, 'status': None, 'base_game': None
            }

            await event.respond(f"🔄 RESET!{f' (prédiction #{old_pred} effacée)' if old_pred else ''} Système libéré!")
            logger.info("RESET exécuté")

        elif cmd == '/info':
            """Info complete avec dernier numero source"""
            last_src = bot_state['last_source_number']
            last_pred = bot_state['last_prediction_number']
            current_pred = verification_state['predicted_number']

            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"

            verif_info = "Aucune"
            if current_pred:
                next_check = current_pred + verification_state['current_check']
                verif_info = f"#{current_pred} (check {verification_state['current_check']}/3, attend #{next_check})"

            msg = f"""📊 **STATUT SYSTÈME**

🟢 **État:** {status}
🎯 **Dernier numéro source:** #{last_src}
🔍 **Dernière prédiction:** #{last_pred if last_pred else 'Aucune'}
🔎 **Vérification en cours:** {verif_info}
📊 **Compteur pause:** {bot_state['predictions_count']}/{PAUSE_AFTER}

🎨 **Cycle:** {' '.join(bot_state['cycle'])}
📍 **Position:** {bot_state['cycle_pos']}/{len(bot_state['cycle'])}

🎯 **Cibles:** Impairs {TARGET_CONFIG['impairs']} | Pairs {TARGET_CONFIG['pairs']}
🔗 **Déclencheurs:** {TARGET_CONFIG['triggers']}

💡 /reset si bloqué"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\n⏸️ **Pause:** {remaining.seconds // 60} min restantes"

            await event.respond(msg)

        elif cmd == '/next':
            cycle = bot_state['cycle']
            pos = bot_state['cycle_pos']
            next_suit = cycle[pos % len(cycle)]
            await event.respond(f"🎯 Prochain: {SUIT_DISPLAY.get(next_suit, next_suit)}")

        elif cmd == '/bilan':
            if stats_bilan['total'] == 0:
                await event.respond("📊 Aucune prédiction enregistrée")
                return

            win_rate = (stats_bilan['wins'] / stats_bilan['total']) * 100

            await event.respond(f"""📊 **BILAN PRÉDICTIONS**

🎯 **Total:** {stats_bilan['total']}
✅ **Victoires:** {stats_bilan['wins']} ({win_rate:.1f}%)
❌ **Défaites:** {stats_bilan['losses']}

**Détails victoires:**
• Immédiat (N): {stats_bilan['win_details'].get('✅0️⃣', 0)}
• 2ème chance (N+1): {stats_bilan['win_details'].get('✅1️⃣', 0)}
• 3ème chance (N+2): {stats_bilan['win_details'].get('✅2️⃣', 0)}
• 4ème chance (N+3): {stats_bilan['win_details'].get('✅3️⃣', 0)}""")

        elif cmd == '/pause':
            bot_state['is_paused'] = True
            await bot_client.send_message(PREDICTION_CHANNEL_ID, "Pause")
            await event.respond("⏸️ En pause")

        elif cmd == '/resume':
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            await event.respond("▶️ Repris!")

        else:
            await event.respond("Commande inconnue. /start pour la liste.")

    except Exception as e:
        logger.error(f"Erreur commande: {e}")
        await event.respond(f"❌ Erreur: {str(e)}")

# ============================================================
# DEMARRAGE
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

        startup = f"""🤖 **BOT PRÉDICTION DÉMARRÉ**

🎯 **Cibles:** {TARGET_CONFIG['impairs']} (impairs) | {TARGET_CONFIG['pairs']} (pairs)
🔗 **Déclencheurs:** {TARGET_CONFIG['triggers']}
🎨 **Cycle:** {' '.join(bot_state['cycle'])}
⏸️ **Pause:** {PAUSE_AFTER} prédictions ({min(PAUSE_MINUTES)}-{max(PAUSE_MINUTES)} min)

✅ Système de vérification: ACTIVÉ (N, N+1, N+2, N+3)
⏰ Attente messages finalisés: ACTIVÉ
🔒 Bloquant: ACTIVÉ

Commandes: /start, /settargets, /setcycle, /reset, /info, /bilan"""

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
