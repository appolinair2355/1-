#!/usr/bin/env python3
"""
Bot Telegram de Prediction - CORRIGÉ v2
Logique: Cibles _3,_5 (impairs) et _0,_8 (pairs) - FINS DE NUMÉRO
Déclencheurs: _2,_4,_9,_7 - FINS DE NUMÉRO
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

# Configuration des FINS DE NUMÉRO (derniers chiffres)
TARGET_CONFIG = {
    'impairs': [3, 5],      # Fins de numéro impairs à prédire
    'pairs': [0, 8],        # Fins de numéro pairs à prédire
    'triggers': {2: 3, 4: 5, 9: 0, 7: 8}  # Déclencheur: Cible (fins de numéro)
}

# Cycle des costumes
SUIT_CYCLE = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']
SUIT_DISPLAY = {'♦️': '♦️ Carreau', '❤️': '❤️ Coeur', '♣️': '♣️ Trefle', '♠️': '♠️ Pique'}

PAUSE_AFTER = 5
PAUSE_MINUTES = [3, 4, 5]
PREDICTION_TIMEOUT = 10

# ============================================================
# VARIABLES GLOBALES
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
    """Extrait le numero de jeu du message"""
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
    """Retourne le dernier chiffre d'un numéro"""
    return number % 10

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
    """Verifie si le message est en cours d'edition"""
    return message_text.strip().startswith('⏰')

def is_message_finalized(message_text):
    """Verifie si le message est finalise"""
    return '✅' in message_text or '🔰' in message_text

def is_target_last_digit(last_digit, is_odd):
    """Verifie si le dernier chiffre est une cible"""
    if is_odd:
        return last_digit in TARGET_CONFIG['impairs']
    else:
        return last_digit in TARGET_CONFIG['pairs']

