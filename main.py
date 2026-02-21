#!/usr/bin/env python3
"""
Bot Telegram de Prediction - Version Finale
Attente message finalise, verification etendue, bloquant
Port: 10000
"""
import os
import sys
import asyncio
import logging
import re
from datetime import datetime, timedelta
from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from config import (
    API_ID, API_HASH, BOT_TOKEN, PORT, ADMIN_ID,
    SOURCE_CHANNEL_ID, PREDICTION_CHANNEL_ID,
    EXCLUDED_NUMBERS
)

# =====================================================
# CONFIGURATION MODIFIABLE PAR COMMANDES
# =====================================================

# Configuration par defaut (peut etre modifiee par /settargets)
TARGET_CONFIG = {
    'impairs': [3, 5],  # Fins de numero impairs a predire
    'pairs': [0, 8],    # Fins de numero pairs a predire
    'triggers': {       # Declencheurs -> cibles
        2: 3,  # _2 -> _3
        4: 5,  # _4 -> _5
        9: 0,  # _9 -> _0
        7: 8,  # _7 -> _8
    }
}

SUIT_CYCLE = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']

# =====================================================
# VARIABLES GLOBALES
# =====================================================

bot_client = None

bot_state = {
    'cycle': SUIT_CYCLE.copy(),
    'cycle_pos': 0,
    'predictions': {},      # num -> {msg_id, suit, status, message_id_channel}
    'history': [],
    'is_paused': False,
    'pause_end': None,
    'prediction_count': 0,
    'last_prediction_num': None,
    'pending_checks': {},   # numeros en attente de verification
    'editing_messages': set(),  # numeros en cours d'edition (⏰)
}

PAUSE_AFTER = 5
PAUSE_MINUTES = [3, 4, 5]  # Aleatoire entre 3-5 min

# =====================================================
# FONCTIONS UTILITAIRES
# =====================================================

def is_target_number(n):
    """Verifie si le numero est une cible selon la config"""
    if n in EXCLUDED_NUMBERS:
        return False
    last_digit = n % 10
    if n % 2 == 1:  # Impair
        return last_digit in TARGET_CONFIG['impairs']
    else:  # Pair
        return last_digit in TARGET_CONFIG['pairs']

def get_trigger_for_target(target_last_digit):
    """Trouve le declencheur pour une cible"""
    for trigger, target in TARGET_CONFIG['triggers'].items():
        if target == target_last_digit:
            return trigger
    return None

def get_target_for_trigger(trigger_last_digit):
    """Trouve la cible pour un declencheur"""
    return TARGET_CONFIG['triggers'].get(trigger_last_digit)

def extract_number_and_status(text):
    """
    Extrait numero et statut du message
    Retourne: (numero, is_final, is_editing)
    """
    # Chercher numero #N
    match = re.search(r'#N\s*(\d+)', text)
    if not match:
        return None, False, False

    num = int(match.group(1))

    # Verifier si en cours d'edition (⏰)
    is_editing = '⏰' in text or '▶️' in text or '▶' in text

    # Verifier si finalise (✅ ou 🔰)
    is_final = '✅' in text or '🔰' in text

    return num, is_final, is_editing

def extract_suits_from_message(text):
    """
    Extrait les costumes du premier groupe de parentheses
    Ex: "4(J♥️4♠️10♦️)" -> ['♥️', '♠️', '♦️']
    """
    # Chercher premier groupe de parentheses
    match = re.search(r'\(([^)]+)\)', text)
    if not match:
        return []

    content = match.group(1)

    # Extraire les emojis de costumes
    suits = re.findall(r'[♦️♥️♣️♠️]', content)
    return suits

def get_next_suit():
    """Retourne le prochain costume du cycle"""
    cycle = bot_state['cycle']
    pos = bot_state['cycle_pos']
    suit = cycle[pos % len(cycle)]
    bot_state['cycle_pos'] = (pos + 1) % len(cycle)
    return suit

def get_suit_name(emoji):
    names = {'♦️': 'Carreau', '❤️': 'Coeur', '♣️': 'Trefle', '♠️': 'Pique'}
    return names.get(emoji, emoji)

