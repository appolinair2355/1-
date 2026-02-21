#!/usr/bin/env python3
"""
Bot Telegram de Prédiction - Déployable sur Render.com
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
admin_client = None
last_prediction = None  # Pour suivre la dernière prédiction faite

# =====================================================
# PARTIE 1 : SERVEUR WEB MINIMAL (pour Render.com)
# =====================================================

async def handle_health(request):
    """Endpoint de santé pour Render.com"""
    return web.Response(text="Bot is running!", status=200)

async def start_web_server():
    """Démarre le serveur web sur le port 10000"""
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Serveur web démarré sur le port {PORT}")
    return runner

# =====================================================
# PARTIE 2 : LOGIQUE DU BOT
# =====================================================

def get_prediction(number):
    """
    Retourne la prédiction pour un numéro donné
    Règle: 
    - Si numéro impair reçu -> prédit avec cycle pair
    - Si numéro pair reçu -> prédit avec cycle impair
    - Si numéro exclu -> retourne None (pas de prédiction)
    """
    if number in EXCLUDED_NUMBERS:
        return None
    return PREDICTION_MAP.get(number)

def format_prediction_message(number, suit, is_excluded=False):
    """Formate le message de prédiction"""
    if is_excluded:
        return f"🚫 Numéro {number} exclu - Aucune prédiction"

    parite = "impair" if number % 2 == 1 else "pair"
    cycle_used = "pair" if number % 2 == 1 else "impair"

    return f"""🎯 PRÉDICTION

📥 Numéro reçu: {number} ({parite})
🎴 Costume prédit: {suit}
📊 Cycle utilisé: {cycle_used}
⏰ {datetime.now().strftime('%H:%M:%S')}"""

# =====================================================
# PARTIE 3 : COMMANDES ADMIN
# =====================================================

async def handle_admin_commands(event):
    """Gère les commandes admin"""
    global bot_client

    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    command = parts[0].lower()

    try:
        if command == '/start':
            await event.reply("""🤖 Bot de Prédiction Actif

Commandes disponibles:
/test <numero> - Tester une prédiction
/info - Voir les infos du bot
/stats - Statistiques
/restart - Redémarrer le bot""")

        elif command == '/test' and len(parts) > 1:
            try:
                num = int(parts[1])
                if num in EXCLUDED_NUMBERS:
                    await event.reply(f"🚫 {num} est un numéro EXCLU")
                else:
                    suit = get_prediction(num)
                    if suit:
                        msg = format_prediction_message(num, suit)
                        await event.reply(msg)
                    else:
                        await event.reply(f"❌ Numéro {num} non trouvé dans la map")
            except ValueError:
                await event.reply("❌ Usage: /test <numero>")

        elif command == '/info':
            info_msg = f"""📊 Informations du Bot

📝 Configuration:
• Canal Source: {SOURCE_CHANNEL_ID}
• Canal Prédiction: {PREDICTION_CHANNEL_ID}
• Admin ID: {ADMIN_ID}

🎲 Règles:
• Numéros valides: 1-1440 (sauf exclus)
• Numéros exclus: {len(EXCLUDED_NUMBERS)} numéros
• Logique: Impair reçu → Cycle pair | Pair reçu → Cycle impair

⏰ Dernière prédiction: {last_prediction or 'Aucune'}"""
            await event.reply(info_msg)

        elif command == '/stats':
            await event.reply(f"""📈 Statistiques

