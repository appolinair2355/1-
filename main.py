#!/usr/bin/env python3
"""
Bot Telegram de Prediction - Deployable sur Render.com
Tout-en-un : bot + serveur web + commandes admin
Port: 10000
"""
import os
import sys
import asyncio
import logging
from datetime import datetime
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
    EXCLUDED_NUMBERS, PREDICTION_MAP, CYCLE_IMPAIR, CYCLE_PAIR
)

# Variables globales
bot_client = None
last_prediction = None

# =====================================================
# PARTIE 1 : SERVEUR WEB MINIMAL (pour Render.com)
# =====================================================

async def handle_health(request):
    """Endpoint de sante pour Render.com"""
    return web.Response(text="Bot is running!", status=200)

async def start_web_server():
    """Demarre le serveur web sur le port 10000"""
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
# PARTIE 2 : LOGIQUE DU BOT
# =====================================================

def get_prediction(number):
    """
    Retourne la prediction pour un numero donne
    Regle: 
    - Si numero impair recu -> predit avec cycle pair
    - Si numero pair recu -> predit avec cycle impair
    - Si numero exclu -> retourne None (pas de prediction)
    """
    if number in EXCLUDED_NUMBERS:
        return None
    return PREDICTION_MAP.get(number)

def format_prediction_message(number, suit, is_excluded=False):
    """Formate le message de prediction"""
    if is_excluded:
        return f"🚫 Numero {number} exclu - Aucune prediction"

    parite = "impair" if number % 2 == 1 else "pair"
    cycle_used = "pair" if number % 2 == 1 else "impair"

    return f"""🎯 PREDICTION

📥 Numero recu: {number} ({parite})
🎴 Costume predit: {suit}
📊 Cycle utilise: {cycle_used}
⏰ {datetime.now().strftime('%H:%M:%S')}"""

# =====================================================
# PARTIE 3 : COMMANDES ADMIN
# =====================================================

async def handle_admin_commands(event):
    """Gere les commandes admin"""
    global bot_client

    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    command = parts[0].lower()

    try:
        if command == '/start':
            await event.reply("""🤖 Bot de Prediction Actif

Commandes disponibles:
/test <numero> - Tester une prediction
/info - Voir les infos du bot
/stats - Statistiques
/restart - Redemarrer le bot""")

        elif command == '/test' and len(parts) > 1:
            try:
                num = int(parts[1])
                if num in EXCLUDED_NUMBERS:
                    await event.reply(f"🚫 {num} est un numero EXCLU")
                else:
                    suit = get_prediction(num)
                    if suit:
                        msg = format_prediction_message(num, suit)
                        await event.reply(msg)
                    else:
                        await event.reply(f"❌ Numero {num} non trouve dans la map")
            except ValueError:
                await event.reply("❌ Usage: /test <numero>")

        elif command == '/info':
            info_msg = f"""📊 Informations du Bot

📝 Configuration:
• Canal Source: {SOURCE_CHANNEL_ID}
• Canal Prediction: {PREDICTION_CHANNEL_ID}
• Admin ID: {ADMIN_ID}

🎲 Regles:
• Numeros valides: 1-1440 (sauf exclus)
• Numeros exclus: {len(EXCLUDED_NUMBERS)} numeros
• Logique: Impair recu → Cycle pair | Pair recu → Cycle impair

⏰ Derniere prediction: {last_prediction or 'Aucune'}"""
            await event.reply(info_msg)

        elif command == '/stats':
            await event.reply(f"""📈 Statistiques

• Numeros exclus: {sorted(EXCLUDED_NUMBERS)}
• Total numeros valides: {len(PREDICTION_MAP)}
• Cycle impair: {CYCLE_IMPAIR}
• Cycle pair: {CYCLE_PAIR}""")

        elif command == '/restart':
            await event.reply("🔄 Redemarrage demande...")
            logger.info("Redemarrage demande par admin")
            await event.reply("✅ Bot operationnel")

        elif command == '/excluded':
            excluded_list = sorted(EXCLUDED_NUMBERS)
            chunks = [excluded_list[i:i+10] for i in range(0, len(excluded_list), 10)]
            for chunk in chunks:
                await event.reply(f"🚫 Exclus: {chunk}")

        else:
            await event.reply("❓ Commande inconnue. Tapez /start pour la liste.")

    except Exception as e:
        logger.error(f"Erreur commande admin: {e}")
        await event.reply(f"❌ Erreur: {str(e)}")

# =====================================================
# PARTIE 4 : GESTION DES MESSAGES SOURCE
# =====================================================