def format_prediction(number, suit, status=None, emoji="⏳"):
    if status:
        return f"""🎰 PRÉDICTION #{number}
🎯 Couleur: {suit} {get_suit_name(suit)}
📊 Statut: {emoji} {status}"""
    return f"""🎰 PRÉDICTION #{number}
🎯 Couleur: {suit} {get_suit_name(suit)}
📊 Statut: ⏳"""

def determine_status(pred_suit, actual_suits, pred_num, actual_num):
    """
    Determine le statut selon les regles:
    - Si costume predit dans les costumes reels -> GAGNE selon distance
    - Sinon -> PERDU
    """
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
    pending = len([p for p in bot_state['predictions'].values() if not p.get('resolved')])
    return web.Response(text=f"Bot {status} | Pending: {pending}", status=200)

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
    """Verifie si la pause est terminee"""
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
    """Demarre une pause aleatoire"""
    import random
    minutes = random.choice(PAUSE_MINUTES)
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=minutes)

    msg = f"Pause de {minutes}min"
    await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)
    await bot_client.send_message(ADMIN_ID, f"⏸️ {msg} - Reprise a {bot_state['pause_end'].strftime('%H:%M')}")

    logger.info(f"Pause {minutes} min")

# =====================================================
# VERIFICATION ETENDUE
# =====================================================

async def verify_prediction_extended(pred_num, pred_suit, pred_data):
    """
    Verifie la prediction sur num, num+1, num+2, num+3
    Retourne True si trouve et mis a jour, False sinon
    """
    # Recuperer les derniers messages du canal source
    # Note: Dans la pratique, il faudrait stocker l'historique des messages
    # Pour l'instant, on verifie lors de la reception de chaque message

    for offset in range(4):  # 0, 1, 2, 3
        check_num = pred_num + offset

        # Si ce numero est dans nos donnees recues
        if check_num in bot_state['pending_checks']:
            msg_data = bot_state['pending_checks'][check_num]
            actual_suits = msg_data['suits']

            status, emoji = determine_status(pred_suit, actual_suits, pred_num, check_num)

            # Mettre a jour la prediction
            await update_prediction_message(pred_num, pred_suit, status, emoji)
            return True

    return False

async def update_prediction_message(pred_num, suit, status, emoji):
    """Met a jour le message de prediction avec le statut"""
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

        # Nettoyer
        if pred_num in bot_state['pending_checks']:
            del bot_state['pending_checks'][pred_num]

    except Exception as e:
        logger.error(f"❌ Erreur edition: {e}")

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
/reset - Reset tout et debloquer
/info - Voir etat complet
/next - Prochain costume
/history - Historique
/pause - Mettre en pause
/resume - Reprendre""")

        elif cmd == '/settargets':
            """Modifie les cibles et declencheurs"""
            if len(parts) < 4:
                await event.reply(
                    "Usage: /settargets <impairs> <pairs> <triggers>\n"
                    "Ex: /settargets 3,5 0,8 2:3,4:5,9:0,7:8\n\n"
                    f"Actuel:\n"
                    f"Impairs: {TARGET_CONFIG['impairs']}\n"
                    f"Pairs: {TARGET_CONFIG['pairs']}\n"
                    f"Declencheurs: {TARGET_CONFIG['triggers']}"
                )
                return

            try:
                # Parser impairs
                impairs = [int(x.strip()) for x in parts[1].split(',')]
                # Parser pairs  
                pairs = [int(x.strip()) for x in parts[2].split(',')]
                # Parser triggers (format: 2:3,4:5...)
                triggers = {}
                for pair in parts[3].split(','):
                    if ':' in pair:
                        t, c = pair.split(':')
                        triggers[int(t)] = int(c)

                # Mettre a jour
                TARGET_CONFIG['impairs'] = impairs
                TARGET_CONFIG['pairs'] = pairs
                TARGET_CONFIG['triggers'] = triggers

                await event.reply(
                    f"✅ Cibles modifiees!\n\n"
                    f"Impairs: {impairs}\n"
                    f"Pairs: {pairs}\n"
                    f"Declencheurs: {triggers}"
                )

            except Exception as e:
                await event.reply(f"❌ Erreur format: {e}")

        elif cmd == '/setcycle':
            if len(parts) < 2:
                await event.reply(f"Usage: /setcycle ♦️ ♣️ ❤️ ♠️\nActuel: {' '.join(bot_state['cycle'])}")
                return

            new_cycle = parts[1:]
            valid = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid]

            if invalid:
                await event.reply(f"Invalides: {invalid}\nValides: {valid}")
                return

            old = bot_state['cycle'].copy()
            bot_state['cycle'] = new_cycle
            bot_state['cycle_pos'] = 0

            await event.reply(f"✅ Cycle modifie!\n{old} → {new_cycle}")

        elif cmd == '/reset':
            """Reset complet et debloque"""
            old_pending = len([p for p in bot_state['predictions'].values() if not p.get('resolved')])

            bot_state['predictions'] = {}
            bot_state['history'] = []
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            bot_state['cycle_pos'] = 0
            bot_state['last_prediction_num'] = None
            bot_state['pending_checks'] = {}
            bot_state['editing_messages'] = set()

            await event.reply(
                f"🔄 RESET EXECUTE\n\n"
                f"✅ {old_pending} predictions en attente effacees\n"
                f"✅ Cycle reset\n"
                f"✅ Stocks vides\n"
                f"🚀 Pret pour nouvelles predictions!"
            )
            logger.info("RESET execute")

        elif cmd == '/info':
            pending = len([p for p in bot_state['predictions'].values() if not p.get('resolved')])
            editing = len(bot_state['editing_messages'])

            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"

            msg = f"""📊 ETAT COMPLET

