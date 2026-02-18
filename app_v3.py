from __future__ import annotations

import json
import math
import os
import secrets
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(16))

BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# 0) OUTILS
# ============================================================


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _to_float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(int(v))
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# ============================================================
# 1) CHARGEMENT JSON + DÉCOUVERTE ATTRIBUTS
# ============================================================


def load_raw_words_json(path: str) -> dict[str, dict[str, Any]]:
    p = (BASE_DIR / path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"{p} introuvable. Vérifie WORDS_JSON_PATH.")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k.strip().lower()] = v
    return out


def discover_attr_keys(raw_db: dict[str, dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for _, attrs in raw_db.items():
        for ak in attrs.keys():
            if isinstance(ak, str) and ak.strip():
                keys.add(ak.strip())
    return keys


def W(threshold: float = 2.5) -> dict[str, Any]:
    return {"type": "weight", "min": 0.0, "max": 5.0, "threshold": float(threshold)}


# Les structurants "universels" (même si ton JSON change, on garde ces noms)
STRUCTURAL_BASE = {"vivant", "animal", "plante", "objet", "lieu", "concept"}
SCALES_BASE = {"taille", "poids", "durete"}
SIZE_TRIPLE = {"tres_petit", "taille", "geant"}


def build_attr_specs(all_keys: set[str]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}

    # Defaults
    for k in sorted(all_keys):
        # seuil par défaut : attribut binaire-ish 0/5
        specs[k] = W(2.5)

    # structurants : plus stricts
    for k in STRUCTURAL_BASE:
        if k in specs:
            specs[k] = W(3.0)

    # échelles
    for k in SCALES_BASE:
        if k in specs:
            specs[k] = W(3.0)

    # familles et sous-types (souvent 0/5)
    for k in all_keys:
        if k.startswith("fam_") or k.startswith("obj_") or k.startswith("lieu_"):
            specs[k] = W(3.0)

    # fonctions objet / attributs conceptuels typés
    for k in ("phenom_meteo", "fait_du_son", "se_tient_en_main", "sert_a_couper", "sert_a_lire_ecrire", "sert_a_manger_boire"):
        if k in specs:
            specs[k] = W(3.0)

    # couleur_typique / forme_simple : plutôt descriptifs (laisser 2.5)
    return specs


def clean_words_database(
    raw_db: dict[str, dict[str, Any]],
    attr_specs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float]]:
    cleaned: dict[str, dict[str, float]] = {}
    for word, attrs in raw_db.items():
        out: dict[str, float] = {}
        for ak, av in attrs.items():
            if ak not in attr_specs:
                continue
            fv = _to_float_or_none(av)
            if fv is None:
                continue
            spec = attr_specs[ak]
            out[ak] = clamp(fv, float(spec["min"]), float(spec["max"]))
        if out:
            cleaned[word] = out
    return cleaned


WORDS_JSON_PATH = os.getenv("WORDS_JSON_PATH", "data/words.json")
RAW_DB = load_raw_words_json(WORDS_JSON_PATH)
ALL_ATTR_KEYS = discover_attr_keys(RAW_DB)

ATTR_SPECS = build_attr_specs(ALL_ATTR_KEYS)
WORDS_DATABASE = clean_words_database(RAW_DB, ATTR_SPECS)

# Groupes dynamiques (suivant ton JSON)
OBJECT_SUBTYPES = {k for k in ALL_ATTR_KEYS if k.startswith("obj_")}
LIEU_SUBTYPES = {k for k in ALL_ATTR_KEYS if k.startswith("lieu_")}
FAMILIES = {k for k in ALL_ATTR_KEYS if k.startswith("fam_")}
CONCEPT_SUBTYPES = {k for k in ALL_ATTR_KEYS if k in {"phenom_meteo"}}

# Fonctions "objets"
OBJECT_FUNCTIONS = {k for k in ALL_ATTR_KEYS if k in {"fait_du_son", "se_tient_en_main", "sert_a_couper", "sert_a_lire_ecrire", "sert_a_manger_boire"}}

# Attributs "animal-only" (si présents)
ANIMAL_ONLY = {
    k
    for k in ALL_ATTR_KEYS
    if k
    in {
        "aboie",
        "miaule",
        "ronronne",
        "rongeur",
        "grimpe_arbres",
        "cage",
        "ferme",
        "lait",
        "laine",
        "oeufs",
        "felin",
        "rayures",
        "criniere",
        "taches",
        "vole",
        "chante",
        "bec",
        "plumes",
        "nageoires",
        "ecailles",
        "reptile",
        "carapace",
        "insecte",
        "ailes",
        "antennes",
        "tres_petit",
        "geant",
    }
}

STRUCTURAL = {k for k in STRUCTURAL_BASE if k in ALL_ATTR_KEYS}
SCALES = {k for k in SCALES_BASE if k in ALL_ATTR_KEYS}
SIZE_ATTRS = {k for k in SIZE_TRIPLE if k in ALL_ATTR_KEYS}


# ============================================================
# 2) IMPORTANCES (AMÉLIORÉES)
# ============================================================

ATTR_IMPORTANCE: dict[str, float] = {k: 1.0 for k in ALL_ATTR_KEYS}

# Structurants = CRITIQUES
for k in STRUCTURAL:
    ATTR_IMPORTANCE[k] = 2.8

# Familles très discriminantes
for k in FAMILIES:
    ATTR_IMPORTANCE[k] = 2.2

# Sous-types objets/lieux/concepts
for k in OBJECT_SUBTYPES | LIEU_SUBTYPES | CONCEPT_SUBTYPES:
    ATTR_IMPORTANCE[k] = 1.9

# Fonctions objets
for k in OBJECT_FUNCTIONS:
    ATTR_IMPORTANCE[k] = 1.7

# Attributs animaux spécifiques
for k in ANIMAL_ONLY:
    ATTR_IMPORTANCE[k] = max(ATTR_IMPORTANCE.get(k, 1.0), 1.6)

for k in SCALES:
    ATTR_IMPORTANCE[k] = 1.3


# ============================================================
# 3) TEXTE DES QUESTIONS
# ============================================================

QUESTION_TEXT: dict[str, str] = {
    # structurants
    "vivant": "Je ressens une énergie… Est-ce quelque chose de vivant ?",
    "animal": "Un regard… Est-ce un animal ?",
    "plante": "Une sève… Est-ce une plante ?",
    "objet": "Je vois une forme… Est-ce un objet (qu'on peut tenir / utiliser) ?",
    "lieu": "Je perçois un endroit… Est-ce plutôt un lieu ?",
    "concept": "Je sens une idée… Est-ce plutôt un concept ?",

    # descriptifs généraux
    "domestique": "Cette essence… Fait-elle partie du quotidien humain (domestique) ?",
    "interieur": "Je vois un espace clos… Est-ce plutôt à l'intérieur ?",
    "naturel": "Je sens l'origine… Est-ce naturel (pas fabriqué par l'humain) ?",
    "technologique": "Une vibration… Est-ce technologique ?",
    "transport": "Je vois un déplacement… Sert-il au transport ?",
    "outil": "Je perçois une utilité… Est-ce un outil ?",
    "comestible": "Une odeur… une tentation… Est-ce comestible ?",
    "dangereux": "Un frisson… Est-ce dangereux ?",
    "bruyant": "J'entends… Est-ce bruyant ?",
    "mobile": "Je sens un mouvement… Est-ce mobile ?",
    "vivant_sauvage": "Je perçois la nature… Est-ce un vivant sauvage ?",
    "aquatique": "L'eau… je sens l'eau… Est-ce lié à l'eau ?",
    "aerien": "Je perçois l'air… Est-ce lié au ciel / à l'air ?",
    "feu_chaud": "Je sens la chaleur… Est-ce lié au feu / au chaud ?",

    # échelles
    "tres_petit": "Minuscule… Tient-il dans la paume d'une main ?",
    "taille": "Cette présence… Est-elle plus grande qu'un humain ?",
    "geant": "Une présence imposante… Est-ce gigantesque ?",
    "poids": "Je sens une masse… Est-ce plutôt lourd ?",
    "durete": "Je perçois la matière… Est-ce plutôt dur ?",

    # animaux
    "aboie": "J'entends un son… Est-ce que ça aboie ?",
    "miaule": "Un miaulement… Est-ce que ça miaule ?",
    "ronronne": "Une vibration douce… Est-ce que ça ronronne ?",
    "rongeur": "Je vois des dents… Est-ce un rongeur ?",
    "grimpe_arbres": "Je vois de la hauteur… Grimpe-t-il aux arbres ?",
    "cage": "Un espace restreint… Vit-il typiquement en cage ?",
    "ferme": "Je sens la campagne… Est-ce un animal de ferme ?",
    "lait": "Je perçois un liquide blanc… Produit-il du lait ?",
    "laine": "Une texture douce… Donne-t-il de la laine ?",
    "oeufs": "Une forme ovale… Pond-il des œufs ?",
    "felin": "Une grâce féline… Est-ce un félin ?",
    "rayures": "Des lignes parallèles… A-t-il des rayures ?",
    "criniere": "Une couronne royale… A-t-il une crinière ?",
    "taches": "Des motifs irréguliers… A-t-il des taches ?",
    "vole": "Des ailes déployées… Vole-t-il réellement ?",
    "chante": "Une mélodie… Chante-t-il ?",
    "bec": "Je vois une pointe… A-t-il un bec ?",
    "plumes": "Une texture légère… A-t-il des plumes ?",
    "nageoires": "Des extensions aquatiques… A-t-il des nageoires ?",
    "ecailles": "Une peau particulière… A-t-il des écailles ?",
    "reptile": "Un sang froid… Est-ce un reptile ?",
    "carapace": "Une protection dure… A-t-il une carapace ?",
    "insecte": "Six pattes… Est-ce un insecte ?",
    "ailes": "Des ailes fines… A-t-il des ailes d'insecte ?",
    "antennes": "Des capteurs… A-t-il des antennes ?",

    # familles
    "fam_mammifere": "Je sens du sang chaud… Est-ce un mammifère ?",
    "fam_oiseau": "Je vois des plumes… Est-ce un oiseau ?",
    "fam_poisson": "Je sens l'eau… Est-ce un poisson ?",
    "fam_reptile": "Je perçois du sang froid… Est-ce un reptile ?",
    "fam_insecte": "Je perçois de petites pattes… Est-ce un insecte ?",
    "fam_arachnide": "Huit pattes… Est-ce un arachnide ?",
    "fam_amphibien": "Eau et terre… Est-ce un amphibien ?",
    "fam_plante": "Racines et feuilles… Est-ce une plante ?",
    "fam_lieu": "Je sens un endroit… Est-ce un lieu ?",
    "fam_objet": "Je perçois une utilisation… Est-ce un objet ?",
    "fam_concept": "Je sens une idée… Est-ce un concept ?",

    # sous-types objets
    "obj_electronique": "Des circuits… Est-ce un objet électronique ?",
    "obj_mobilier": "Je vois une pièce… Est-ce du mobilier ?",
    "obj_cuisine": "Je sens la cuisine… Est-ce lié à la cuisine ?",
    "obj_recipent": "Contenant… Est-ce un récipient ?",
    "obj_outil_tranchant": "Une lame… Est-ce un outil tranchant ?",
    "obj_ecriture_papeterie": "Papier et encre… Est-ce pour écrire / papeterie ?",
    "obj_instrument_musique": "Une note… Est-ce un instrument de musique ?",
    "obj_hygiene": "Propreté… Est-ce lié à l'hygiène ?",
    "obj_vetement_accessoire": "Porté sur soi… Vêtement / accessoire ?",
    "obj_audio_video": "Images ou sons… Audio / vidéo ?",
    "obj_energie_charge": "Énergie… charge / alimentation ?",
    "obj_mesure_temps": "Le temps… mesure du temps ?",

    # sous-types lieux
    "lieu_nature": "Je vois la nature… Est-ce un lieu naturel ?",
    "lieu_batiment": "Des murs… Est-ce un bâtiment / lieu construit ?",
    "lieu_transport": "Départs et arrivées… Est-ce lié au transport (gare, etc.) ?",
    "lieu_eau": "Présence d'eau… Est-ce un lieu d'eau (mer/lac/rivière) ?",

    # concepts
    "phenom_meteo": "Ciel et climat… Est-ce un phénomène météo ?",

    # fonctions d'objet
    "fait_du_son": "Je perçois un son… Cet objet fait-il du son ?",
    "se_tient_en_main": "Prise en main… Est-ce quelque chose qui se tient en main ?",
    "sert_a_couper": "Fonction… Sert-il à couper ?",
    "sert_a_lire_ecrire": "Fonction… Sert-il à lire ou écrire ?",
    "sert_a_manger_boire": "Fonction… Sert-il à manger ou boire ?",
}

# pool initial
QUESTION_POOL: list[str] = [
    *[a for a in ("vivant", "animal", "plante", "objet", "lieu", "concept") if a in ALL_ATTR_KEYS],
    *[a for a in ("fam_oiseau", "fam_insecte", "fam_poisson", "fam_reptile", "fam_mammifere", "fam_arachnide", "fam_amphibien") if a in ALL_ATTR_KEYS],
    *[a for a in ("technologique", "naturel", "domestique", "interieur", "mobile", "aquatique", "aerien", "dangereux", "bruyant", "comestible", "transport", "outil", "feu_chaud") if a in ALL_ATTR_KEYS],
    *sorted([a for a in ANIMAL_ONLY if a in ALL_ATTR_KEYS and a not in SIZE_ATTRS]),
    *[a for a in ("tres_petit", "taille", "geant", "poids", "durete") if a in ALL_ATTR_KEYS],
    *sorted(list(OBJECT_SUBTYPES)),
    *sorted(list(OBJECT_FUNCTIONS)),
    *sorted(list(LIEU_SUBTYPES)),
    *sorted(list(CONCEPT_SUBTYPES)),
]

TOTAL_QUESTIONS = int(os.getenv("TOTAL_QUESTIONS", "15"))  # Augmenté de 12 → 15
TOTAL_QUESTIONS = max(5, min(18, TOTAL_QUESTIONS))
MAX_QUESTIONS_WITH_TIEBREAKER = TOTAL_QUESTIONS + 3  # 3 tie-breakers au lieu de 2


# ============================================================
# 4) INFÉRENCES / COHÉRENCES
# ============================================================


def apply_inferences(answers: dict[str, int]) -> None:
    """Inférences logiques SANS forcer brutalement (permet erreurs user)."""
    
    if answers.get("animal") == 1:
        answers["vivant"] = 1
        if "plante" not in answers:
            answers.setdefault("plante", 0)
        if "objet" not in answers:
            answers.setdefault("objet", 0)
        if "lieu" not in answers:
            answers.setdefault("lieu", 0)

    if answers.get("plante") == 1:
        answers["vivant"] = 1
        if "animal" not in answers:
            answers.setdefault("animal", 0)
        if "objet" not in answers:
            answers.setdefault("objet", 0)
        if "lieu" not in answers:
            answers.setdefault("lieu", 0)

    if answers.get("objet") == 1:
        answers["vivant"] = 0
        if "animal" not in answers:
            answers.setdefault("animal", 0)
        if "plante" not in answers:
            answers.setdefault("plante", 0)

    if answers.get("lieu") == 1:
        answers["vivant"] = 0
        if "animal" not in answers:
            answers.setdefault("animal", 0)
        if "plante" not in answers:
            answers.setdefault("plante", 0)
        if "objet" not in answers:
            answers.setdefault("objet", 0)

    if answers.get("concept") == 1:
        answers["vivant"] = 0
        if "animal" not in answers:
            answers.setdefault("animal", 0)
        if "plante" not in answers:
            answers.setdefault("plante", 0)
        if "objet" not in answers:
            answers.setdefault("objet", 0)

    strong_animal = {
        "bec", "plumes", "aboie", "miaule", "ronronne", "nageoires", "ecailles",
        "reptile", "carapace", "insecte", "ailes", "antennes", "oeufs", "felin",
        "rongeur", "ferme", "lait", "laine", "vole", "chante",
    }
    if any(answers.get(a) == 1 for a in strong_animal if a in ALL_ATTR_KEYS):
        answers["animal"] = 1
        answers["vivant"] = 1
        if "plante" not in answers:
            answers.setdefault("plante", 0)
        if "objet" not in answers:
            answers.setdefault("objet", 0)

    if any(answers.get(a) == 1 for a in OBJECT_SUBTYPES):
        if answers.get("animal") != 1:
            answers["objet"] = 1
            answers["vivant"] = 0

    if any(answers.get(a) == 1 for a in OBJECT_FUNCTIONS):
        if answers.get("animal") != 1:
            answers["objet"] = 1
            answers["vivant"] = 0

    if any(answers.get(a) == 1 for a in LIEU_SUBTYPES):
        answers["lieu"] = 1
        answers["vivant"] = 0

    if answers.get("phenom_meteo") == 1:
        answers["concept"] = 1
        answers["vivant"] = 0

    if answers.get("bec") == 1 or answers.get("plumes") == 1:
        answers.setdefault("fam_oiseau", 1)
        answers.setdefault("fam_insecte", 0)
        answers.setdefault("fam_poisson", 0)

    if answers.get("antennes") == 1 or answers.get("insecte") == 1:
        answers.setdefault("fam_insecte", 1)
        answers.setdefault("fam_oiseau", 0)

    if answers.get("nageoires") == 1:
        answers.setdefault("aquatique", 1)
        answers.setdefault("fam_poisson", 1)
        answers.setdefault("fam_oiseau", 0)
        answers.setdefault("plumes", 0)

    if answers.get("reptile") == 1:
        answers.setdefault("fam_reptile", 1)

    if answers.get("tres_petit") == 1:
        if "taille" in ALL_ATTR_KEYS:
            answers.setdefault("taille", 0)
        if "geant" in ALL_ATTR_KEYS:
            answers.setdefault("geant", 0)

    if answers.get("geant") == 1:
        if "tres_petit" in ALL_ATTR_KEYS:
            answers.setdefault("tres_petit", 0)

    if answers.get("taille") == 1:
        if "tres_petit" in ALL_ATTR_KEYS:
            answers.setdefault("tres_petit", 0)


def parse_answer(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return 1 if raw else 0
    if isinstance(raw, (int, float)):
        return 1 if int(raw) == 1 else 0
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "oui", "y", "ok"):
        return 1
    if s in ("0", "false", "no", "non", "n"):
        return 0
    return None


# ============================================================
# 5) SCORE PROBA / RANKING
# ============================================================


def get_unknown_penalty(attr: str) -> float:
    """Pénalité adaptative selon l'importance de l'attribut manquant."""
    if attr in STRUCTURAL:
        return 5.0
    elif attr in FAMILIES:
        return 4.0
    elif attr in (OBJECT_SUBTYPES | LIEU_SUBTYPES | CONCEPT_SUBTYPES):
        return 3.5
    elif attr in OBJECT_FUNCTIONS:
        return 3.0
    elif attr in ANIMAL_ONLY:
        return 2.8
    else:
        return 2.2


def p_yes_from_weight(attr: str, v: float) -> float:
    """AMÉLIORATION: Pentes plus fortes pour mieux discriminer."""
    spec = ATTR_SPECS[attr]
    thr = float(spec["threshold"])
    
    if attr in STRUCTURAL:
        k = 3.2
    elif attr.startswith("fam_"):
        k = 3.0
    elif attr.startswith("obj_") or attr.startswith("lieu_"):
        k = 2.8
    elif attr in OBJECT_FUNCTIONS:
        k = 2.6
    else:
        k = 2.2
    
    return sigmoid((v - thr) * k)


def word_loss_for_answer(word_attrs: dict[str, float], attr: str, answer: int) -> float:
    """Calcul du loss avec pénalité adaptative pour valeurs manquantes."""
    imp = ATTR_IMPORTANCE.get(attr, 1.0)
    v = word_attrs.get(attr)
    
    if v is None:
        return get_unknown_penalty(attr) * imp

    p_yes = p_yes_from_weight(attr, float(v))
    eps = 1e-6
    if answer == 1:
        loss = -math.log(max(eps, p_yes))
    else:
        loss = -math.log(max(eps, 1.0 - p_yes))
    return loss * imp


def rank_candidates(answers: dict[str, int], candidates: list[str]) -> list[tuple[str, float]]:
    ranked: list[tuple[str, float]] = []
    for w in candidates:
        attrs = WORDS_DATABASE.get(w, {})
        score = 0.0
        for a, ans in answers.items():
            if a not in ATTR_SPECS:
                continue
            score += word_loss_for_answer(attrs, a, int(ans))
        ranked.append((w, score))
    ranked.sort(key=lambda x: x[1])
    return ranked


# ============================================================
# NOUVEAU: DÉTECTION DES ÉGALITÉS PARFAITES
# ============================================================

def detect_perfect_ties(ranked: list[tuple[str, float]]) -> list[str]:
    """Détecte les mots avec exactement le même score."""
    if len(ranked) < 2:
        return []
    top_score = ranked[0][1]
    tied_words = [w for w, s in ranked if abs(s - top_score) < 0.001]
    if len(tied_words) > 1:
        return tied_words
    return []


# Dictionnaire de corrélations
ATTRIBUTE_CORRELATIONS = {
    'bec': ['plumes', 'fam_oiseau'],
    'plumes': ['bec', 'fam_oiseau'],
    'miaule': ['ronronne', 'felin'],
    'ronronne': ['miaule', 'felin'],
    'ecailles': ['nageoires', 'fam_poisson'],
    'nageoires': ['ecailles', 'fam_poisson'],
    'bruyant': ['fait_du_son'],
    'fait_du_son': ['bruyant'],
    'plante': ['fam_plante'],
    'fam_plante': ['plante'],
}


# ============================================================
# 6) FILTRAGE STRUCTURANT
# ============================================================

STRUCT_MARGIN = 0.4  # réduit de 0.6 → 0.4 (plus strict = élimine plus)


def compatible_structural(word_attrs: dict[str, float], answers: dict[str, int]) -> bool:
    """Filtrage dur avec élimination des mots incomplets."""
    for a, ans in answers.items():
        if a not in STRUCTURAL:
            continue
        
        v = word_attrs.get(a)
        thr = float(ATTR_SPECS[a]["threshold"])
        
        if v is None:
            if int(ans) == 1:
                return False
            continue
        
        if int(ans) == 1 and float(v) < thr - STRUCT_MARGIN:
            return False
        if int(ans) == 0 and float(v) > thr + STRUCT_MARGIN + 0.4:
            return False
    
    return True


# ============================================================
# 7) GAIN D'INFO
# ============================================================


def entropy(p: float) -> float:
    """Entropie binaire."""
    p = min(1.0 - 1e-9, max(1e-9, p))
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def expected_information_gain(candidates: list[str], attr: str, answers: dict[str, int] = None) -> float:
    """
    AMÉLIORATION: IG pondéré par coverage sans rejet brutal.
    Favorise les attributs qui séparent bien les candidats.
    """
    if len(candidates) < 2:
        return 0.0
    
    known = 0
    ps: list[float] = []
    for w in candidates:
        v = WORDS_DATABASE.get(w, {}).get(attr)
        if v is None:
            continue
        known += 1
        ps.append(p_yes_from_weight(attr, float(v)))

    if known == 0:
        return 0.0

    coverage = known / max(1, len(candidates))
    p_bar = sum(ps) / known

    if p_bar < 0.05 or p_bar > 0.95:
        return 0.0

    H_before = entropy(p_bar)
    
    sum_yes = sum(ps)
    sum_no = sum(1.0 - p for p in ps)
    
    if sum_yes <= 1e-9 or sum_no <= 1e-9:
        return 0.0
    
    def weight_entropy(ws: list[float]) -> float:
        s = sum(ws)
        if s <= 1e-9:
            return 0.0
        h = 0.0
        for x in ws:
            if x <= 1e-12:
                continue
            pp = x / s
            h -= pp * math.log2(pp)
        return h
    
    H_yes = weight_entropy(ps)
    H_no = weight_entropy([1.0 - p for p in ps])
    
    gain = H_before * (coverage ** 0.5) * 0.8 + ((coverage ** 0.5) * 0.2)
    gain *= (1.0 - abs(p_bar - 0.5) * 1.2)
    gain *= (0.7 + 0.3 * (H_yes + H_no) / max(1e-9, math.log2(max(2, known)) * 2))
    
    if attr in STRUCTURAL:
        gain *= 1.3
    if attr.startswith("fam_"):
        gain *= 1.2
    
    # NOUVEAU : Pénalité pour redondance
    if answers and attr in ATTRIBUTE_CORRELATIONS:
        for corr in ATTRIBUTE_CORRELATIONS[attr]:
            if corr in answers:
                gain *= 0.2
    
    return max(0.0, gain)


# ============================================================
# 8) LOGIQUE "ARBRE MACRO + GATES"
# ============================================================


def dont_ask_from_answers(answers: dict[str, int]) -> set[str]:
    """Détermine quelles questions sont inutiles selon l'état actuel."""
    d: set[str] = set(answers.keys())

    vivant = answers.get("vivant")
    animal = answers.get("animal")
    plante = answers.get("plante")
    objet = answers.get("objet")
    lieu = answers.get("lieu")
    concept = answers.get("concept")
    techno = answers.get("technologique")

    if vivant == 0:
        d |= {"animal", "plante"}
        d |= ANIMAL_ONLY
        d |= FAMILIES

    if vivant == 1:
        d |= {"objet", "lieu", "concept"}
        d |= OBJECT_SUBTYPES | OBJECT_FUNCTIONS | LIEU_SUBTYPES | CONCEPT_SUBTYPES

    if animal == 1:
        d |= {"plante", "objet", "lieu", "concept"}
        d |= OBJECT_SUBTYPES | OBJECT_FUNCTIONS | LIEU_SUBTYPES
    
    if plante == 1:
        d |= {"animal", "objet", "lieu", "concept"}
        d |= ANIMAL_ONLY | FAMILIES
    
    if objet == 1:
        d |= {"animal", "plante", "lieu", "concept"}
        d |= ANIMAL_ONLY | FAMILIES
    
    if lieu == 1:
        d |= {"animal", "plante", "objet", "concept"}
        d |= ANIMAL_ONLY | FAMILIES | OBJECT_SUBTYPES | OBJECT_FUNCTIONS
    
    if concept == 1:
        d |= {"animal", "plante", "objet", "lieu"}
        d |= ANIMAL_ONLY | FAMILIES | OBJECT_SUBTYPES | OBJECT_FUNCTIONS

    if techno == 1:
        d |= ANIMAL_ONLY | FAMILIES

    if objet != 1:
        d |= OBJECT_SUBTYPES | OBJECT_FUNCTIONS
    if lieu != 1:
        d |= LIEU_SUBTYPES
    if concept != 1:
        d |= CONCEPT_SUBTYPES

    family_yes = next((f for f in FAMILIES if answers.get(f) == 1), None)
    if family_yes:
        d |= FAMILIES - {family_yes}

    if answers.get("tres_petit") == 1:
        d |= {"taille", "geant"} & ALL_ATTR_KEYS
    if answers.get("taille") == 1 or answers.get("geant") == 1:
        d |= {"tres_petit"} & ALL_ATTR_KEYS

    return d


def pick_best_attr(
    candidates_focus: list[str], 
    attrs: Iterable[str], 
    asked: set[str], 
    dont: set[str],
    answers: dict[str, int],
    min_gain: float = 0.0
) -> str | None:
    """Choisit le meilleur attribut parmi une liste selon l'IG."""
    options = [
        a for a in attrs 
        if a in ALL_ATTR_KEYS 
        and a in QUESTION_TEXT 
        and a not in asked 
        and a not in dont
    ]
    if not options:
        return None
    
    best = max(options, key=lambda a: expected_information_gain(candidates_focus, a, answers))
    
    if expected_information_gain(candidates_focus, best, answers) < min_gain:
        return None
    
    return best


def choose_next_question(
    answers: dict[str, int],
    asked: set[str],
    candidates_focus: list[str],
    last_was_unknown: bool,
) -> str | None:
    """
    AMÉLIORATION: Arbre de décision optimisé pour éviter redondances
    et poser les questions les plus discriminantes.
    """
    dont = dont_ask_from_answers(answers)

    if last_was_unknown:
        q = pick_best_attr(
            candidates_focus, 
            ("vivant", "animal", "objet", "lieu", "concept", "plante"), 
            asked, 
            dont,
            answers,
            min_gain=0.01
        )
        if q:
            return q

    if "vivant" in ALL_ATTR_KEYS and "vivant" not in answers and "vivant" not in asked:
        return "vivant"

    vivant = answers.get("vivant")

    if vivant == 1:
        if "animal" in ALL_ATTR_KEYS and "animal" not in answers and "animal" not in asked:
            return "animal"
        
        if answers.get("animal") == 0:
            if "plante" in ALL_ATTR_KEYS and "plante" not in answers and "plante" not in asked:
                return "plante"

        if answers.get("animal") == 1:
            if answers.get("vole") == 1:
                if "plumes" in ALL_ATTR_KEYS and "plumes" not in answers and "plumes" not in asked:
                    return "plumes"
                if "antennes" in ALL_ATTR_KEYS and "antennes" not in answers and "antennes" not in asked:
                    return "antennes"

            family_order = [
                "fam_mammifere",
                "fam_oiseau",
                "fam_insecte",
                "fam_poisson",
                "fam_reptile",
                "fam_arachnide",
                "fam_amphibien",
            ]
            
            fam_yes = next((f for f in family_order if answers.get(f) == 1), None)

            if fam_yes is None:
                q = pick_best_attr(candidates_focus, family_order, asked, dont, answers, min_gain=0.02)
                if q:
                    return q

            if fam_yes == "fam_oiseau":
                q = pick_best_attr(
                    candidates_focus,
                    ("aquatique", "taille", "bec", "chante"),
                    asked, dont, answers
                )
                if q:
                    return q

            if fam_yes == "fam_insecte":
                q = pick_best_attr(candidates_focus, ("tres_petit", "antennes", "ailes"), asked, dont, answers)
                if q:
                    return q

            if fam_yes == "fam_poisson":
                q = pick_best_attr(candidates_focus, ("nageoires", "taille", "dangereux"), asked, dont, answers)
                if q:
                    return q

            if fam_yes == "fam_reptile":
                q = pick_best_attr(candidates_focus, ("carapace", "ecailles", "aquatique"), asked, dont, answers)
                if q:
                    return q

            if fam_yes == "fam_mammifere":
                q = pick_best_attr(
                    candidates_focus,
                    ("domestique", "ferme", "felin", "rongeur", "aboie", "miaule", "taille"),
                    asked, dont, answers
                )
                if q:
                    return q

        allowed = [
            a for a in QUESTION_POOL
            if a in ALL_ATTR_KEYS
            and a in QUESTION_TEXT
            and a not in asked
            and a not in dont
            and a not in (OBJECT_SUBTYPES | OBJECT_FUNCTIONS | LIEU_SUBTYPES | CONCEPT_SUBTYPES)
        ]
        if allowed:
            return max(allowed, key=lambda a: expected_information_gain(candidates_focus, a, answers))

    if vivant == 0:
        tri = [a for a in ("objet", "lieu", "concept") if a in ALL_ATTR_KEYS]
        q = pick_best_attr(candidates_focus, tri, asked, dont, answers, min_gain=0.01)
        if q and q not in answers:
            return q

        if answers.get("objet") == 1:
            priority_obj = [
                "obj_instrument_musique",
                "obj_electronique",
                "obj_mobilier",
                "obj_cuisine",
                "obj_hygiene",
            ]
            q = pick_best_attr(candidates_focus, priority_obj, asked, dont, answers, min_gain=0.02)
            if q:
                return q
            
            q = pick_best_attr(
                candidates_focus,
                ("se_tient_en_main", "sert_a_manger_boire", "sert_a_lire_ecrire", "fait_du_son"),
                asked, dont, answers,
                min_gain=0.01
            )
            if q:
                return q
            
            q = pick_best_attr(candidates_focus, ("technologique", "transport"), asked, dont, answers)
            if q:
                return q

        if answers.get("lieu") == 1:
            q = pick_best_attr(
                candidates_focus,
                sorted(LIEU_SUBTYPES),
                asked, dont, answers,
                min_gain=0.02
            )
            if q:
                return q
            
            q = pick_best_attr(candidates_focus, ("naturel", "interieur"), asked, dont, answers)
            if q:
                return q

        if answers.get("concept") == 1:
            q = pick_best_attr(candidates_focus, ("phenom_meteo", "feu_chaud"), asked, dont, answers)
            if q:
                return q

        allowed = [a for a in QUESTION_POOL if a in QUESTION_TEXT and a not in asked and a not in dont]
        if allowed:
            return max(allowed, key=lambda a: expected_information_gain(candidates_focus, a, answers))

    for a in QUESTION_POOL:
        if a in QUESTION_TEXT and a not in asked and a not in dont:
            return a
    
    return None


def make_question_payload(attr: str, number: int, total: int, is_tiebreaker: bool = False) -> dict[str, Any]:
    return {
        "id": attr,
        "text": QUESTION_TEXT.get(attr, f"Est-ce lié à {attr} ?"),
        "question_number": number,
        "total_questions": total,
        "is_tiebreaker": is_tiebreaker,
    }


# ============================================================
# 9) ROUTES
# ============================================================


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start_game():
    session["answers"] = {}
    session["asked"] = []
    session["question_count"] = 0
    session["tiebreaker_used"] = False
    session["last_answer_unknown"] = False

    all_words = list(WORDS_DATABASE.keys())
    if not all_words:
        return jsonify({"success": False, "error": "Base de mots vide (JSON)"}), 500

    q = "vivant" if "vivant" in QUESTION_TEXT else next(iter(QUESTION_POOL), None)
    if not q:
        return jsonify({"success": False, "error": "Aucune question disponible"}), 500

    session["asked"].append(q)
    session["question_count"] = 1
    return jsonify({"success": True, "question": make_question_payload(q, 1, TOTAL_QUESTIONS)})


@app.route("/answer", methods=["POST"])
def answer_question():
    data = request.get_json(force=True) or {}
    qid = data.get("question_id")
    raw_answer = data.get("answer", None)

    session.setdefault("answers", {})
    session.setdefault("asked", [])
    session.setdefault("question_count", 0)
    session.setdefault("tiebreaker_used", False)
    session.setdefault("last_answer_unknown", False)

    if qid and qid not in ATTR_SPECS:
        qid = None

    ans = parse_answer(raw_answer)
    session["last_answer_unknown"] = ans is None

    if qid:
        if qid not in session["asked"]:
            session["asked"].append(qid)
        if ans is not None:
            session["answers"][qid] = ans

    answers: dict[str, int] = session["answers"]
    apply_inferences(answers)

    asked_set = set(session["asked"])
    count = len(asked_set)

    all_words = list(WORDS_DATABASE.keys())
    if not all_words:
        return jsonify({"success": False, "error": "Base de mots vide (JSON)"}), 500

    base_candidates = [w for w, attrs in WORDS_DATABASE.items() if compatible_structural(attrs, answers)]
    if len(base_candidates) < 5:
        base_candidates = all_words

    ranked = rank_candidates(answers, base_candidates)
    best_word, best_score = ranked[0]
    
    # NOUVEAU : Détecter et gérer les égalités parfaites
    # MAIS seulement après au moins 5 questions pour éviter les faux positifs
    if count >= 5:
        ties = detect_perfect_ties(ranked)
        if ties and len(ties) > 1:
            return jsonify({
                "success": True,
                "done": True,
                "prediction": random.choice(ties),
                "candidates": ties,
                "message": f"Impossible de choisir entre : {', '.join(ties)}. Ces mots sont trop similaires."
            })

    second_score = ranked[1][1] if len(ranked) > 1 else best_score + 999.0
    confidence_gap = second_score - best_score

    if count >= TOTAL_QUESTIONS:
        # Permettre PLUSIEURS tie-breakers tant que gap < 2.5 et questions disponibles
        if (
            (count < MAX_QUESTIONS_WITH_TIEBREAKER)
            and (confidence_gap < 2.5)  # Si pas assez confiant
        ):
            focus = [w for w, _ in ranked[:60]]
            q = choose_next_question(
                answers=answers,
                asked=asked_set,
                candidates_focus=focus,
                last_was_unknown=session.get("last_answer_unknown", False),
            )
            if q and q not in asked_set:
                # NE PLUS marquer tiebreaker_used pour permettre plusieurs tie-breakers
                session["asked"].append(q)
                session["question_count"] = len(set(session["asked"]))
                return jsonify(
                    {
                        "success": True,
                        "done": False,
                        "question": make_question_payload(
                            q,
                            session["question_count"],
                            MAX_QUESTIONS_WITH_TIEBREAKER,
                            is_tiebreaker=True,
                        ),
                    }
                )

        return jsonify(
            {
                "success": True,
                "done": True,
                "prediction": best_word,
                "candidates": [w for w, _ in ranked[:3]],
                "debug": {
                    "confidence_gap": confidence_gap,
                    "best_score": best_score,
                    "second_score": second_score,
                    "candidates_count": len(base_candidates),
                    "questions_asked": count,
                    "max_possible": MAX_QUESTIONS_WITH_TIEBREAKER,
                    "reason": "max_questions_reached" if count >= MAX_QUESTIONS_WITH_TIEBREAKER else "gap_insufficient"
                },
            }
        )

    # Victoire précoce plus exigeante (4.0 au lieu de 2.5)
    if count >= 7 and confidence_gap > 4.0:
        return jsonify(
            {
                "success": True,
                "done": True,
                "prediction": best_word,
                "candidates": [w for w, _ in ranked[:3]],
                "debug": {"confidence_gap": confidence_gap, "early_stop": True},
            }
        )

    focus_words = [w for w, _ in ranked[:60]]
    q = choose_next_question(
        answers=answers,
        asked=asked_set,
        candidates_focus=focus_words,
        last_was_unknown=session.get("last_answer_unknown", False),
    )

    if not q:
        return jsonify(
            {
                "success": True,
                "done": True,
                "prediction": best_word,
                "candidates": [w for w, _ in ranked[:3]],
                "debug": {"confidence_gap": confidence_gap, "fallback_stop": True},
            }
        )

    if q not in session["asked"]:
        session["asked"].append(q)
    session["question_count"] = len(set(session["asked"]))

    return jsonify(
        {
            "success": True,
            "done": False,
            "question": make_question_payload(q, session["question_count"], TOTAL_QUESTIONS),
        }
    )


@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json(force=True) or {}
    correct = bool(data.get("correct", False))
    actual_word = (data.get("actual_word") or "").strip().lower()
    predicted = (data.get("predicted") or "").strip().lower()

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "correct": correct,
        "predicted": predicted if predicted else None,
        "actual_word": actual_word if actual_word else None,
        "answers": session.get("answers", {}),
        "asked": session.get("asked", []),
    }

    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    msg = "Merci ! Votre feedback aide l'IA à s'améliorer."
    if (not correct) and actual_word:
        msg = f"Merci ! Je vais me souvenir de « {actual_word} » pour devenir plus précis."

    return jsonify({"success": True, "message": msg})


