"""
Profanity filter — Hungarian bad words auto-censored with asterisks.
Original text stays in DB; censoring happens at display time via Jinja2 filter.
"""

import re

# Hungarian profanity list — common swear words and variations
_BADWORDS = [
    "kurva", "kurv", "kúrva", "kurvá",
    "fasz", "faszom", "faszát", "faszt", "faszba",
    "geci", "gecis", "geciző",
    "baszd", "baszom", "basszus", "basszál", "bassza", "basszá", "bazd", "bazdmeg", "bazmeg",
    "anyád", "anyádat", "anyámat",
    "szar", "szaros", "szarházi",
    "picsa", "picsá", "picsa", "pina", "piná",
    "segg", "seggfej", "segge",
    "buzi", "buzis",
    "ribanc", "ringyó", "lotyó",
    "köcsög", "köcsögök",
    "paraszt",
    "szopd", "szopjál", "szopj",
    "dögölj", "dögöljön",
    "rohadt", "rohadj", "rohadék",
    "mocsok", "mocskos",
    "csicska", "csicskás",
    "retkes", "retek",
    "tetves",
    "bunkó",
    "pöcs",
]

# Build regex pattern — case insensitive, word boundary aware
_pattern = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in sorted(_BADWORDS, key=len, reverse=True)) + r')',
    re.IGNORECASE
)


def censor_text(text):
    """Replace bad words with asterisks, keeping first letter visible."""
    if not text:
        return text

    def _replace(match):
        word = match.group(0)
        if len(word) <= 1:
            return word
        return word[0] + '*' * (len(word) - 1)

    return _pattern.sub(_replace, text)
