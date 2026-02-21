#!/usr/bin/env python3
"""
Bot Telegram de Prediction - Deployable sur Render.com
Prediction ciblee: _3, _5 (impairs) et _0, _8 (pairs)
Declencheurs: _2->3, _9->0, _4->5, _7->8
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
# CONFIGURATION MODIFIABLE
# =====================================================

# Cycle de costumes par defaut
DEFAULT_SUIT_CYCLE = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']

# Numéros cibles (impairs terminant par 3,5 et pairs terminant par 0,8)
def is_target_number(n):
    """Verifie si le numero est une cible valide"""
    if n in EXCLUDED_NUMBERS:
        return False
    last_digit = n % 10
    # Impairs: 3, 5 | Pairs: 0, 8
    return (n % 2 == 1 and last_digit in [3, 5]) or (n % 2 == 0 and last_digit in [0, 8])

def get_trigger_for_target(target):
    """Retourne le declencheur pour une cible"""
    last_digit = target % 10
    triggers = {3: 2, 5: 4, 0: 9, 8: 7}
    return triggers.get(last_digit)

def get_target_for_trigger(trigger):
    """Retourne la cible pour un declencheur"""
    targets = {2: 3, 4: 5, 9: 0, 7: 8}
    return targets.get(trigger)

# =====================================================
# VARIABLES GLOBALES
# =====================================================

bot_client = None

# Etat du bot
bot_state = {
    'suit_cycle': DEFAULT_SUIT_CYCLE.copy(),
    'cycle_position': 0,
    'last_prediction': None,      # Derniere prediction faite
    'pending_predictions': [],    # Predictions en attente de verification
    'history': [],                # Historique complet
    'is_paused': False,
    'pause_end': None,
    'prediction_count': 0,
    'last_trigger': None,         # Dernier declencheur vu
}

# Constantes
PAUSE_AFTER = 5
PAUSE_MINUTES = 3

# =====================================================
# PARTIE 1 : SERVEUR WEB
# =====================================================

async def handle_health(request):
    status = "PAUSED" if bot_state['is_paused'] else "RUNNING"
    return web.Response(text=f"Bot is {status}! Predictions: {bot_state['prediction_count']}", status=200)

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
# PARTIE 2 : GESTION DES PAUSES
# =====================================================

async def check_pause():
    """Verifie et gere la pause"""
    if bot_state['is_paused'] and bot_state['pause_end']:
        if datetime.now() >= bot_state['pause_end']:
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            logger.info("✅ Pause terminee")
            await bot_client.send_message(ADMIN_ID, "✅ Pause terminee! Reprise des predictions.")
            return True
    return not bot_state['is_paused']

async def start_pause():
    """Demarre une pause"""
    bot_state['is_paused'] = True
    bot_state['pause_end'] = datetime.now() + timedelta(minutes=PAUSE_MINUTES)
    logger.info(f"⏸️ Pause de {PAUSE_MINUTES} minutes")
    await bot_client.send_message(
        ADMIN_ID,
        f"⏸️ Pause de {PAUSE_MINUTES} minutes apres {PAUSE_AFTER} predictions.\n"
        f"Reprise a: {bot_state['pause_end'].strftime('%H:%M:%S')}"
    )

# =====================================================
# PARTIE 3 : LOGIQUE DE PREDICTION
# =====================================================

def get_next_suit():
    """Retourne le prochain costume du cycle"""
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

def check_result(pred_num, pred_suit, actual_num, actual_suit):
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

# =====================================================
# PARTIE 4 : COMMANDES ADMIN
# =====================================================

async def handle_admin_commands(event):
    """Gere toutes les commandes admin"""
    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    cmd = parts[0].lower()

    try:
        if cmd == '/start':
            await event.reply("""🤖 Bot de Prediction - Commandes:

/setcycle <emojis> - Modifier le cycle de costumes
/reset - Vider les stocks et recommencer
/status - Voir l'etat actuel
/history - Historique des predictions
/next - Voir le prochain costume
/pause - Mettre en pause
/resume - Reprendre
/test <numero> - Tester une prediction
/info - Informations""")

        elif cmd == '/setcycle':
            """Modifie le cycle de costumes"""
            if len(parts) < 2:
                await event.reply(
                    "❌ Usage: /setcycle <emojis>\n"
                    "Exemple: /setcycle ♦️ ♣️ ❤️ ♠️\n"
                    f"Cycle actuel: {' '.join(bot_state['suit_cycle'])}"
                )
                return

            # Recuperer les emojis (tous les arguments sauf la commande)
            new_cycle = parts[1:]

            # Valider qu'ils sont bien des emojis de cartes
            valid_suits = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid_suits]

            if invalid:
                await event.reply(
                    f"❌ Emojis invalides: {invalid}\n"
                    f"Emojis valides: {valid_suits}"
                )
                return

            # Sauvegarder l'ancien cycle
            old_cycle = bot_state['suit_cycle'].copy()

            # Mettre a jour
            bot_state['suit_cycle'] = new_cycle
            bot_state['cycle_position'] = 0  # Reset position

            logger.info(f"Cycle modifie: {old_cycle} -> {new_cycle}")
            await event.reply(
                f"✅ **Cycle modifie!**\n\n"
                f"Ancien: {' '.join(old_cycle)}\n"
                f"Nouveau: {' '.join(new_cycle)}\n"
                f"Position reset a 0"
            )

        elif cmd == '/reset':
            """Reset complet"""
            old_count = len(bot_state['history'])

            bot_state['last_prediction'] = None
            bot_state['pending_predictions'] = []
            bot_state['history'] = []
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['prediction_count'] = 0
            bot_state['cycle_position'] = 0
            bot_state['last_trigger'] = None

            logger.info("RESET execute")
            await event.reply(
                f"🔄 **RESET EXECUTE**\n\n"
                f"✅ {old_count} predictions effacees\n"
                f"✅ Cycle reset a position 0\n"
                f"✅ Stocks vides\n\n"
                f"🚀 Pret pour de nouvelles predictions!"
            )

        elif cmd == '/status':
            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"
            last = bot_state['last_prediction']

            msg = f"""📊 **ETAT ACTUEL**

Statut: {status}
Predictions: {bot_state['prediction_count']}/{PAUSE_AFTER}
Cycle position: {bot_state['cycle_position']}/{len(bot_state['suit_cycle'])}
Cycle: {' '.join(bot_state['suit_cycle'])}

Derniere prediction: {f"#{last['number']}" if last else "Aucune"}
Total historique: {len(bot_state['history'])}"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\n⏱️ Pause: {remaining.seconds // 60} min restantes"

            await event.reply(msg)

        elif cmd == '/next':
            """Voir le prochain costume"""
            cycle = bot_state['suit_cycle']
            pos = bot_state['cycle_position']
            next_suit = cycle[pos % len(cycle)]
            await event.reply(
                f"🎯 **Prochain costume:** {next_suit} {get_suit_name(next_suit)}\n"
                f"Position: {pos} (modulo {len(cycle)})"
            )

        elif cmd == '/history':
            if not bot_state['history']:
                await event.reply("📊 Aucune prediction")
                return

            text = "📜 **Dernieres predictions:**\n\n"
            for p in bot_state['history'][-8:]:
                status = f"{p.get('emoji', '⏳')} {p.get('status', '...')}" if p.get('status') else "⏳ En cours"
                text += f"🎰 #{p['number']} {p['suit']} - {status}\n"
            await event.reply(text)

        elif cmd == '/pause':
            bot_state['is_paused'] = True
            await event.reply("⏸️ Predictions en pause. /resume pour reprendre.")

        elif cmd == '/resume':
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            await event.reply("▶️ Predictions reprises!")

        elif cmd == '/test' and len(parts) > 1:
            try:
                num = int(parts[1])
                if not is_target_number(num):
                    await event.reply(f"🚫 {num} n'est pas un numero cible (_3, _5, _0, _8)")
                else:
                    suit = get_next_suit()
                    bot_state['cycle_position'] -= 1  # Annuler l'avance pour le test
                    await event.reply(f"🧪 **TEST** #{num}\n{suit} {get_suit_name(suit)}\n⚠️ Test uniquement")
            except ValueError:
                await event.reply("❌ Usage: /test <numero>")

        elif cmd == '/info':
            await event.reply(
                f"""📊 **Informations**

🎯 Cibles:
• Impairs: _3, _5
• Pairs: _0, _8

🔗 Declencheurs:
• _2 → _3
• _4 → _5
• _9 → _0
• _7 → _8

🚫 Exclus: {len(EXCLUDED_NUMBERS)} numeros

🎨 Cycle actuel: {' '.join(bot_state['suit_cycle'])}
📍 Position: {bot_state['cycle_position']}"""
            )

        else:
            await event.reply("❓ Commande inconnue. /start pour la liste.")

    except Exception as e:
        logger.error(f"Erreur commande: {e}")
        await event.reply(f"❌ Erreur: {str(e)}")

# =====================================================
# PARTIE 5 : GESTION DES MESSAGES SOURCE
# =====================================================

