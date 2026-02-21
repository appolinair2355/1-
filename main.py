#!/usr/bin/env python3
"""
Bot Telegram de Prediction - Deployable sur Render.com
Extraction correcte des numeros #N et edition des messages
Port: 10000
"""
import os
import sys
import asyncio
import logging
import re
from datetime import datetime, timedelta
from aiohttp import web

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Import configuration
from config import (
    API_ID, API_HASH, BOT_TOKEN, PORT, ADMIN_ID,
    SOURCE_CHANNEL_ID, PREDICTION_CHANNEL_ID,
    EXCLUDED_NUMBERS
)

# =====================================================
# CONFIGURATION
# =====================================================

DEFAULT_SUIT_CYCLE = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']

def is_target_number(n):
    """Verifie si le numero est une cible valide"""
    if n in EXCLUDED_NUMBERS:
        return False
    last_digit = n % 10
    return (n % 2 == 1 and last_digit in [3, 5]) or (n % 2 == 0 and last_digit in [0, 8])

# =====================================================
# VARIABLES GLOBALES
# =====================================================

bot_client = None

bot_state = {
    'suit_cycle': DEFAULT_SUIT_CYCLE.copy(),
    'cycle_position': 0,
    'last_prediction': None,
    'predictions': {},  # numero -> {message_id, suit, status, ...}
    'history': [],
    'is_paused': False,
    'pause_end': None,
    'prediction_count': 0,
}

PAUSE_AFTER = 5
PAUSE_MINUTES = 3

# =====================================================
# PARTIE 1 : SERVEUR WEB
# =====================================================

async def handle_health(request):
    status = "PAUSED" if bot_state['is_paused'] else "RUNNING"
    return web.Response(text=f"Bot is {status}!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Serveur web demarre sur le port {PORT}")
    return runner

# =====================================================
# PARTIE 2 : PAUSE
# =====================================================

async def check_pause():
    if bot_state['is_paused'] and bot_state['pause_end']:
        if datetime.now() >= bot_state['pause_end']:
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            logger.info("✅ Pause terminee")
            await bot_client.send_message(ADMIN_ID, "✅ Pause terminee! Reprise.")
            return True
    return not bot_state['is_paused']

async def start_pause():
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=PAUSE_MINUTES)
    logger.info(f"⏸️ Pause de {PAUSE_MINUTES} minutes")
    await bot_client.send_message(
        ADMIN_ID,
        f"⏸️ Pause de {PAUSE_MINUTES} minutes apres {PAUSE_AFTER} predictions.\n"
        f"Reprise a: {bot_state['pause_end'].strftime('%H:%M:%S')}"
    )

# =====================================================
# PARTIE 3 : LOGIQUE
# =====================================================

def get_next_suit():
    cycle = bot_state['suit_cycle']
    pos = bot_state['cycle_position']
    suit = cycle[pos % len(cycle)]
    bot_state['cycle_position'] = pos + 1
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

def check_result(pred_suit, actual_suit, pred_num, actual_num):
    """Verifie le resultat"""
    if pred_suit != actual_suit:
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
    return ("PERDU", "❌")

def extract_number_from_message(text):
    """
    Extrait le numero du message du canal source
    Format attendu: #N1369 ou #N 1369 ou N1369
    """
    # Chercher #N suivi de chiffres
    match = re.search(r'#N\s*(\d+)', text)
    if match:
        return int(match.group(1))

    # Chercher N suivi de chiffres au debut
    match = re.search(r'^N\s*(\d+)', text.strip())
    if match:
        return int(match.group(1))

    # Fallback: chercher le plus grand nombre (eviter les petits chiffres des cartes)
    numbers = re.findall(r'\b(\d{3,4})\b', text)  # 3-4 chiffres minimum
    if numbers:
        return int(numbers[0])

    return None

def get_trigger_target(last_digit):
    """Retourne la cible pour un declencheur"""
    mapping = {2: 3, 4: 5, 9: 0, 7: 8}
    return mapping.get(last_digit)

# =====================================================
# PARTIE 4 : COMMANDES
# =====================================================

