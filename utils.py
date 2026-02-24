"""
Gedeelde hulpfuncties voor WaxTagger.
"""

import re
from difflib import SequenceMatcher

# Herkent remix/edit-markers in een titel: "(The Magician Remix)", "(Henrik Schwarz Edit)" etc.
_REMIX_MARKER_RE = re.compile(
    r'[\(\[](.*?(?:remix|edit|mix|re-edit|rework|bootleg|flip|version).*?)[\)\]]',
    re.IGNORECASE,
)


def artist_match(query: str, result: str, threshold: float = 0.5) -> bool:
    """
    Geeft True als de artiestsnaam in het zoekresultaat voldoende overeenkomt
    met de zoekquery.

    Logica (van lax naar strikt):
    1. Substring-check na normalisatie — vangt afkortingen en prefixen:
       "Krust" ↔ "DJ Krust", "Orbital" ↔ "Orbital, Penelope Isles"
    2. Token-overlap — vangt gedeelde woorden bij langere namen
    3. SequenceMatcher-ratio als laatste toets

    Drempelwaarde: 0.5 (aanpasbaar per aanroep).
    """
    def normalize(s: str) -> str:
        return re.sub(r'[^\w\s]', '', s.lower()).strip()

    a, b = normalize(query), normalize(result)
    if not a or not b:
        return True  # geen data om op te toetsen, laat door

    # 1. Substring
    if a in b or b in a:
        return True

    # 2. Token-overlap: deel van de woorden matcht
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if tokens_a & tokens_b:  # minstens één gedeeld woord
        return True

    # 3. Teken-voor-teken overeenkomst
    return SequenceMatcher(None, a, b).ratio() >= threshold


def title_match(query: str, result: str) -> bool:
    """
    Geeft True als de Discogs-releasetitel compatibel is met de zoekopdrachttitel.

    Kernregel: als de query een remix/edit-marker bevat (bijv. "(The Magician Remix)"),
    moet de result dat ook hebben. Zo wordt voorkomen dat de vroegste-persing-lookup
    een originele track teruggeeft terwijl er naar een specifieke remix gezocht werd.
    """
    query_has_remix = bool(_REMIX_MARKER_RE.search(query))
    result_has_remix = bool(_REMIX_MARKER_RE.search(result))

    if query_has_remix and not result_has_remix:
        return False

    # Vergelijk basistitel (zonder haakjesblokken)
    def base(s: str) -> str:
        return re.sub(r'[\(\[].*?[\)\]]', '', s).lower().strip()

    bq, br = base(query), base(result)
    if not bq or not br:
        return True

    return bq in br or br in bq or SequenceMatcher(None, bq, br).ratio() >= 0.6