def get_trigger_target(trigger_num):
    """Calcule la cible a partir du declencheur"""
    last_digit = get_last_digit(trigger_num)
    target_last = TARGET_CONFIG['triggers'].get(last_digit)

    if target_last is None:
        return None

    # Calculer le numéro cible en remplaçant le dernier chiffre
    target = (trigger_num // 10) * 10 + target_last

    if target == 0:
        target = trigger_num + 1
        if not is_target_last_digit(get_last_digit(target), target % 2 == 1):
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
    last_digit = get_last_digit(number)
    if status:
        return f"""🎰 **PRÉDICTION #{number}** (fin: _{last_digit})
🎯 Couleur: {SUIT_DISPLAY.get(suit, suit)}
📊 Statut: {emoji} {status}"""
    return f"""🎰 **PRÉDICTION #{number}** (fin: _{last_digit})
🎯 Couleur: {SUIT_DISPLAY.get(suit, suit)}
⏳ Statut: EN ATTENTE DU RÉSULTAT..."""

def reset_verification_state():
    """Réinitialise l'état de vérification"""
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

async def check_prediction_timeout(current_game):
    """Vérifie si la prédiction en cours a expiré"""
    if verification_state['predicted_number'] is None:
        return False
    
    predicted_num = verification_state['predicted_number']
    
    if current_game > predicted_num + PREDICTION_TIMEOUT:
        logger.warning(f"⏰ PRÉDICTION #{predicted_num} EXPIRÉE (actuel: #{current_game})")
        
        try:
            predicted_suit = verification_state['predicted_suit']
            updated_text = format_prediction(
                predicted_num, 
                predicted_suit, 
                "⏹️ EXPIRÉ (délai dépassé)", 
                "⏹️"
            )
            
            await bot_client.edit_message(
                verification_state['channel_id'],
                verification_state['message_id'],
                updated_text
            )
            
            await bot_client.send_message(
                ADMIN_ID, 
                f"⚠️ Prédiction #{predicted_num} expirée (délai dépassé). Système libéré."
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
    """Envoie une prediction au canal"""
    if verification_state['predicted_number'] is not None:
        logger.error(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en cours!")
        return False

    try:
        prediction_text = format_prediction(target_game, predicted_suit)
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

        logger.info(f"🚀 PRÉDICTION #{target_game} (fin _{get_last_digit(target_game)}) LANCÉE")
        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi prédiction: {e}")
        return False

async def update_prediction_status(status):
    """Met a jour le statut de la prediction"""
    global stats_bilan

    if verification_state['predicted_number'] is None:
        logger.error("❌ Aucune prédiction à mettre à jour")
        return False

    try:
        predicted_num = verification_state['predicted_number']
        predicted_suit = verification_state['predicted_suit']

        if status == "❌":
            status_text = "❌ PERDU"
        elif status == "⏹️":
            status_text = "⏹️ EXPIRÉ"
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

        logger.info(f"🔓 SYSTÈME LIBÉRÉ")
        reset_verification_state()
        return True

    except Exception as e:
        logger.error(f"❌ Erreur mise à jour statut: {e}")
        return False

async def process_verification_step(game_number, message_text):
    """Traite UNE étape de vérification"""
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
    logger.info(f"🔍 Vérification #{game_number}: {suits}, attendu {predicted_suit}")

    if predicted_suit in suits:
        status = f"✅{current_check}️⃣"
        logger.info(f"🎉 GAGNÉ au check {current_check}")
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
    """Verifie et lance une prediction basée sur la FIN DE NUMÉRO"""
    
    await check_prediction_timeout(game_number)
    
    if verification_state['predicted_number'] is not None:
        logger.warning(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en attente.")
        return

    if not await check_pause():
        logger.info("⏸️ En pause")
        return

    # Vérifier la FIN DE NUMÉRO (dernier chiffre)
    last_digit = get_last_digit(game_number)
    
    # Vérifier si c'est un déclencheur (fins de numéro définies dans triggers)
    if last_digit not in TARGET_CONFIG['triggers']:
        logger.info(f"ℹ️ #{game_number} (fin _{last_digit}) pas un déclencheur")
        return

    # Calculer la cible (changer le dernier chiffre)
    target_num = get_trigger_target(game_number)
    if not target_num:
        logger.warning(f"⚠️ Pas de cible pour #{game_number} (fin _{last_digit})")
        return

    if target_num in EXCLUDED_NUMBERS:
        logger.info(f"🚫 Cible #{target_num} exclue")
        return

    # Vérifier que la cible a bien une fin de numéro valide
    target_last = get_last_digit(target_num)
    is_target_odd = target_num % 2 == 1
    
    if not is_target_last_digit(target_last, is_target_odd):
        logger.info(f"🚫 Cible #{target_num} (fin _{target_last}) invalide")
        return

    suit = get_next_suit()
    success = await send_prediction(target_num, suit, game_number)

    if success and bot_state['predictions_count'] >= PAUSE_AFTER:
        await start_pause()

# ============================================================
# TRAITEMENT DES MESSAGES SOURCE
# ============================================================

async def process_source_message(event, is_edit=False):
    """Traite les messages du canal source"""
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
        logger.info(f"📩 {log_status} {log_type}: #{game_number} (fin _{last_digit})")

        bot_state['last_source_number'] = game_number

        # Vérification prédiction en cours
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

        # Lancer nouvelle prédiction
        await check_and_launch_prediction(game_number)

    except Exception as e:
        logger.error(f"❌ Erreur traitement message: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ============================================================
# COMMANDES ADMIN (AVEC NOUVELLES COMMANDES)
# ============================================================

async def handle_admin_commands(event):
    if event.sender_id != ADMIN_ID:
        return

    text = event.message.text.strip()
    parts = text.split()
    cmd = parts[0].lower()

    try:
        if cmd == '/start':
            await event.respond("""🤖 Commandes disponibles:

**Configuration des fins de numéro:**
/settargets <impairs> <pairs> - Modifier fins à prédire (ex: /settargets 3,5 0,8)
/settriggers <liste> - Modifier fins déclencheurs (ex: /settriggers 2,4,9,7)
/setmapping <map> - Modifier mapping déclencheur→cible (ex: /setmapping 2:3,4:5,9:0,7:8)

**Configuration du cycle:**
/setcycle <emojis> - Modifier cycle costumes (ex: /setcycle ♦️ ♣️ ❤️ ♠️)
/addsuit <emoji> - Ajouter un costume au cycle
/removesuit <position> - Retirer un costume du cycle

**Gestion:**
/reset - Reset complet
/forceunlock - Débloquer immédiatement
/pause /resume - Pause/Reprendre
/info - Voir état complet
/bilan - Statistiques
/next - Prochain costume
/timeout <n> - Changer timeout""")

        # ============================================================
        # COMMANDES DE CONFIGURATION DES FINS DE NUMÉRO
        # ============================================================

        elif cmd == '/settargets':
            """Modifie les fins de numéro à prédire (impairs et pairs)"""
            if len(parts) < 3:
                await event.respond(
                    f"📋 **Usage:** `/settargets <impairs> <pairs>`\n\n"
                    f"**Exemple:** `/settargets 3,5 0,8`\n"
                    f"**Actuel:**\n"
                    f"• Impairs: {TARGET_CONFIG['impairs']}\n"
                    f"• Pairs: {TARGET_CONFIG['pairs']}"
                )
                return

            try:
                impairs = [int(x.strip()) for x in parts[1].split(',') if x.strip()]
                pairs = [int(x.strip()) for x in parts[2].split(',') if x.strip()]
                
                # Validation
                for d in impairs:
                    if d < 0 or d > 9 or d % 2 == 0:
                        await event.respond(f"❌ {d} n'est pas un chiffre impair valide (1,3,5,7,9)")
                        return
                
                for d in pairs:
                    if d < 0 or d > 9 or d % 2 == 1:
                        await event.respond(f"❌ {d} n'est pas un chiffre pair valide (0,2,4,6,8)")
                        return

                TARGET_CONFIG['impairs'] = impairs
                TARGET_CONFIG['pairs'] = pairs
                
                await event.respond(
                    f"✅ **Fins de numéro à prédire modifiées!**\n\n"
                    f"🎯 **Impairs:** {impairs}\n"
                    f"🎯 **Pairs:** {pairs}\n\n"
                    f"Les numéros se terminant par ces chiffres seront prédits."
                )
                logger.info(f"Fins cibles modifiées - Impairs: {impairs}, Pairs: {pairs}")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/settriggers':
            """Modifie les fins de numéro déclencheurs"""
            if len(parts) < 2:
                current_triggers = list(TARGET_CONFIG['triggers'].keys())
                await event.respond(
                    f"📋 **Usage:** `/settriggers <liste>`\n\n"
                    f"**Exemple:** `/settriggers 2,4,9,7`\n"
                    f"**Actuel:** {current_triggers}\n\n"
                    f"⚠️ Cela remplace tous les déclencheurs existants!"
                )
                return

            try:
                new_triggers = [int(x.strip()) for x in parts[1].split(',') if x.strip()]
                
                # Validation
                for d in new_triggers:
                    if d < 0 or d > 9:
                        await event.respond(f"❌ {d} n'est pas un chiffre valide (0-9)")
                        return

                # Garder les mappings existants pour les déclencheurs communs
                old_mapping = TARGET_CONFIG['triggers'].copy()
                new_mapping = {}
                
                for trigger in new_triggers:
                    if trigger in old_mapping:
                        new_mapping[trigger] = old_mapping[trigger]
                    else:
                        # Par défaut: déclencheur + 1 (avec gestion du cycle 9→0)
                        default_target = (trigger + 1) % 10
                        new_mapping[trigger] = default_target
                
                TARGET_CONFIG['triggers'] = new_mapping
                
                trigger_list = list(new_mapping.keys())
                await event.respond(
                    f"✅ **Déclencheurs modifiés!**\n\n"
                    f"🔗 **Fins déclencheurs:** {trigger_list}\n"
                    f"🎯 **Mapping actuel:** {new_mapping}\n\n"
                    f"💡 Utilisez `/setmapping` pour changer les cibles associées."
                )
                logger.info(f"Déclencheurs modifiés: {trigger_list}")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        elif cmd == '/setmapping':
            """Modifie le mapping déclencheur → cible"""
            if len(parts) < 2:
                await event.respond(
                    f"📋 **Usage:** `/setmapping <map>`\n\n"
                    f"**Format:** `déclencheur:cible,déclencheur:cible,...`\n"
                    f"**Exemple:** `/setmapping 2:3,4:5,9:0,7:8`\n"
                    f"**Actuel:** {TARGET_CONFIG['triggers']}\n\n"
                    f"Signification: quand fin de numéro=X, prédire fin de numéro=Y"
                )
                return

            try:
                new_mapping = {}
                pairs = parts[1].split(',')
                
                for pair in pairs:
                    if ':' not in pair:
                        await event.respond(f"❌ Format invalide pour '{pair}'. Utilisez déclencheur:cible")
                        return
                    
                    t, c = pair.split(':')
                    trigger = int(t.strip())
                    cible = int(c.strip())
                    
                    if not (0 <= trigger <= 9 and 0 <= cible <= 9):
                        await event.respond(f"❌ Les chiffres doivent être entre 0 et 9")
                        return
                    
                    new_mapping[trigger] = cible
                
                TARGET_CONFIG['triggers'] = new_mapping
                
                # Créer un affichage lisible
                mapping_text = "\n".join([f"  • _{k} → _{v}" for k, v in sorted(new_mapping.items())])
                
                await event.respond(
                    f"✅ **Mapping modifié!**\n\n"
                    f"**Correspondances:**\n{mapping_text}\n\n"
                    f"Quand le canal envoie un numéro finissant par X, le bot prédit un numéro finissant par Y."
                )
                logger.info(f"Mapping modifié: {new_mapping}")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        # ============================================================
        # COMMANDES DE CONFIGURATION DU CYCLE
        # ============================================================

        elif cmd == '/setcycle':
            """Remplace complètement le cycle des costumes"""
            if len(parts) < 2:
                await event.respond(
                    f"📋 **Usage:** `/setcycle <emojis...>`\n\n"
                    f"**Exemple:** `/setcycle ♦️ ♣️ ❤️ ♠️`\n"
                    f"**Actuel:** {' '.join(bot_state['cycle'])}\n"
                    f"**Position:** {bot_state['cycle_pos']}/{len(bot_state['cycle'])}\n\n"
                    f"Costumes valides: ♦️ ♣️ ❤️ ♠️"
                )
                return

            new_cycle = parts[1:]
            valid = ['♦️', '❤️', '♣️', '♠️']
            invalid = [s for s in new_cycle if s not in valid]

            if invalid:
                await event.respond(f"❌ Costumes invalides: {invalid}\nValides: {valid}")
                return

            bot_state['cycle'] = new_cycle
            bot_state['cycle_pos'] = 0
            await event.respond(
                f"✅ **Cycle modifié!**\n\n"
                f"🎨 **Nouveau cycle:** {' '.join(new_cycle)}\n"
                f"📍 **Position reset:** 0/{len(new_cycle)}\n"
                f"🎯 **Prochain:** {new_cycle[0] if new_cycle else 'N/A'}"
            )
            logger.info(f"Cycle modifié: {new_cycle}")

        elif cmd == '/addsuit':
            """Ajoute un costume à la fin du cycle"""
            if len(parts) < 2:
                await event.respond(
                    f"📋 **Usage:** `/addsuit <emoji>`\n\n"
                    f"**Exemple:** `/addsuit ♦️`\n"
                    f"**Cycle actuel:** {' '.join(bot_state['cycle'])}"
                )
                return

            suit = parts[1]
            valid = ['♦️', '❤️', '♣️', '♠️']
            
            if suit not in valid:
                await event.respond(f"❌ Costume invalide. Valides: {valid}")
                return
            
            bot_state['cycle'].append(suit)
            await event.respond(
                f"✅ **Costume ajouté!**\n\n"
                f"🎨 **Cycle:** {' '.join(bot_state['cycle'])}\n"
                f"📍 **Position:** {bot_state['cycle_pos']}/{len(bot_state['cycle'])}"
            )

        elif cmd == '/removesuit':
            """Retire un costume du cycle par position"""
            if len(parts) < 2:
                cycle_str = " ".join([f"{i}:{s}" for i, s in enumerate(bot_state['cycle'])])
                await event.respond(
                    f"📋 **Usage:** `/removesuit <position>`\n\n"
                    f"**Exemple:** `/removesuit 0` (retire le premier)\n"
                    f"**Cycle actuel:** {cycle_str}\n"
                    f"**Positions:** 0 à {len(bot_state['cycle'])-1}"
                )
                return

            try:
                pos = int(parts[1])
                if pos < 0 or pos >= len(bot_state['cycle']):
                    await event.respond(f"❌ Position invalide. Utilisez 0-{len(bot_state['cycle'])-1}")
                    return
                
                removed = bot_state['cycle'].pop(pos)
                
                # Ajuster la position si nécessaire
                if bot_state['cycle_pos'] >= len(bot_state['cycle']):
                    bot_state['cycle_pos'] = 0
                
                await event.respond(
                    f"✅ **Costume retiré!**\n\n"
                    f"🗑️ Retiré: {removed} (position {pos})\n"
                    f"🎨 **Nouveau cycle:** {' '.join(bot_state['cycle'])}\n"
                    f"📍 **Position:** {bot_state['cycle_pos']}/{len(bot_state['cycle'])}"
                )
                logger.info(f"Costume {removed} retiré du cycle")

            except Exception as e:
                await event.respond(f"❌ Erreur: {e}")

        # ============================================================
        # COMMANDES DE GESTION
        # ============================================================

        elif cmd == '/reset':
            """Reset complet"""
            old_pred = verification_state['predicted_number']

            bot_state['predictions_count'] = 0
            bot_state['is_paused'] = False
            bot_state['pause_end'] = None
            bot_state['cycle_pos'] = 0

            reset_verification_state()

            await event.respond(f"🔄 RESET!{f' (prédiction #{old_pred} effacée)' if old_pred else ''} Système libéré!")
            logger.info("RESET exécuté")

        elif cmd == '/forceunlock':
            """Force le déblocage immédiat"""
            old_pred = verification_state['predicted_number']
            reset_verification_state()
            await event.respond(f"🔓 FORCÉ! Prédiction #{old_pred} annulée. Système libre!")
            logger.info("FORCE UNLOCK exécuté")

        elif cmd == '/timeout':
            """Change le timeout"""
            global PREDICTION_TIMEOUT
            if len(parts) < 2:
                await event.respond(f"📋 Usage: `/timeout <nombre>`\nActuel: {PREDICTION_TIMEOUT} jeux")
                return
            
            try:
                new_timeout = int(parts[1])
                if new_timeout < 3 or new_timeout > 50:
                    await event.respond("❌ Timeout doit être entre 3 et 50")
                    return
                PREDICTION_TIMEOUT = new_timeout
                await event.respond(f"✅ Timeout changé à {PREDICTION_TIMEOUT} jeux")
            except ValueError:
                await event.respond("❌ Veuillez entrer un nombre valide")

        elif cmd == '/info':
            """Info complète"""
            last_src = bot_state['last_source_number']
            last_pred = bot_state['last_prediction_number']
            current_pred = verification_state['predicted_number']

            status = "⏸️ PAUSE" if bot_state['is_paused'] else "▶️ ACTIF"

            verif_info = "Aucune"
            if current_pred:
                next_check = current_pred + verification_state['current_check']
                remaining = PREDICTION_TIMEOUT - (last_src - current_pred)
                verif_info = f"#{current_pred} (check {verification_state['current_check']}/3, attend #{next_check}, timeout dans {remaining} jeux)"

            # Mapping formaté
            mapping_text = "\n".join([f"    _{k} → _{v}" for k, v in sorted(TARGET_CONFIG['triggers'].items())])

            msg = f"""📊 **STATUT SYSTÈME**

🟢 **État:** {status}
🎯 **Dernier source:** #{last_src} (fin _{get_last_digit(last_src)})
🔍 **Dernière prédiction:** #{last_pred if last_pred else 'Aucune'}
🔎 **Vérification:** {verif_info}
📊 **Compteur pause:** {bot_state['predictions_count']}/{PAUSE_AFTER}
⏱️ **Timeout:** {PREDICTION_TIMEOUT} jeux

🎯 **FINS DE NUMÉRO À PRÉDIRE:**
   • Impairs: {TARGET_CONFIG['impairs']}
   • Pairs: {TARGET_CONFIG['pairs']}

🔗 **DÉCLENCHEURS (fin → cible):**
{mapping_text}

🎨 **Cycle:** {' '.join(bot_state['cycle'])}
📍 **Position:** {bot_state['cycle_pos']}/{len(bot_state['cycle'])}

💡 `/reset` ou `/forceunlock` si bloqué"""

            if bot_state['is_paused'] and bot_state['pause_end']:
                remaining = bot_state['pause_end'] - datetime.now()
                msg += f"\n\n⏸️ **Pause:** {remaining.seconds // 60} min restantes"

            await event.respond(msg)

        elif cmd == '/next':
            cycle = bot_state['cycle']
            pos = bot_state['cycle_pos']
            if cycle:
                next_suit = cycle[pos % len(cycle)]
                await event.respond(f"🎯 Prochain: {SUIT_DISPLAY.get(next_suit, next_suit)}")
            else:
                await event.respond("❌ Cycle vide!")

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

        # Mapping formaté pour le startup
        mapping_text = "\n".join([f"  _{k} → _{v}" for k, v in sorted(TARGET_CONFIG['triggers'].items())])

        startup = f"""🤖 **BOT PRÉDICTION DÉMARRÉ** (v2 - Fins de numéro)

🎯 **Fins à prédire:** Impairs {TARGET_CONFIG['impairs']} | Pairs {TARGET_CONFIG['pairs']}
🔗 **Mapping déclencheurs:**
{mapping_text}

🎨 **Cycle:** {' '.join(bot_state['cycle'])}
⏸️ **Pause:** {PAUSE_AFTER} prédictions ({min(PAUSE_MINUTES)}-{max(PAUSE_MINUTES)} min)
⏱️ **Timeout:** {PREDICTION_TIMEOUT} jeux

**Nouvelles commandes:**
• /settargets <impairs> <pairs> - Fins de numéro à prédire
• /settriggers <liste> - Fins déclencheurs
• /setmapping <map> - Mapping déclencheur→cible
• /setcycle <emojis> - Cycle costumes
• /addsuit /removesuit - Gérer le cycle

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
