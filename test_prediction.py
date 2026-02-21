#!/usr/bin/env python3
"""
Test de la logique de prédiction
"""
import sys
sys.path.insert(0, '/mnt/kimi/output')

from config import EXCLUDED_NUMBERS, PREDICTION_MAP, CYCLE_IMPAIR, CYCLE_PAIR

def test_predictions():
    print("=== TEST DE LA LOGIQUE DE PRÉDICTION ===
")

    # Test 1: Vérifier les numéros exclus
    print("1. Test des numéros exclus:")
    excluded_test = [1086, 1089, 1267, 1270, 1388]
    for num in excluded_test:
        if num in EXCLUDED_NUMBERS:
            print(f"   ✅ {num} est bien exclu")
        else:
            print(f"   ❌ {num} devrait être exclu!")

    # Test 2: Vérifier que les numéros exclus ne sont pas dans PREDICTION_MAP
    print("
2. Test exclusion de la map:")
    for num in [1086, 1266, 1386]:
        if num not in PREDICTION_MAP:
            print(f"   ✅ {num} n'est pas dans PREDICTION_MAP")
        else:
            print(f"   ❌ {num} ne devrait pas être dans PREDICTION_MAP!")

    # Test 3: Vérifier la logique inversée
    print("
3. Test logique inversée:")
    test_cases = [
        (1, 'impair', 'pair'),    # 1 est impair, devrait utiliser cycle pair
        (2, 'pair', 'impair'),    # 2 est pair, devrait utiliser cycle impair
        (3, 'impair', 'pair'),    # 3 est impair, devrait utiliser cycle pair
        (4, 'pair', 'impair'),    # 4 est pair, devrait utiliser cycle impair
    ]

    for num, parite_recu, cycle_attendu in test_cases:
        suit = PREDICTION_MAP.get(num)
        if suit:
            # Vérifier quel cycle a été utilisé
            if cycle_attendu == 'pair':
                expected_suits = CYCLE_PAIR
            else:
                expected_suits = CYCLE_IMPAIR

            if suit in expected_suits:
                print(f"   ✅ {num} ({parite_recu}) -> {suit} (cycle {cycle_attendu})")
            else:
                print(f"   ❌ {num} ({parite_recu}) -> {suit} (mauvais cycle!)")
        else:
            print(f"   ❌ {num} non trouvé dans PREDICTION_MAP")

    # Test 4: Afficher quelques prédictions
    print("
4. Exemples de prédictions:")
    for n in sorted(PREDICTION_MAP.keys())[:20]:
        parite = "impair" if n % 2 == 1 else "pair"
        cycle = "pair" if n % 2 == 1 else "impair"
        print(f"   {n} ({parite}) -> {PREDICTION_MAP[n]} (cycle {cycle})")

    print("
=== TEST TERMINÉ ===")

if __name__ == '__main__':
    test_predictions()