@app.route("/debug/state")
def debug_state():
    path = WORDS_JSON_PATH
    p = (BASE_DIR / path).resolve()
    exists = p.exists()
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat() if exists else None
    size = p.stat().st_size if exists else None

    return jsonify(
        {
            "words_json_path_env": os.getenv("WORDS_JSON_PATH"),
            "words_json_path_used": str(p),
            "words_json_exists": exists,
            "words_json_mtime_utc": mtime,
            "words_json_size_bytes": size,
            "num_words_loaded": len(WORDS_DATABASE),
            "num_attrs_known": len(ATTR_SPECS),
            "num_obj_subtypes": len(OBJECT_SUBTYPES),
            "num_lieu_subtypes": len(LIEU_SUBTYPES),
            "num_families": len(FAMILIES),
            "question_pool_size": len(QUESTION_POOL),
        }
    )


@app.route("/debug/attr/<attr>")
def debug_attr(attr: str):
    attr = attr.strip()
    if attr not in ATTR_SPECS:
        return jsonify({"ok": False, "error": "attr inconnu"}), 404

    present = 0
    nonzero = 0
    samples = []
    for w, attrs in WORDS_DATABASE.items():
        if attr in attrs:
            present += 1
            if attrs.get(attr, 0) > 0:
                nonzero += 1
            if len(samples) < 10:
                samples.append({"word": w, "value": attrs.get(attr)})

    return jsonify(
        {
            "ok": True,
            "attr": attr,
            "present_count": present,
            "nonzero_count": nonzero,
            "present_ratio": present / max(1, len(WORDS_DATABASE)),
            "samples": samples,
        }
    )


@app.route("/debug/rank")
def debug_rank():
    answers = session.get("answers", {})
    apply_inferences(answers)

    candidates = list(WORDS_DATABASE.keys())
    ranked = rank_candidates(answers, candidates)[:25]

    return jsonify(
        {
            "answers": answers,
            "top25": [{"word": w, "score": s, "attrs": WORDS_DATABASE.get(w, {})} for w, s in ranked],
        }
    )


@app.route("/debug/next")
def debug_next():
    answers = session.get("answers", {})
    apply_inferences(answers)
    asked = set(session.get("asked", []))

    candidates = list(WORDS_DATABASE.keys())
    ranked = rank_candidates(answers, candidates)
    focus = [w for w, _ in ranked[:60]]

    q = choose_next_question(answers, asked, focus, last_was_unknown=False)
    return jsonify({"answers": answers, "asked": sorted(list(asked)), "suggested_next": q})


if __name__ == "__main__":
    # Détecte si on est sur Render
    is_production = os.getenv("RENDER") is not None
    
    port = int(os.getenv("PORT", "5000"))
    host = "0.0.0.0" if is_production else "127.0.0.1"
    debug = False if is_production else True
    
    app.run(debug=debug, host=host, port=port)
