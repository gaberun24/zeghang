"""
Profanity filter — Hungarian bad words auto-censored with asterisks.
Original text stays in DB; censoring happens at display time via Jinja2 filter.
"""

import re

# Hungarian profanity list — common swear words + frequent inflected forms.
# A regex most már BOTH-sided word boundary-t használ (\b...\b), ezért
# toldalékos alakokat külön fel kell venni. Cserébe nincs false positive
# olyan szavaknál mint "faszállító kamion", "szarvas", "retek" stb.
_BADWORDS = [
    # kurva és ragozott alakok
    "kurva", "kurvák", "kurvát", "kurvára", "kurvának", "kurvaanyád", "kúrva", "kurvája",
    # fasz és ragozott alakok
    "fasz", "faszom", "faszod", "faszát", "faszt", "faszba", "faszába",
    "faszság", "faszomba", "faszomat", "faszfej", "faszkalap",
    "faszok", "faszokat", "faszán", "faszának", "faszunk", "faszatok",
    "faszukat",
    # geci
    "geci", "gecis", "geciző", "gecit", "gecik",
    # basz + bazmeg (jelen / múlt / felszólító / főnévi igenév)
    "basz", "baszd", "baszod", "baszol", "baszom", "baszok", "baszik",
    "baszunk", "basztok", "basznak", "baszni", "baszódj", "baszódjon",
    "baszott", "basztam", "basztál", "basztunk", "basztatok", "basztak",
    "bassz", "basszon", "basszatok", "basszák", "basszus", "basszál",
    "bassza", "basszá", "bazd", "bazdmeg", "bazmeg", "bazmegaz",
    # anyád
    "anyád", "anyádat", "anyámat", "anyádba",
    # szar és ragozott alakok
    "szar", "szart", "szarnak", "szaros", "szarházi", "szarok", "szarjon", "szarom",
    # picsa / pina
    "picsa", "picsát", "picsába", "picsája", "picsán", "picsájába",
    "pina", "pinát", "pinád", "pinába", "pinája",
    # segg
    "segg", "segged", "seggem", "seggfej", "segge", "seggbe",
    "seggét", "seggében", "seggemet", "seggedet", "seggükbe",
    # egyéb sértések / trágárságok
    "buzi", "buzis",
    "ribanc", "ringyó", "lotyó",
    "köcsög", "köcsögök",
    "szopd", "szopjál", "szopj", "szopjatok", "szopós", "szopja",
    "dögölj", "dögöljön",
    "rohadt", "rohadj", "rohadék",
    "mocsok", "mocskos",
    "csicska", "csicskás",
    "retkes",  # a sima "retek" (zöldség) kivéve a false positive miatt
    "pöcs", "pöcsöm", "pöcsös",
]

# Mindkét oldali word boundary — "faszállító" már NEM match-el, csak pontos szó.
_pattern = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in sorted(_BADWORDS, key=len, reverse=True)) + r')\b',
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


def has_profanity(text):
    """True, ha a szöveg legalább egy magyar trágár kifejezést tartalmaz."""
    if not text:
        return False
    return bool(_pattern.search(text))


def find_profanity(text):
    """A szövegben szereplő trágár szavak listája (kisbetűs, duplikátumok nélkül)."""
    if not text:
        return []
    return sorted({m.group(0).lower() for m in _pattern.finditer(text)})