• Numéros exclus: {sorted(EXCLUDED_NUMBERS)}
• Total numéros valides: {len(PREDICTION_MAP)}
• Cycle impair: {CYCLE_IMPAIR}
• Cycle pair: {CYCLE_PAIR}""")

        elif command == '/restart':
            await event.reply("🔄 Redémarrage demandé...")
            logger.info("Redémarrage demandé par admin")
            # On ne redémarre pas vraiment, juste un message
            await event.reply("✅ Bot opérationnel")

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
    """Gère les messages du canal source"""
    global last_prediction

    try:
        # Extraire le numéro du message
        text = event.message.text or ""
        logger.info(f"📩 Message reçu du canal source: {text[:50]}...")

        # Chercher un numéro dans le message
        import re
        numbers = re.findall(r'\b(\d+)\b', text)

        if not numbers:
            logger.info("Aucun numéro trouvé dans le message")
            return

        # Prendre le premier numéro trouvé
        number = int(numbers[0])
        logger.info(f"🔢 Numéro extrait: {number}")

        # Vérifier si c'est un numéro exclu
        if number in EXCLUDED_NUMBERS:
            logger.info(f"🚫 Numéro {number} est exclu - pas de prédiction")
            await bot_client.send_message(
                ADMIN_ID, 
                f"🚫 Numéro exclu reçu: {number}\nPas de prédiction générée."
            )
            return

        # Vérifier que le numéro est dans la plage valide
        if number < 1 or number > 1440:
            logger.warning(f"⚠️ Numéro {number} hors plage (1-1440)")
            return

        # Obtenir la prédiction
        suit = get_prediction(number)
        if not suit:
            logger.error(f"❌ Pas de prédiction trouvée pour {number}")
            return

        # Formater et envoyer la prédiction
        message = format_prediction_message(number, suit)

        # Envoyer au canal de prédiction
        await bot_client.send_message(PREDICTION_CHANNEL_ID, message)
        logger.info(f"✅ Prédiction envoyée: {number} -> {suit}")

        # Mettre à jour la dernière prédiction
        last_prediction = f"{number} -> {suit} à {datetime.now().strftime('%H:%M:%S')}"

        # Notifier l'admin
        await bot_client.send_message(
            ADMIN_ID,
            f"✅ Prédiction faite:\n{message}"
        )

    except Exception as e:
        logger.error(f"❌ Erreur traitement message: {e}")
        import traceback
        logger.error(traceback.format_exc())

# =====================================================
# PARTIE 5 : DÉMARRAGE DU BOT
# =====================================================

async def start_bot():
    """Démarre le bot Telegram"""
    global bot_client, admin_client

    from telethon import TelegramClient, events
    from telethon.sessions import StringSession

    # Vérifier la configuration
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("❌ Configuration Telegram incomplète!")
        return None

    # Créer le client
    session_string = os.getenv('TELEGRAM_SESSION', '')
    bot_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connecté à Telegram")

        # Récupérer les dialogs pour avoir accès aux entités
        if not session_string:
            await bot_client.get_dialogs()
            logger.info("✅ Dialogs chargés")

        # Configurer le handler pour le canal source
        @bot_client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def source_handler(event):
            await handle_source_message(event)

        # Configurer le handler pour les commandes admin (partout)
        @bot_client.on(events.NewMessage(pattern='/'))
        async def admin_handler(event):
            if event.sender_id == ADMIN_ID:
                await handle_admin_commands(event)

        # Test d'accès aux canaux
        try:
            await bot_client.get_entity(SOURCE_CHANNEL_ID)
            logger.info(f"✅ Canal source {SOURCE_CHANNEL_ID} accessible")
        except Exception as e:
            logger.warning(f"⚠️ Canal source inaccessible: {e}")

        try:
            await bot_client.get_entity(PREDICTION_CHANNEL_ID)
            logger.info(f"✅ Canal prédiction {PREDICTION_CHANNEL_ID} accessible")
        except Exception as e:
            logger.warning(f"⚠️ Canal prédiction inaccessible: {e}")

        # Message de démarrage à l'admin
        try:
            startup_msg = f"""🤖 Bot de Prédiction Démarré!

📊 Configuration:
• Source: {SOURCE_CHANNEL_ID}
• Prédiction: {PREDICTION_CHANNEL_ID}
• Port: {PORT}

🎲 Règles actives:
• Impair reçu → Cycle pair
• Pair reçu → Cycle impair
• {len(EXCLUDED_NUMBERS)} numéros exclus

Commandes: /start, /test <n>, /info, /stats, /excluded"""

            await bot_client.send_message(ADMIN_ID, startup_msg)
            logger.info("✅ Message de démarrage envoyé à l'admin")
        except Exception as e:
            logger.error(f"❌ Impossible de contacter l'admin: {e}")

        return bot_client

    except Exception as e:
        logger.error(f"❌ Erreur démarrage bot: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

# =====================================================
# PARTIE 6 : FONCTION PRINCIPALE
# =====================================================

async def main():
    """Fonction principale"""
    logger.info("🚀 Démarrage du bot de prédiction...")

    # Démarrer le serveur web (pour Render.com)
    web_runner = await start_web_server()

    # Démarrer le bot Telegram
    client = await start_bot()

    if not client:
        logger.error("❌ Impossible de démarrer le bot. Arrêt.")
        return

    logger.info("✅ Bot et serveur web sont opérationnels")
    logger.info("⏳ En attente de messages...")

    # Garder le programme en vie
    try:
        while True:
            await asyncio.sleep(3600)  # Attendre 1 heure
    except KeyboardInterrupt:
        logger.info("👋 Arrêt demandé par l'utilisateur")
    finally:
        await client.disconnect()
        logger.info("🔌 Bot déconnecté")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Programme arrêté")
    except Exception as e:
        logger.error(f"💥 Erreur fatale: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