{status}
Predictions avant pause: {bot_state['prediction_count']}/{PAUSE_AFTER}
En attente statut: {pending}
En cours d'edition: {editing}

🎨 CYCLE
Actuel: {' '.join(bot_state['cycle'])}
Position: {bot_state['cycle_pos']}/{len(bot_state['cycle'])}
Prochain: {bot_state['cycle'][bot_state['cycle_pos'] % len(bot_state['cycle'])]}

🎯 CIBLES
Impairs: {TARGET_CONFIG['impairs']}
Pairs: {TARGET_CONFIG['pairs']}
Declencheurs: {TARGET_CONFIG['triggers']}

📈 TOTAL
Historique: {len(bot_state['history'])} predictions"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\n⏱️ Pause: {remaining.seconds // 60} min restantes"

            await event.reply(msg)

        elif cmd == '/next':
            cycle = bot_state['cycle']
            pos = bot_state['cycle_pos']
            next_suit = cycle[pos % len(cycle)]
            await event.reply(f"🎯 Prochain: {next_suit} {get_suit_name(next_suit)} (pos {pos})")

        elif cmd == '/history':
            if not bot_state['history']:
                await event.reply("Aucune prediction")
                return

            text = "📜 Historique (5 dernieres):\n\n"
            for p in bot_state['history'][-5:]:
                status = f"{p.get('emoji', '⏳')} {p.get('status', '...')}" if p.get('status') else "⏳"
                text += f"#{p['number']} {p['suit']} - {status}\n"
            await event.reply(text)

        elif cmd == '/pause':
            bot_state['is_paused'] = True
            await bot_client.send_message(PREDICTION_CHANNEL_ID, "Pause manuelle")
            await event.reply("⏸️ En pause. /resume pour reprendre.")

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
# GESTION MESSAGES SOURCE
# =====================================================