async def process_pending_predictions(actual_number, actual_suit):
    """Verifie et met a jour les predictions en attente"""
    updated = []

    for pred in bot_state['pending_predictions']:
        if pred.get('resolved'):
            continue

        # Verifier si ce resultat correspond a cette prediction
        status, emoji = check_result(
            pred['number'], pred['suit'],
            actual_number, actual_suit
        )

        # Mettre a jour
        pred['status'] = status
        pred['emoji'] = emoji
        pred['resolved'] = True
        pred['actual_number'] = actual_number
        pred['actual_suit'] = actual_suit

        # Envoyer la mise a jour
        msg = format_prediction(pred['number'], pred['suit'], status, emoji)
        await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)

        updated.append(pred)
        logger.info(f"✅ Prediction #{pred['number']} mise a jour: {status}")

    # Retirer les predictions resolues de la liste d'attente
    bot_state['pending_predictions'] = [
        p for p in bot_state['pending_predictions'] if not p.get('resolved')
    ]

    return len(updated)

async def handle_source_message(event):
    """Traite les messages du canal source"""
    try:
        # Verifier pause
        if not await check_pause():
            return

        # Extraire numero
        text = event.message.text or ""
        numbers = re.findall(r'\b(\d+)\b', text)

        if not numbers:
            return

        num = int(numbers[0])
        logger.info(f"📩 Numero recu: {num}")

        # Verifier exclusion
        if num in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Numero exclu: {num}")
            return

        # Verifier plage
        if num < 1 or num > 1440:
            return

        last_digit = num % 10

        # ============================================================
        # ETAPE 1: Verifier si c'est un resultat pour une prediction
        # ============================================================
        if bot_state['pending_predictions']:
            # Simuler le costume de ce numero
            actual_suit = bot_state['suit_cycle'][num % len(bot_state['suit_cycle'])]
            updated = await process_pending_predictions(num, actual_suit)
            if updated > 0:
                await asyncio.sleep(2)  # Attendre avant nouvelle prediction

        # ============================================================
        # ETAPE 2: Verifier si c'est un declencheur
        # ============================================================
        trigger_targets = {2: 3, 4: 5, 9: 0, 7: 8}

        if last_digit not in trigger_targets:
            logger.info(f"ℹ️ {num} n'est pas un declencheur (last digit: {last_digit})")
            return

        # C'est un declencheur!
        target_last_digit = trigger_targets[last_digit]

        # Construire le numero cible
        # Ex: declencheur 132 (termine par 2) -> cible 133 (termine par 3)
        target_number = (num // 10) * 10 + target_last_digit

        # Verifier que la cible est valide
        if target_number in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Cible {target_number} est exclue")
            return

        if not is_target_number(target_number):
            logger.info(f"🚫 Cible {target_number} n'est pas un numero cible")
            return

        # ============================================================
        # ETAPE 3: Faire la prediction
        # ============================================================
        suit = get_next_suit()

        prediction = {
            'number': target_number,
            'suit': suit,
            'trigger': num,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'resolved': False
        }

        bot_state['last_prediction'] = prediction
        bot_state['pending_predictions'].append(prediction)
        bot_state['history'].append(prediction.copy())
        bot_state['prediction_count'] += 1
        bot_state['last_trigger'] = num

        # Envoyer
        msg = format_prediction(target_number, suit)
        await bot_client.send_message(PREDICTION_CHANNEL_ID, msg)

        logger.info(f"✅ Prediction: {num} (_{last_digit}) → {target_number} (_{target_last_digit}) | {suit}")

        # Notifier admin
        await bot_client.send_message(
            ADMIN_ID,
            f"🎯 Prediction lancee:\n"
            f"Declencheur: {num} (_{last_digit})\n"
            f"Cible: {target_number} (_{target_last_digit})\n"
            f"Costume: {suit} {get_suit_name(suit)}"
        )

        # Verifier pause
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
    """Demarre le bot"""
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

        # Message de demarrage
        startup = f"""🤖 **Bot de Prediction Demarre!**

🎯 **Cibles:**
• Impairs: _3, _5
• Pairs: _0, _8

🔗 **Declencheurs:**
• _2 → _3 | _4 → _5
• _9 → _0 | _7 → _8

🎨 **Cycle:** {' '.join(bot_state['suit_cycle'])}
⏸️ **Pause:** apres {PAUSE_AFTER} predictions ({PAUSE_MINUTES} min)

Commandes: /start, /setcycle, /reset, /status"""

        await bot_client.send_message(ADMIN_ID, startup)
        return bot_client

    except Exception as e:
        logger.error(f"Erreur demarrage: {e}")
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
