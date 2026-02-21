"""
Configuration du bot - Toutes les variables sont définies ici
"""
import os

# Telegram API credentials
API_ID = 29177661
API_HASH = "a8639172fa8d35dbfd8ea46286d349ab"
BOT_TOKEN = "8359623168:AAHno00lno02QOw5OvGukP0TIgn4sDFB158"

# IDs des canaux
SOURCE_CHANNEL_ID = -1002682552255      # Canal source où on reçoit les numéros
PREDICTION_CHANNEL_ID = -1003430118891  # Canal où on envoie les prédictions
ADMIN_ID = 1190237801                   # ID de l'admin pour les notifications

# Configuration serveur
PORT = int(os.getenv('PORT', 10000))    # Port pour Render.com

# ============ CONFIGURATION DES PRÉDICTIONS ============

# Numéros exclus - ni déclencheurs ni prédictions
EXCLUDED_NUMBERS = set(
    list(range(1086, 1091)) +   # 1086, 1087, 1088, 1089, 1090
    list(range(1266, 1271)) +   # 1266, 1267, 1268, 1269, 1270
    list(range(1386, 1391))     # 1386, 1387, 1388, 1389, 1390
)

# Cycles de costumes
# Cycle impair (utilisé quand on reçoit un numéro PAIR)
CYCLE_IMPAIR = ['♦️', '♣️', '❤️', '♠️', '♦️', '❤️', '♠️', '♣️']
# Cycle pair (utilisé quand on reçoit un numéro IMPAIR)
CYCLE_PAIR = ['♦️', '❤️', '♣️', '♠️', '♦️', '♠️', '❤️', '♣️']

# Construction de la map de prédiction
PREDICTION_MAP = {}
idx_impair = 0
idx_pair = 0

# Tous les numéros valides (1-1440 sauf exclus)
VALID_NUMBERS = [n for n in range(1, 1441) if n not in EXCLUDED_NUMBERS]

for n in VALID_NUMBERS:
    if n % 2 == 1:
        # Nombre impair -> utilise cycle pair (logique inversée)
        PREDICTION_MAP[n] = CYCLE_PAIR[idx_pair % len(CYCLE_PAIR)]
        idx_pair += 1
    else:
        # Nombre pair -> utilise cycle impair (logique inversée)
        PREDICTION_MAP[n] = CYCLE_IMPAIR[idx_impair % len(CYCLE_IMPAIR)]
        idx_impair += 1
