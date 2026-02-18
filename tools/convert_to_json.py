#!/usr/bin/env python3
"""
Convertit words.xlsx en JSON pour l'application Flask
"""

import pandas as pd
import json
from pathlib import Path

def convert_excel_to_json():
    print("="*70)
    print("📊 CONVERSION EXCEL → JSON")
    print("="*70)
    
    # Chercher le fichier Excel
    excel_files = ['data/words.xlsx']
    excel_path = None
    
    for filename in excel_files:
        path = Path(filename)
        if path.exists():
            excel_path = path
            break
    
    if not excel_path:
        print("❌ Aucun fichier Excel trouvé !")
        print("Fichiers recherchés :", ', '.join(excel_files))
        return False
    
    print(f"\n📁 Lecture : {excel_path}")
    df = pd.read_excel(excel_path)
    print(f"✓ {len(df)} mots chargés")
    print(f"✓ {len(df.columns)} attributs")
    
    # Convertir en dictionnaire
    data = {}
    
    for _, row in df.iterrows():
        word = str(row['word']).strip().lower()
        
        # Exclure 'word' et les valeurs NaN
        attrs = {}
        for col in df.columns:
            if col == 'word':
                continue
            
            value = row[col]
            
            # Ignorer les NaN
            if pd.isna(value):
                continue
            
            # Convertir en float Python natif
            attrs[col] = float(value)
        
        data[word] = attrs
    
    # Créer le dossier data s'il n'existe pas
    data_dir = Path('data')
    data_dir.mkdir(exist_ok=True)
    
    # Sauvegarder en JSON
    json_path = data_dir / 'words.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Fichier créé : {json_path}")
    print(f"✓ {len(data)} mots exportés")
    
    # Afficher un exemple
    first_word = list(data.keys())[0]
    print(f"\n📋 Exemple - '{first_word}' :")
    print(f"   {len(data[first_word])} attributs")
    examples = list(data[first_word].items())[:3]
    for attr, val in examples:
        print(f"   - {attr}: {val}")
    
    print("\n" + "="*70)
    print("✅ CONVERSION TERMINÉE")
    print("="*70)
    print(f"Vous pouvez maintenant lancer votre application avec :")
    print(f"  python app_improved_v2.py")
    print("="*70)
    
    return True


if __name__ == "__main__":
    import sys
    success = convert_excel_to_json()
    sys.exit(0 if success else 1)
