"""The SecretNames word deck.

A board is 25 distinct words drawn from this list. It is the classic Codenames
word family — concrete, polysemous nouns that carry several unrelated senses,
because a clue is only interesting when a word can be reached from more than one
direction (BANK, SPRING, MOLE, PITCH, CRANE are the shape of the whole deck).

MULTI-WORD ENTRIES ARE DELIBERATE and are why the deck is a list of strings
rather than a set of identifiers: "ICE CREAM" and "NEW YORK" are single cards on
the physical board. The board renderer wraps them; nothing downstream splits on
whitespace.

IT IS DATA, NOT RULES. Swapping the deck (a themed pack, a shorter list for
children) needs no engine change: :func:`deal_words` is the only reader and it
only requires ``len(WORDS) >= BOARD_SIZE`` and no duplicates, both asserted at
import so a bad edit fails at boot rather than at the first deal.
"""
from __future__ import annotations

BOARD_SIZE = 25

WORDS: tuple[str, ...] = (
    "AFRICA", "AGENT", "AIR", "ALIEN", "ALPS", "AMAZON", "AMBULANCE", "AMERICA",
    "ANGEL", "ANTARCTICA", "APPLE", "ARM", "ATLANTIS", "AUSTRALIA", "AZTEC",
    "BACK", "BALL", "BAND", "BANK", "BAR", "BARK", "BAT", "BATTERY", "BEACH",
    "BEAR", "BEAT", "BED", "BEIJING", "BELL", "BELT", "BERLIN", "BERMUDA",
    "BERRY", "BILL", "BLOCK", "BOARD", "BOLT", "BOMB", "BOND", "BOOM", "BOOT",
    "BOTTLE", "BOW", "BOX", "BRIDGE", "BRUSH", "BUCK", "BUFFALO", "BUG",
    "BUGLE", "BUTTON", "CALF", "CANADA", "CAP", "CAPITAL", "CAR", "CARD",
    "CARROT", "CASINO", "CAST", "CAT", "CELL", "CENTAUR", "CENTER", "CHAIR",
    "CHANGE", "CHARGE", "CHECK", "CHEST", "CHICK", "CHINA", "CHOCOLATE",
    "CHURCH", "CIRCLE", "CLIFF", "CLOAK", "CLUB", "CODE", "COLD", "COMIC",
    "COMPOUND", "CONCERT", "CONDUCTOR", "CONTRACT", "COOK", "COPPER", "COTTON",
    "COURT", "COVER", "CRANE", "CRASH", "CRICKET", "CROSS", "CROWN", "CYCLE",
    "CZECH", "DANCE", "DATE", "DAY", "DEATH", "DECK", "DEGREE", "DIAMOND",
    "DICE", "DINOSAUR", "DISEASE", "DOCTOR", "DOG", "DRAFT", "DRAGON", "DRESS",
    "DRILL", "DROP", "DUCK", "DWARF", "EAGLE", "EGYPT", "EMBASSY", "ENGINE",
    "ENGLAND", "EUROPE", "EYE", "FACE", "FAIR", "FALL", "FAN", "FENCE",
    "FIELD", "FIGHTER", "FIGURE", "FILE", "FILM", "FIRE", "FISH", "FLUTE",
    "FLY", "FOOT", "FORCE", "FOREST", "FORK", "FRANCE", "GAME", "GAS",
    "GENIUS", "GERMANY", "GHOST", "GIANT", "GLASS", "GLOVE", "GOLD", "GRACE",
    "GRASS", "GREECE", "GREEN", "GROUND", "HAM", "HAND", "HAWK", "HEAD",
    "HEART", "HELICOPTER", "HIMALAYAS", "HOLE", "HOLLYWOOD", "HONEY", "HOOD",
    "HOOK", "HORN", "HORSE", "HORSESHOE", "HOSPITAL", "HOTEL", "ICE",
    "ICE CREAM", "INDIA", "IRON", "IVORY", "JACK", "JAM", "JET", "JUPITER",
    "KANGAROO", "KETCHUP", "KID", "KING", "KIWI", "KNIFE", "KNIGHT", "LAB",
    "LAP", "LASER", "LAWYER", "LEAD", "LEMON", "LEPRECHAUN", "LIFE", "LIGHT",
    "LIMOUSINE", "LINE", "LINK", "LION", "LITTER", "LOCH NESS", "LOCK", "LOG",
    "LONDON", "LUCK", "MAIL", "MAMMOTH", "MAPLE", "MARBLE", "MARCH", "MASS",
    "MATCH", "MERCURY", "MEXICO", "MICROSCOPE", "MILLIONAIRE", "MINE", "MINT",
    "MISSILE", "MODEL", "MOLE", "MOON", "MOSCOW", "MOUNT", "MOUSE", "MOUTH",
    "MUG", "NAIL", "NEEDLE", "NET", "NEW YORK", "NIGHT", "NINJA", "NOTE",
    "NOVEL", "NURSE", "NUT", "OCTOPUS", "OIL", "OLIVE", "OLYMPUS", "OPERA",
    "ORANGE", "ORGAN", "PALM", "PAN", "PANTS", "PAPER", "PARACHUTE", "PARK",
    "PART", "PASS", "PASTE", "PENGUIN", "PHOENIX", "PIANO", "PIE", "PILOT",
    "PIN", "PIPE", "PIRATE", "PISTOL", "PIT", "PITCH", "PLANE", "PLASTIC",
    "PLATE", "PLATYPUS", "PLAY", "PLOT", "POINT", "POISON", "POLE", "POLICE",
    "POOL", "PORT", "POST", "POUND", "PRESS", "PRINCESS", "PUMPKIN", "PUPIL",
    "PYRAMID", "QUEEN", "RABBIT", "RACKET", "RAY", "REVOLUTION", "RING",
    "ROBIN", "ROBOT", "ROCK", "ROME", "ROOT", "ROSE", "ROULETTE", "ROUND",
    "ROW", "RULER", "SATELLITE", "SATURN", "SCALE", "SCHOOL", "SCIENTIST",
    "SCORPION", "SCREEN", "SCUBA DIVER", "SEAL", "SERVER", "SHADOW",
    "SHAKESPEARE", "SHARK", "SHIP", "SHOE", "SHOP", "SHOT", "SINK",
    "SKYSCRAPER", "SLIP", "SLUG", "SMUGGLER", "SNOW", "SNOWMAN", "SOCK",
    "SOLDIER", "SOUL", "SOUND", "SPACE", "SPELL", "SPIDER", "SPIKE", "SPINE",
    "SPOT", "SPRING", "SPY", "SQUARE", "STADIUM", "STAFF", "STAR", "STATE",
    "STICK", "STOCK", "STRAW", "STREAM", "STRIKE", "STRING", "SUB", "SUIT",
    "SUPERHERO", "SWING", "SWITCH", "TABLE", "TABLET", "TAG", "TAIL", "TAP",
    "TEACHER", "TELESCOPE", "TEMPLE", "THEATER", "THIEF", "THUMB", "TICK",
    "TIE", "TIME", "TOKYO", "TOOTH", "TORCH", "TOWER", "TRACK", "TRAIN",
    "TRIANGLE", "TRIP", "TRUNK", "TUBE", "TURKEY", "UNDERTAKER", "UNICORN",
    "VACUUM", "VAN", "VET", "WAKE", "WALL", "WAR", "WASHER", "WASHINGTON",
    "WATCH", "WATER", "WAVE", "WEB", "WELL", "WHALE", "WHIP", "WIND", "WITCH",
    "WORM", "YARD",
)

# Boot-time, not test-time: a duplicated word deals a board with two identical
# cards and two different key roles, which is unplayable and would otherwise
# surface as a confused player rather than as an error.
assert len(set(WORDS)) == len(WORDS), "the word deck contains duplicates"
assert len(WORDS) >= BOARD_SIZE, "the word deck is smaller than a board"


def deal_words(rng) -> list[str]:
    """25 distinct words in board order (position 0 = row 0, column 0)."""
    return rng.sample(list(WORDS), BOARD_SIZE)