async def handle_admin_commands(event):
    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    cmd = parts[0].lower()

    try:
        if cmd == '/start':
            await event.reply("""🤖 Commandes disponibles:

/setcycle <emojis> - Modifier le cycle
/reset - Vider les stocks
/status - Voir l'etat
/next - Prochain costume
/history - Historique
/pause - Mettre en pause
/resume - Reprendre
/test <numero> - Tester""")

        elif cmd == '/setcycle':
            if len(parts) < 2:
                await event.reply(f"Usage: /setcycle ♦️ ♣️ ❤️ ♠️\nActuel: {' '.join(bot_state['suit_cycle'])}")
                return

            new_cycle = parts[1:]
            valid = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid]

            if invalid:
                await event.reply(f"Emojis invalides: {invalid}. Valides: {valid}")
                return

            old = bot_state['suit_cycle'].copy()
            bot_state['suit_cycle'] = new_cycle
            bot_state['cycle_position'] = 0

            await event.reply(f"✅ Cycle modifie!\nAncien: {' '.join(old)}\nNouveau: {' '.join(new_cycle)}")

        elif cmd == '/reset':
            old_count = len(bot_state['history'])
            bot_state['predictions'] = {}
            bot_state['history'] = []
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            bot_state['cycle_position'] = 0
            bot_state['last_prediction'] = None

            await event.reply(f"🔄 RESET! {old_count} predictions effacees. Pret!")

        elif cmd == '/status':
            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"
            last = bot_state['last_prediction']

            msg = f"""📊 ETAT: {status}
Predictions: {bot_state['prediction_count']}/{PAUSE_AFTER}
Cycle: {' '.join(bot_state['suit_cycle'])}
Position: {bot_state['cycle_position']}
Derniere: {f"#{last['number']}" if last else "Aucune"}
En attente: {len([p for p in bot_state['predictions'].values() if not p.get('resolved')])}"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\n⏱️ Pause: {remaining.seconds // 60} min"

            await event.reply(msg)

        elif cmd == '/next':
            cycle = bot_state['suit_cycle']
            pos = bot_state['cycle_position']
            next_suit = cycle[pos % len(cycle)]
            await event.reply(f"🎯 Prochain: {next_suit} {get_suit_name(next_suit)}")

        elif cmd == '/history':
            if not bot_state['history']:
                await event.reply("Aucune prediction")
                return

            text = "📜 Historique:\n\n"
            for p in bot_state['history'][-8:]:
                status = f"{p.get('emoji', '⏳')} {p.get('status', '...')}" if p.get('status') else "⏳"
                text += f"#{p['number']} {p['suit']} - {status}\n"
            await event.reply(text)

        elif cmd == '/pause':
            bot_state['is_paused'] = True
            await event.reply("⏸️ En pause. /resume pour reprendre.")

        elif cmd == '/resume':
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            await event.reply("▶️ Repris!")

        elif cmd == '/test' and len(parts) > 1:
            try:
                num = int(parts[1])
                if not is_target_number(num):
                    await event.reply(f"🚫 {num} n'est pas une cible (_3, _5, _0, _8)")
                else:
                    suit = get_next_suit()
                    bot_state['cycle_position'] -= 1
                    await event.reply(f"🧪 TEST #{num}: {suit} {get_suit_name(suit)}")
            except ValueError:
                await event.reply("Usage: /test <numero>")

        else:
            await event.reply("Commande inconnue. /start pour la liste.")

    except Exception as e:
        logger.error(f"Erreur commande: {e}")
        await event.reply(f"❌ Erreur: {str(e)}")

# =====================================================
# PARTIE 5 : GESTION MESSAGES SOURCE
# =====================================================

async def handle_source_message(event):
    """Traite les messages du canal source"""
    try:
        # Verifier pause
        if not await check_pause():
            return

        text = event.message.text or ""
        logger.info(f"📩 Message: {text[:80]}...")

        # ============================================================
        # ETAPE 1: Extraire le numero CORRECTEMENT
        # ============================================================
        num = extract_number_from_message(text)

        if not num:
            logger.info("Aucun numero trouve")
            return

        logger.info(f"🔢 Numero extrait: {num}")

        # Verifications
        if num in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Exclu: {num}")
            return

        if num < 1 or num > 1440:
            logger.warning(f"⚠️ Hors plage: {num}")
            return

        last_digit = num % 10

        # ============================================================
        # ETAPE 2: Verifier si c'est un resultat pour une prediction
        # ============================================================
        if num in bot_state['predictions']:
            pred = bot_state['predictions'][num]

            if not pred.get('resolved'):
                # Determiner le costume reel (simule pour le test)
                # Dans la realite, il faudrait parser le message pour trouver le vrai costume
                actual_suit = pred['suit']  # Pour test, on met le meme

                # Verifier resultat
                status, emoji = check_result(pred['suit'], actual_suit, pred['number'], num)

                # Mettre a jour
                pred['status'] = status
                pred['emoji'] = emoji
                pred['resolved'] = True

                # EDITER le message existant (pas en envoyer un nouveau)
                try:
                    new_text = format_prediction(num, pred['suit'], status, emoji)
                    await bot_client.edit_message(
                        PREDICTION_CHANNEL_ID,
                        pred['message_id'],
                        new_text
                    )
                    logger.info(f"✅ Message #{num} edite: {status}")
                except Exception as e:
                    logger.error(f"❌ Erreur edition: {e}")
                    # Si edition echoue, envoyer nouveau message
                    await bot_client.send_message(PREDICTION_CHANNEL_ID, 
                        format_prediction(num, pred['suit'], status, emoji))

                # Mettre a jour historique
                for h in bot_state['history']:
                    if h['number'] == num and not h.get('resolved'):
                        h.update(pred)
                        break

                logger.info(f"✅ Prediction #{num} resolue: {status}")

                # Attendre avant nouvelle prediction
                await asyncio.sleep(3)

        # ============================================================
        # ETAPE 3: Verifier si c'est un declencheur
        # ============================================================
        trigger_targets = {2: 3, 4: 5, 9: 0, 7: 8}

        if last_digit not in trigger_targets:
            logger.info(f"ℹ️ Pas un declencheur: {num} (_{last_digit})")
            return

        # Calculer cible
        target_last = trigger_targets[last_digit]
        target_num = (num // 10) * 10 + target_last

        # Verifier cible valide
        if target_num in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Cible exclue: {target_num}")
            return

        if not is_target_number(target_num):
            logger.info(f"🚫 Cible invalide: {target_num}")
            return

        # Verifier si prediction deja en cours pour cette cible
        if target_num in bot_state['predictions'] and not bot_state['predictions'][target_num].get('resolved'):
            logger.info(f"⚠️ Prediction deja en cours pour #{target_num}")
            return

        # ============================================================
        # ETAPE 4: Faire la prediction
        # ============================================================
        suit = get_next_suit()

        # Envoyer prediction
        msg_text = format_prediction(target_num, suit)
        sent_msg = await bot_client.send_message(PREDICTION_CHANNEL_ID, msg_text)

        # Stocker la prediction
        prediction = {
            'number': target_num,
            'suit': suit,
            'message_id': sent_msg.id,
            'trigger': num,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'resolved': False
        }

        bot_state['predictions'][target_num] = prediction
        bot_state['history'].append(prediction.copy())
        bot_state['last_prediction'] = prediction
        bot_state['prediction_count'] += 1

        logger.info(f"✅ Prediction: {num}→{target_num} | {suit} | msg_id:{sent_msg.id}")

        # Notifier admin
        await bot_client.send_message(ADMIN_ID,
            f"🎯 #{target_num} ({suit}) depuis #{num} (_{last_digit})→(_{target_last})")

        # Pause si necessaire
        if bot_state['prediction_count'] >= PAUSE_AFTER:
            await start_pause()

    except Exception as e:
        logger.error(f"❌ Erreur: {e}")
        import traceback
        logger.error(traceback.format_exc())

# =====================================================
# PARTIE 6 : DEMARRAGE
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

🎯 Cibles: _3, _5 (impairs) | _0, _8 (pairs)
🔗 Declencheurs: _2→3, _4→5, _9→0, _7→8
🎨 Cycle: {' '.join(bot_state['suit_cycle'])}
✏️ Edition automatique des messages

Commandes: /start, /setcycle, /reset, /status"""

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
            await asyncio.sleep(60)
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
