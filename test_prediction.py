#!/usr/bin/env python3
"""
Test de la logique de prediction
"""
import sys
sys.path.insert(0, '/mnt/kimi/output')

from config import EXCLUDED_NUMBERS, PREDICTION_MAP, CYCLE_IMPAIR, CYCLE_PAIR

def test_predictions():
    print("=== TEST DE LA LOGIQUE DE PREDICTION ===")
    print()

    # Test 1: Verifier les numeros exclus
    print("1. Test des numeros exclus:")
    excluded_test = [1086, 1089, 1267, 1270, 1388]
    for num in excluded_test:
        if num in EXCLUDED_NUMBERS:
            print(f"   OK {num} est bien exclu")
        else:
            print(f"   ERREUR {num} devrait etre exclu!")

    # Test 2: Verifier que les numeros exclus ne sont pas dans PREDICTION_MAP
    print()
    print("2. Test exclusion de la map:")
    for num in [1086, 1266, 1386]:
        if num not in PREDICTION_MAP:
            print(f"   OK {num} n'est pas dans PREDICTION_MAP")
        else:
            print(f"   ERREUR {num} ne devrait pas etre dans PREDICTION_MAP!")

    # Test 3: Verifier la logique inversee
    print()
    print("3. Test logique inversee:")
    test_cases = [
        (1, 'impair', 'pair'),
        (2, 'pair', 'impair'),
        (3, 'impair', 'pair'),
        (4, 'pair', 'impair'),
    ]

    for num, parite_recu, cycle_attendu in test_cases:
        suit = PREDICTION_MAP.get(num)
        if suit:
            if cycle_attendu == 'pair':
                expected_suits = CYCLE_PAIR
            else:
                expected_suits = CYCLE_IMPAIR

            if suit in expected_suits:
                print(f"   OK {num} ({parite_recu}) -> {suit} (cycle {cycle_attendu})")
            else:
                print(f"   ERREUR {num} ({parite_recu}) -> {suit} (mauvais cycle!)")
        else:
            print(f"   ERREUR {num} non trouve dans PREDICTION_MAP")

    # Test 4: Afficher quelques predictions
    print()
    print("4. Exemples de predictions:")
    for n in sorted(PREDICTION_MAP.keys())[:20]:
        parite = "impair" if n % 2 == 1 else "pair"
        cycle = "pair" if n % 2 == 1 else "impair"
        print(f"   {n} ({parite}) -> {PREDICTION_MAP[n]} (cycle {cycle})")

    print()
    print("=== TEST TERMINE ===")

if __name__ == '__main__':
    test_predictions()
