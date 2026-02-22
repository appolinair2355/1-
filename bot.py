import os
import asyncio
import re
import logging
import sys
import json
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights
from aiohttp import web
from config import (
    API_ID, API_HASH, BOT_TOKEN, ADMIN_ID,
    PORT, SUIT_DISPLAY, EXCLUDED_NUMBERS,
    DEFAULT_TRIGGER_PREDICTION_MAP, DEFAULT_SUIT_CYCLE
)

# Fichiers de configuration (stockés dans /tmp pour Render.com)
USERS_FILE = "/tmp/users_data.json"
PAUSE_CONFIG_FILE = "/tmp/pause_config.json"
CHANNELS_CONFIG_FILE = "/tmp/channels_config.json"
TRIGGER_PREDICTION_FILE = "/tmp/trigger_prediction_config.json"
SUIT_CYCLE_CONFIG_FILE = "/tmp/suit_cycle_config.json"

# Configuration par défaut des canaux
DEFAULT_SOURCE_CHANNEL_ID = -1002682552255
DEFAULT_PREDICTION_CHANNEL_ID = -1003430118891

# --- Configuration Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

if not API_ID or API_ID == 0:
    logger.error("API_ID manquant")
    exit(1)
if not API_HASH:
    logger.error("API_HASH manquant")
    exit(1)
if not BOT_TOKEN:
    logger.error("BOT_TOKEN manquant")
    exit(1)

# Session string depuis variable d'environnement (pour Render.com)
session_string = os.getenv('TELEGRAM_SESSION', '')
client = TelegramClient(StringSession(session_string), API_ID, API_HASH)

# --- Variables Globales ---
channels_config = {
    'source_channel_id': DEFAULT_SOURCE_CHANNEL_ID,
    'prediction_channel_id': DEFAULT_PREDICTION_CHANNEL_ID,
}

# Cycle de pause par défaut: 3min, 5min, 4min
DEFAULT_PAUSE_CYCLE = [180, 300, 240]
pause_config = {
    'cycle': DEFAULT_PAUSE_CYCLE.copy(),
    'current_index': 0,
    'predictions_count': 0,
    'is_paused': False,
    'pause_end_time': None,
    'just_resumed': False
}

# Mapping trigger→prédiction (ex: {"1": "0", "3": "2", "5": "4", "7": "6"})
trigger_prediction_map = DEFAULT_TRIGGER_PREDICTION_MAP.copy()

# Cycle des costumes (modifiable via /setsuitcycle)
suit_cycle_config = DEFAULT_SUIT_CYCLE.copy()

# État global
users_data = {}
current_game_number = 0
last_source_game_number = 0
last_predicted_number = None
predictions_enabled = True
already_predicted_games = set()

# État de vérification
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

# Variables pour le reset automatique
last_prediction_time = None
auto_reset_task = None

# Liste des numéros valides (recalculée selon les endings configurés)
VALID_NUMBERS = []

# ============================================================
# FONCTIONS DE CHARGEMENT/SAUVEGARDE
# ============================================================

def load_json(file_path, default=None):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Erreur chargement {file_path}: {e}")
    return default or {}