async def handle_source_message(event):
    """Traite les messages du canal source"""
    try:
        text = event.message.text or ""

        # ============================================================
        # ETAPE 1: Extraire numero et statut
        # ============================================================
        num, is_final, is_editing = extract_number_and_status(text)

        if not num:
            return

        logger.info(f"📩 #{num} | Final:{is_final} | Editing:{is_editing}")

        # ============================================================
        # ETAPE 2: Si en cours d'edition, on attend (mais on garde en memoire)
        # ============================================================
        if is_editing:
            bot_state['editing_messages'].add(num)
            logger.info(f"⏰ #{num} en cours d'edition - attente")
            return

        # Si etait en editing et maintenant final, on retire
        if num in bot_state['editing_messages']:
            bot_state['editing_messages'].discard(num)

        # ============================================================
        # ETAPE 3: Verifier exclusions
        # ============================================================
        if num in EXCLUDED_NUMBERS:
            return

        if num < 1 or num > 1440:
            return

        # ============================================================
        # ETAPE 4: Stocker pour verification (meme si pas final, on garde)
        # ============================================================
        suits = extract_suits_from_message(text)
        if suits:
            bot_state['pending_checks'][num] = {
                'suits': suits,
                'final': is_final,
                'text': text
            }

        # ============================================================
        # ETAPE 5: Verifier les predictions en attente
        # ============================================================
        for pred_num, pred_data in list(bot_state['predictions'].items()):
            if pred_data.get('resolved'):
                continue

            # Verifier sur pred_num, pred_num+1, pred_num+2, pred_num+3
            for offset in range(4):
                check_num = pred_num + offset

                if check_num == num and is_final:
                    status, emoji = determine_status(
                        pred_data['suit'], suits, pred_num, num
                    )

                    await update_prediction_message(pred_num, pred_data['suit'], status, emoji)

                    # Notifier admin
                    await bot_client.send_message(ADMIN_ID,
                        f"✅ #{pred_num} verifie sur #{num} (offset +{offset}): {status}")
                    break

        # ============================================================
        # ETAPE 6: Verifier si on peut faire une nouvelle prediction
        # ============================================================

        # BLOQUANT: Si prediction non resolue, on ne fait pas de nouvelle
        unresolved = [p for p in bot_state['predictions'].values() if not p.get('resolved')]
        if unresolved:
            logger.info(f"⏳ {len(unresolved)} prediction(s) non resolue(s) - attente")
            return

        # Verifier pause
        if not await check_pause():
            logger.info("⏸️ En pause - pas de nouvelle prediction")
            return

        # ============================================================
        # ETAPE 7: Verifier si c'est un declencheur
        # ============================================================
        last_digit = num % 10
        target_last = get_target_for_trigger(last_digit)

        if target_last is None:
            logger.info(f"ℹ️ #{num} pas un declencheur")
            return

        # Calculer cible
        target_num = (num // 10) * 10 + target_last

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
        # ETAPE 8: Faire la prediction
        # ============================================================
        suit = get_next_suit()
        msg_text = format_prediction(target_num, suit)

        sent = await bot_client.send_message(PREDICTION_CHANNEL_ID, msg_text)

        pred = {
            'number': target_num,
            'suit': suit,
            'message_id': sent.id,
            'trigger': num,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'resolved': False
        }

        bot_state['predictions'][target_num] = pred
        bot_state['history'].append(pred.copy())
        bot_state['last_prediction_num'] = target_num
        bot_state['prediction_count'] += 1

        logger.info(f"✅ Prediction: #{num}→#{target_num} | {suit}")

        await bot_client.send_message(ADMIN_ID,
            f"🎯 #{target_num} ({suit}) depuis #{num}")

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

    from telethon import TelegramClient, events
    from telethon.sessions import StringSession

    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Configuration incomplete!")
        return None

    session = os.getenv('TELEGRAM_SESSION', '')
    bot_client = TelegramClient(StringSession(session), API_ID, API_HASH)

    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connecte")

        @bot_client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def source_handler(event):
            await handle_source_message(event)

        @bot_client.on(events.NewMessage(pattern='/'))
        async def admin_handler(event):
            if event.sender_id == ADMIN_ID:
                await handle_admin_commands(event)

        startup = f"""🤖 Bot Demarre!

🎯 Cibles: {TARGET_CONFIG['impairs']} (impairs) | {TARGET_CONFIG['pairs']} (pairs)
🔗 Declencheurs: {TARGET_CONFIG['triggers']}
🎨 Cycle: {' '.join(bot_state['cycle'])}
⏸️ Pause: {PAUSE_AFTER} predictions ({min(PAUSE_MINUTES)}-{max(PAUSE_MINUTES)} min)
✅ Verification etendue (num, num+1, num+2, num+3)
⏰ Attente messages finalises
🔒 Bloquant (pas de nouvelle si non resolu)

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
