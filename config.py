"""
Configuration du bot - Variables d'environnement pour Render.com
"""
import os

# Telegram API credentials (fixes)
API_ID = 29177661
API_HASH = "a8639172fa8d35dbfd8ea46286d349ab"

# Bot Token - PEUT ETRE CHANGE VIA VARIABLE D'ENVIRONNEMENT RENDER
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7815360317:AAGsrFzeUZrHOjujf5aY2UjlBj4GOblHSig')

# IDs des canaux (fixes)
SOURCE_CHANNEL_ID = -1002682552255      # Canal source ou on recoit les numeros
PREDICTION_CHANNEL_ID = -1003430118891  # Canal ou on envoie les predictions
ADMIN_ID = 1190237801                   # ID de l'admin pour les notifications

# Configuration serveur
PORT = int(os.getenv('PORT', 10000))    # Port pour Render.com

# ============ NUMEROS EXCLUS ============
# Ces numeros ne sont ni predits ni utilisés comme déclencheurs
EXCLUDED_NUMBERS = set(
    list(range(1086, 1091)) +   # 1086, 1087, 1088, 1089, 1090
    list(range(1266, 1271)) +   # 1266, 1267, 1268, 1269, 1270
    list(range(1386, 1391))     # 1386, 1387, 1388, 1389, 1390
)