def save_json(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erreur sauvegarde {file_path}: {e}")

def load_all_configs():
    global channels_config, pause_config, users_data, trigger_prediction_map, suit_cycle_config, VALID_NUMBERS
    channels_config.update(load_json(CHANNELS_CONFIG_FILE, channels_config))
    pause_config.update(load_json(PAUSE_CONFIG_FILE, pause_config))
    users_data.update(load_json(USERS_FILE, {}))

    # Charger le mapping trigger→prédiction
    loaded_map = load_json(TRIGGER_PREDICTION_FILE, {})
    if loaded_map:
        trigger_prediction_map = loaded_map
        logger.info(f"📋 Mapping trigger→prédiction chargé: {trigger_prediction_map}")

    # Charger le cycle des costumes
    loaded_suit = load_json(SUIT_CYCLE_CONFIG_FILE, [])
    if loaded_suit and len(loaded_suit) > 0:
        suit_cycle_config = loaded_suit
        logger.info(f"🎨 Cycle des costumes chargé: {suit_cycle_config}")

    # Recalculer les numéros valides selon les endings configurés
    VALID_NUMBERS = get_valid_numbers()

    logger.info("✅ Configurations chargées")

def save_all_configs():
    save_json(CHANNELS_CONFIG_FILE, channels_config)
    save_json(PAUSE_CONFIG_FILE, pause_config)
    save_json(USERS_FILE, users_data)
    save_json(TRIGGER_PREDICTION_FILE, trigger_prediction_map)
    save_json(SUIT_CYCLE_CONFIG_FILE, suit_cycle_config)

# ============================================================
# GESTION NUMÉROS ET COSTUMES
# ============================================================

def get_valid_numbers():
    """Génère la liste des numéros valides selon les endings configurés"""
    global trigger_prediction_map
    valid = []
    # Récupérer tous les endings de prédiction configurés
    prediction_endings = set(trigger_prediction_map.values())

    for num in range(6, 1437):
        # Vérifier si le numéro n'est pas dans les exclus
        if num in EXCLUDED_NUMBERS:
            continue
        last_digit = str(num % 10)
        if last_digit in prediction_endings:
            valid.append(num)
    return valid

def get_suit_for_number(number):
    """Retourne le costume pour un numéro valide"""
    global suit_cycle_config
    if number not in VALID_NUMBERS:
        logger.error(f"❌ Numéro {number} non valide")
        return None
    idx = VALID_NUMBERS.index(number) % len(suit_cycle_config)
    return suit_cycle_config[idx]

def is_trigger_number(number):
    """Déclencheur: impair présent dans le mapping ET suivant valide"""
    global trigger_prediction_map

    if number % 2 == 0:
        return False

    # Vérifier si le numéro est dans les exclus
    if number in EXCLUDED_NUMBERS:
        return False

    last_digit = str(number % 10)
    # Vérifier si ce ending de trigger est configuré
    if last_digit not in trigger_prediction_map:
        return False

    next_num = number + 1
    # Vérifier que le suivant finit bien par l'ending prédit configuré
    expected_ending = trigger_prediction_map[last_digit]
    actual_ending = str(next_num % 10)
    is_valid = actual_ending == expected_ending and next_num in VALID_NUMBERS

    if is_valid:
        logger.info(f"🔥 DÉCLENCHEUR #{number} → prédit #{next_num} (finit par {expected_ending})")

    return is_valid

def get_trigger_target(number):
    """Retourne le numéro à prédire"""
    if not is_trigger_number(number):
        return None
    return number + 1

# ============================================================
# GESTION CANAUX
# ============================================================

def get_source_channel_id():
    return channels_config.get('source_channel_id', DEFAULT_SOURCE_CHANNEL_ID)

def get_prediction_channel_id():
    return channels_config.get('prediction_channel_id', DEFAULT_PREDICTION_CHANNEL_ID)

def set_channels(source_id=None, prediction_id=None):
    if source_id:
        channels_config['source_channel_id'] = source_id
    if prediction_id:
        channels_config['prediction_channel_id'] = prediction_id
    save_json(CHANNELS_CONFIG_FILE, channels_config)
    logger.info(f"📺 Canaux mis à jour: {channels_config}")

# ============================================================
# SYSTÈME DE PRÉDICTION ET VÉRIFICATION
# ============================================================

async def send_prediction(target_game: int, predicted_suit: str, base_game: int):
    """Envoie une prédiction au canal configuré"""
    global verification_state, last_predicted_number, last_prediction_time

    if not predictions_enabled:
        logger.warning("⛔ Prédictions désactivées")
        return False

    if verification_state['predicted_number'] is not None:
        logger.error(f"⛔ BLOQUÉ: Prédiction #{verification_state['predicted_number']} en cours!")
        return False

    try:
        prediction_channel_id = get_prediction_channel_id()
        entity = await client.get_input_entity(prediction_channel_id)

        prediction_text = f"""🎰 **PRÉDICTION #{target_game}**
🎯 Couleur: {SUIT_DISPLAY.get(predicted_suit, predicted_suit)}
⏳ Statut: EN ATTENTE DU RÉSULTAT..."""

        sent_msg = await client.send_message(entity, prediction_text)

        verification_state = {
            'predicted_number': target_game,
            'predicted_suit': predicted_suit,
            'current_check': 0,
            'message_id': sent_msg.id,
            'channel_id': prediction_channel_id,
            'status': 'pending',
            'base_game': base_game
        }

        last_predicted_number = target_game
        last_prediction_time = datetime.now()

        logger.info(f"🚀 PRÉDICTION #{target_game} ({predicted_suit}) LANCÉE")
        logger.info(f"🔍 Attente vérification: #{target_game} (check 0/3)")

        return True

    except Exception as e:
        logger.error(f"❌ Erreur envoi prédiction: {e}")
        return False

async def update_prediction_status(status: str):
    """Met à jour le statut de la prédiction"""
    global verification_state, stats_bilan, last_prediction_time

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

        updated_text = f"""🎰 **PRÉDICTION #{predicted_num}**
🎯 Couleur: {SUIT_DISPLAY.get(predicted_suit, predicted_suit)}
📊 Statut: {status_text}"""

        await client.edit_message(
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

        verification_state = {
            'predicted_number': None, 'predicted_suit': None,
            'current_check': 0, 'message_id': None,
            'channel_id': None, 'status': None, 'base_game': None
        }

        last_prediction_time = datetime.now()

        return True

    except Exception as e:
        logger.error(f"❌ Erreur mise à jour statut: {e}")
        return False

# ============================================================
# ANALYSE MESSAGES SOURCE
# ============================================================

def extract_game_number(message: str) -> int:
    """Extrait le numéro de jeu du message (supporte #N, #R, #X, etc.)"""
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

def extract_suits_from_first_group(message_text: str) -> list:
    """Extrait les costumes du PREMIER groupe de parenthèses"""
    matches = re.findall(r"\(([^)]+)\)", message_text)
    if not matches:
        return []

    first_group = matches[0]

    normalized = first_group.replace('❤️', '♥').replace('❤', '♥')
    normalized = normalized.replace('♠️', '♠').replace('♦️', '♦').replace('♣️', '♣')
    normalized = normalized.replace('♥️', '♥')

    suits = []
    for suit in ['♥', '♠', '♦', '♣']:
        if suit in normalized:
            suits.append(suit)

    logger.debug(f"Costumes trouvés dans premier groupe '{first_group}': {suits}")
    return suits

def is_message_editing(message_text: str) -> bool:
    """Vérifie si le message est en cours d'édition (commence par ⏰)"""
    return message_text.strip().startswith('⏰')

def is_message_finalized(message_text: str) -> bool:
    """Vérifie si le message est finalisé (contient ✅ ou 🔰)"""
    return '✅' in message_text or '🔰' in message_text

async def process_verification_step(game_number: int, message_text: str):
    """Traite UNE étape de vérification"""
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
