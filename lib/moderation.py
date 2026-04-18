"""
Profanity filter — Hungarian bad words auto-censored with asterisks.
Original text stays in DB; censoring happens at display time via Jinja2 filter.

has_profanity() / find_profanity() a POST flow-ban blokkol (server-side)
és a /api/check-text endpointon keresztül real-time figyelmeztetésre.

A regex \b...\b BOTH-sided word boundary-t használ → a "faszállító",
"szarvas", "retek" stb. NEM false positive. A magyar ragozás miatt
a leggyakoribb toldalékos alakokat külön fel kell venni.
"""

import re

# ============================================================
# Magyar trágár / sértő szavak
# ============================================================
# Kihagyva szándékosan (legitim / medikai / etnikai):
#   cigány, leszbikus, pénisz, nimfomániás, kuki, fütyi, nuna,
#   punci (és ragozott formái), maszturbáció-szármázékok.
# Ezek közül egyes szavak a megfelelő kontextusban sértők lehetnek,
# de a platform nyilvános bejelentéseire túl magas a false-positive
# kockázat.
_BADWORDS = [
    # ───────── kurva ─────────
    "kurva", "kurvák", "kurvát", "kurvára", "kurvának", "kurvaanyád",
    "kúrva", "kurvája", "kurvaanyjú", "kurvapecér",
    "szuperkurva", "szűzkurva", "házikurva",

    # ───────── fasz (alap + ragozás) ─────────
    "fasz", "faszom", "faszod", "faszát", "faszt", "faszba", "faszába",
    "faszság", "faszomba", "faszomat", "faszán", "faszának",
    "faszunk", "faszatok", "faszukat", "faszok", "faszokat",

    # ───────── fasz-os összetett sértések ─────────
    "agyfasz", "aprófaszú", "aszaltfaszú", "balfasz", "baromfifasz",
    "cérnafaszú", "csibefasz", "csirkefaszú", "csupaszfarkú",
    "deformáltfaszú", "duplafaszú", "ebfasz",
    "faszagyú", "faszarc", "faszemulátor", "faszfej", "faszfészek",
    "faszkalap", "faszkarika", "faszkedvelő", "faszkópé", "faszogány",
    "faszpörgettyű", "faszsapka", "faszszagú", "faszszopó", "fasszopó",
    "fasztalan", "fasztarisznya", "fasztengely", "fasztolvaj",
    "faszváladék", "faszverő",
    "fütyinyalogató", "görbefaszú", "íveltfaszú", "ionizáltfaszú",
    "kétfaszú", "kojakfaszú", "kopárfaszú", "kunkorítottfaszú",
    "lankadtfaszú", "lóhugy", "lófasz", "lyukasfaszú",
    "mesterségesfaszú", "műfaszú", "multifasz", "nyalábfasz",
    "peremesfaszú", "puhafaszú", "rágcsáltfaszú", "rőfösfasz",
    "szálkafaszú", "szarfaszú", "szopottfarkú", "szúnyogfaszni",
    "szúnyogfasznyi", "törpefaszú", "tyúkfasznyi", "vadfasz",
    "zsugorítottfaszú",

    # ───────── basz + bazmeg (alap + ragozás) ─────────
    "basz", "baszd", "baszod", "baszol", "baszom", "baszok", "baszik",
    "baszunk", "basztok", "basznak", "baszni", "baszódj", "baszódjon",
    "baszott", "basztam", "basztál", "basztunk", "basztatok", "basztak",
    "bassz", "basszon", "basszatok", "basszák", "basszus", "basszál",
    "bassza", "basszá", "bazd", "bazdmeg", "bazmeg", "bazzeg", "bazmegaz",

    # ───────── basz-os összetett ─────────
    "átbaszott", "baszhatatlan", "basznivaló", "bebaszott",
    "búvalbaszott", "elbaszott", "félrebaszott", "hátbabaszott",
    "kecskebaszó", "kibaszott", "lebaszirgált", "lebaszott",
    "megkúrt", "megkettyintett", "megszopatott", "összebaszott",
    "toszatlan", "toszott",

    # ───────── geci / genny ─────────
    "geci", "gecis", "geciző", "gecit", "gecik",
    "gecinyelő", "geciszaró", "geciszívó", "genyac", "genyó",
    "genny", "gennyes", "gennyesszájú", "gennygóc",

    # ───────── szar (alap + ragozás) ─────────
    "szar", "szart", "szarnak", "szaros", "szarházi", "szarok",
    "szarjon", "szarom",

    # ───────── szar-os összetett ─────────
    "csipszar", "csöppszar", "középszar", "kutyaszar", "nyúlszar",
    "tikszar", "tyúkszar", "szaralak", "szárazfing", "szarbojler",
    "szarcsimbók", "szarevő", "szarjankó", "szarnivaló",
    "szarosvalagú", "szarrágó", "szarszagú", "szarszájú",
    "szartragacs", "szarzsák",

    # ───────── obfuszkált szar / qu-s variánsok ─────────
    "xar", "qtyaszar", "qrva", "qki",

    # ───────── fos / fing ─────────
    "fos", "foskemence", "fospisztoly", "fospumpa", "fostalicska",
    "befosi", "szófosó",
    "fing", "fölfingott", "félrefingott", "gyíkfing", "lepkefing",
    "porbafingó",

    # ───────── picsa / pina ─────────
    "picsa", "picsát", "picsába", "picsája", "picsán", "picsájába",
    "pina", "pinát", "pinád", "pinába", "pinája",
    "békapicsa", "kutyapina", "picsafej", "picsameresztő",
    "picsánnyalt", "picsánrugott", "picsányi",
    "szűzpicsa", "rojtospicsájú",

    # ───────── pöcs ─────────
    "pöcs", "pöcsöm", "pöcsös", "pöcsfej",

    # ───────── segg ─────────
    "segg", "segged", "seggem", "seggfej", "segge", "seggbe",
    "seggét", "seggében", "seggemet", "seggedet", "seggükbe",
    "dobseggű", "dunyhavalagú", "mamutsegg", "seggarc",
    "seggdugó", "seggnyaló", "seggszőr", "seggtorlasz",

    # ───────── buzi / strici / kurva-szinonimák ─────────
    "buzi", "buzis", "buzizik", "buzeráns", "buzernyák",
    "buzikurva", "szuperbuzi",
    "ribanc", "ringyó", "lotyó", "riherongy",
    "strici", "hiperstrici", "hímringyó", "hímnőstény",
    "kurafi", "kurafik", "kurafikat", "kurafit",
    "szajha", "szajhák", "szajhákat", "szajhát",

    # ───────── szop ─────────
    "szopd", "szopjál", "szopj", "szopjatok", "szopós", "szopja",
    "szopógép", "szopógörcs", "ondónyelő",

    # ───────── köcsög / pejoratív ─────────
    "köcsög", "köcsögök",
    "dögölj", "dögöljön", "megdöglik",
    "rohadt", "rohadj", "rohadék",
    "mocsok", "mocskos",
    "csicska", "csicskás", "szégyencsicska",
    "retkes",
    "suttyó", "sutyerák", "ordenálé",
    "cafat", "cafka", "céda",
    "brunya", "csöcs", "csöcsfej", "lógócsöcsű",
    "kula", "lőcs",

    # ───────── agyi / butasági sértések ─────────
    "aberált", "aberrált", "agyalágyult", "agyatlan", "agybatetovált",
    "agyhalott", "agyrákos", "antibarom", "abortuszmaradék",
    "agyonkúrt", "arcbarakott", "cottonfej",
    "hígagyú", "hugyagyú", "kretén",
    "hüje", "hüle", "hülye", "hülyécske", "hülyegyerek",
    "mikrotökű", "tompatökű",

    # ───────── betegség / test alapú sértések ─────────
    "aidses", "hererákos", "szifiliszes", "lemenstruált",
    "hájpacni", "nikotinpatkány", "végbélféreg",

    # ───────── gyűlöletbeszéd / rasszista / szélsőséges ─────────
    "feka", "náci", "hitlerista",

    # ───────── pisi / hugy ─────────
    "pisa", "pisaszagú", "pisis", "ágybavizelős",
    "hugyos", "hugytócsa",

    # ───────── egyéb trágár ─────────
    "leokádott", "leprafészek", "leszart", "lucskos", "lugnya",
    "lyukasbelű", "megfingatott", "muff",
    "pudvás", "pudváslikú",
    "valag", "valagváladék",
    "szűklyukú",

    # ───────── fokozó alakok (LDNOOBW) ─────────
    "leggecibb", "legszarabb", "legkibaszottabb",
]

# Mindkét oldali word boundary — pontos szó match.
# re.IGNORECASE miatt a nagy- és kisbetűs variánsokat is kezeli.
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