async def handle_source_message(event):
    """Gere les messages du canal source"""
    global last_prediction

    try:
        # Extraire le numero du message
        text = event.message.text or ""
        logger.info(f"📩 Message recu du canal source: {text[:50]}...")

        # Chercher un numero dans le message
        import re
        numbers = re.findall(r'\b(\d+)\b', text)

        if not numbers:
            logger.info("Aucun numero trouve dans le message")
            return

        # Prendre le premier numero trouve
        number = int(numbers[0])
        logger.info(f"🔢 Numero extrait: {number}")

        # Verifier si c'est un numero exclu
        if number in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Numero {number} est exclu - pas de prediction")
            await bot_client.send_message(
                ADMIN_ID, 
                f"🚫 Numero exclu recu: {number}\nPas de prediction generee."
            )
            return

        # Verifier que le numero est dans la plage valide
        if number < 1 or number > 1440:
            logger.warning(f"⚠️ Numero {number} hors plage (1-1440)")
            return

        # Obtenir la prediction
        suit = get_prediction(number)
        if not suit:
            logger.error(f"❌ Pas de prediction trouvee pour {number}")
            return

        # Formater et envoyer la prediction
        message = format_prediction_message(number, suit)

        # Envoyer au canal de prediction
        await bot_client.send_message(PREDICTION_CHANNEL_ID, message)
        logger.info(f"✅ Prediction envoyee: {number} -> {suit}")

        # Mettre a jour la derniere prediction
        last_prediction = f"{number} -> {suit} a {datetime.now().strftime('%H:%M:%S')}"

        # Notifier l'admin
        await bot_client.send_message(
            ADMIN_ID,
            f"✅ Prediction faite:\n{message}"
        )

    except Exception as e:
        logger.error(f"❌ Erreur traitement message: {e}")
        import traceback
        logger.error(traceback.format_exc())

# =====================================================
# PARTIE 5 : DEMARRAGE DU BOT
# =====================================================

async def start_bot():
    """Demarre le bot Telegram"""
    global bot_client

    from telethon import TelegramClient, events
    from telethon.sessions import StringSession

    # Verifier la configuration
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("❌ Configuration Telegram incomplete!")
        return None

    # Creer le client
    session_string = os.getenv('TELEGRAM_SESSION', '')
    bot_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connecte a Telegram")

        # NE PAS appeler get_dialogs() pour les bots - RESTRICTION API
        # Les bots n'ont pas besoin de get_dialogs pour fonctionner

        # Configurer le handler pour le canal source
        @bot_client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def source_handler(event):
            await handle_source_message(event)

        # Configurer le handler pour les commandes admin (partout)
        @bot_client.on(events.NewMessage(pattern='/'))
        async def admin_handler(event):
            if event.sender_id == ADMIN_ID:
                await handle_admin_commands(event)

        # Test d'acces aux canaux (optionnel, juste pour les logs)
        try:
            await bot_client.get_entity(SOURCE_CHANNEL_ID)
            logger.info(f"✅ Canal source {SOURCE_CHANNEL_ID} accessible")
        except Exception as e:
            logger.warning(f"⚠️ Canal source inaccessible: {e}")

        try:
            await bot_client.get_entity(PREDICTION_CHANNEL_ID)
            logger.info(f"✅ Canal prediction {PREDICTION_CHANNEL_ID} accessible")
        except Exception as e:
            logger.warning(f"⚠️ Canal prediction inaccessible: {e}")

        # Message de demarrage a l'admin
        try:
            startup_msg = f"""🤖 Bot de Prediction Demarre!

📊 Configuration:
• Source: {SOURCE_CHANNEL_ID}
• Prediction: {PREDICTION_CHANNEL_ID}
• Port: {PORT}

🎲 Regles actives:
• Impair recu → Cycle pair
• Pair recu → Cycle impair
• {len(EXCLUDED_NUMBERS)} numeros exclus

Commandes: /start, /test <n>, /info, /stats, /excluded"""

            await bot_client.send_message(ADMIN_ID, startup_msg)
            logger.info("✅ Message de demarrage envoye a l'admin")
        except Exception as e:
            logger.error(f"❌ Impossible de contacter l'admin: {e}")

        return bot_client

    except Exception as e:
        logger.error(f"❌ Erreur demarrage bot: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

# =====================================================
# PARTIE 6 : FONCTION PRINCIPALE
# =====================================================

async def main():
    """Fonction principale"""
    logger.info("🚀 Demarrage du bot de prediction...")

    # Demarrer le serveur web (pour Render.com)
    web_runner = await start_web_server()

    # Demarrer le bot Telegram
    client = await start_bot()

    if not client:
        logger.error("❌ Impossible de demarrer le bot. Arret.")
        return

    logger.info("✅ Bot et serveur web sont operationnels")
    logger.info("⏳ En attente de messages...")

    # Garder le programme en vie
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("👋 Arret demande par l'utilisateur")
    finally:
        await client.disconnect()
        logger.info("🔌 Bot deconnecte")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Programme arrete")
    except Exception as e:
        logger.error(f"💥 Erreur fatale: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
