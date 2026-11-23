"""
Roe - better Hindi understanding (words and numbers Whisper writes in Devanagari).

What it does
  1. WORDS      : many more Devanagari spellings of the words Roe needs (open, video, message, first, second ...),
                  shared by actions.py and phone_control.py, so "दूसरा वीडियो चलाओ" is understood like "second video".
  2. fix(text)  : if Whisper spells a command word a little wrong (खोलू, बजाव, चालु ...), it is corrected to the
                  closest real command word. Names and songs are left alone (only close matches to command words change).
  3. PROMPT     : a Hindi hint for Whisper (initial prompt) so it expects Devanagari command words.

Add your own words to WORDS or COMMAND_WORDS.
"""
import difflib
import re

# Devanagari spelling -> the word the program understands
WORDS = {
    # opening / closing / doing
    "ओपन": "open", "क्लोज": "close", "स्टार्ट": "start", "स्टॉप": "stop", "प्ले": "play", "पॉज़": "pause", "पॉज": "pause",
    "खोलिए": "kholo", "खोलिये": "kholo", "खोल दो": "kholo", "खोलना": "kholo", "चला दो": "chalao", "चलाइए": "chalao",
    "चलाना": "chalao", "बजा दो": "bajao", "बजाइए": "bajao", "बंद कर दो": "band karo", "बंद करना": "band karo",
    "बन्द": "band", "चालू करो": "chalu karo", "शुरू करो": "chalu karo", "शुरू": "chalu",
    "बढ़ाओ": "badhao", "बढाओ": "badhao", "घटाओ": "ghatao", "कम करो": "kam karo", "ज्यादा": "zyada", "ज़्यादा": "zyada",
    "भेजो": "bhejo", "भेज दो": "bhej do", "दिखाओ": "dikhao", "रोको": "ruko", "रुको": "ruko", "सुनाओ": "sunao",
    # things
    "वीडियो": "video", "विडियो": "video", "वीडिओ": "video", "फाइल": "file", "फ़ाइल": "file", "फोल्डर": "folder",
    "फ़ोल्डर": "folder", "मैसेज": "message", "मेसेज": "message", "संदेश": "message", "एसएमएस": "sms", "एस एम एस": "sms",
    "व्हाट्सएप": "whatsapp", "व्हाट्सऐप": "whatsapp", "वॉट्सएप": "whatsapp", "यूट्यूब": "youtube", "यू ट्यूब": "youtube",
    "फोन": "phone", "फ़ोन": "phone", "मोबाइल": "phone", "कंट्रोल": "control", "कॉल": "call", "फोटो": "photo",
    "तस्वीर": "photo", "फ़ोटो": "photo", "स्क्रीनशॉट": "screenshot", "स्क्रीन शॉट": "screenshot", "स्क्रीन": "screen",
    "इमेज": "images", "इमेजेस": "images", "इमेजेज": "images", "तस्वीरें": "images", "ऑडियो": "audio", "म्यूजिक": "music",
    "म्यूज़िक": "music", "सॉन्ग": "song", "गाना": "gaana", "गाने": "gaana", "डाउनलोड्स": "downloads", "डाउनलोड": "downloads",
    "डॉक्यूमेंट": "documents", "डॉक्यूमेंट्स": "documents", "फाइल्स": "files", "फ़ाइल्स": "files", "ऐप": "app", "एप": "app",
    "एप्लिकेशन": "app", "नोटिफिकेशन": "notification", "ब्राइटनेस": "brightness", "वॉल्यूम": "volume", "आवाज़": "volume",
    "आवाज": "volume", "बैटरी": "battery", "ब्लूटूथ": "bluetooth", "वाईफाई": "wifi", "वाई फाई": "wifi", "वाई-फाई": "wifi",
    "टॉर्च": "torch", "कैमरा": "camera", "सेटिंग्स": "settings", "सर्च": "search", "टाइप": "type", "क्लिक": "click",
    # numbers / order
    "पहला": "pehla", "पहली": "pehli", "पहले": "pehla", "दूसरा": "doosra", "दूसरी": "doosri", "दूसरे": "doosra",
    "तीसरा": "teesra", "तीसरी": "teesri", "तीसरे": "teesra", "चौथा": "chautha", "चौथी": "chauthi", "चौथे": "chautha",
    "पांचवा": "paanchva", "पाँचवा": "paanchva", "पांचवां": "paanchva", "आखिरी": "last", "आख़िरी": "last", "अंतिम": "last",
    "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5", "छह": "6", "छः": "6", "सात": "7", "आठ": "8",
    "नौ": "9", "दस": "10",
    # directions
    "नीचे": "neeche", "ऊपर": "upar", "वापस": "wapas", "पीछे": "peeche", "आगे": "aage",
}

# Words Roe expects (used to repair small spelling mistakes). Plain Devanagari.
COMMAND_WORDS = ["खोलो", "खोलिए", "बंद", "करो", "चालू", "चलाओ", "बजाओ", "बढ़ाओ", "घटाओ", "कम", "भेजो", "दिखाओ", "रोको",
                 "पहला", "दूसरा", "तीसरा", "चौथा", "आखिरी", "वीडियो", "गाना", "फोटो", "मैसेज", "फोन", "मोबाइल", "स्क्रीन",
                 "नीचे", "ऊपर", "वापस", "व्हाट्सएप", "यूट्यूब", "कैमरा", "वॉल्यूम", "ब्राइटनेस", "ब्लूटूथ", "वाईफाई",
                 "फोल्डर", "फाइल", "इमेज", "स्क्रॉल", "कॉल", "बैटरी", "टॉर्च", "सेटिंग्स"]

PROMPT = ("समय क्या हुआ है, मौसम कैसा है, ब्राइटनेस बढ़ाओ, आवाज़ कम करो, विंडो मिनिमाइज़ करो, "
          "यूट्यूब खोलो, गाना बजाओ, फोन कंट्रोल")   # short on purpose: a long hint is slow and can be read back as gibberish

_DEV = re.compile(r"[\u0900-\u097F]+")
_known = set(COMMAND_WORDS) | {k for k in WORDS if " " not in k}


def fix(text):
    """Repairs near-miss spellings of command words in Hindi text. Other words stay as they are."""
    if not text or not _DEV.search(text):
        return text

    def one(m):
        w = m.group(0)
        if w in _known or len(w) < 4:
            return w
        # same first letter and a very similar spelling: a mis-spelt command word, not a name
        cands = [c for c in COMMAND_WORDS if c[0] == w[0]]
        close = difflib.get_close_matches(w, cands, n=1, cutoff=0.74)
        return close[0] if close else w
    return _DEV.sub(one, text)


def merge_into(table):
    """Adds the words above to another program's Devanagari table (never replaces what it already has)."""
    for k, v in WORDS.items():
        table.setdefault(k, v)


# =====================================================================================================
# BASIC HINDI: commands and everyday questions, understood INSTANTLY (no internet, no AI, no waiting)
#
#   "समय क्या हुआ है"  -> the time          "मौसम कैसा है"  -> the weather        "ब्राइटनेस बढ़ाओ" -> brightness up
#   "आवाज़ कम करो"     -> volume down       "विंडो मिनिमाइज़ करो" -> minimize      "नया टैब खोलो"   -> new tab
#   "तुम कैसी हो"      -> she answers in Hindi
#
# parse(text) returns a command (same format brain.py uses) or None. None = "not one of mine": the sentence then
# goes to the AI as before. Works with Devanagari AND Hindi written in English letters (kaise ho, mausam kaisa hai).
# Her reply is turned into Hindi at once by hindi_fast.py.
# =====================================================================================================
import random
import unicodedata

# ---------------- YOUR OWN SENTENCES (add yours here) ----------------
# Left side : what you say (Hindi or Hinglish, spelling does not need to be perfect: close matches work too)
# Right side: what she does. Either a ready action name from the list below, or ("reply", "what she says").
#   time, date, weather, weather_tomorrow, brightness_up, brightness_down, volume_up, volume_down, mute,
#   minimize, maximize, restore, show_desktop, new_tab, close_tab, next_tab, prev_tab, close_window,
#   scroll_up, scroll_down, top, bottom, screenshot, back, forward, refresh, pause, resume, next_song,
#   prev_song, lock, wifi_on, wifi_off, bluetooth_on, bluetooth_off
MY_SENTENCES = {
    # "टाइम बताओ": "time",
    # "बाहर का मौसम कैसा है": "weather",
    # "तुम्हारा नाम क्या है": ("reply", "मेरा नाम रो है।"),
}
# ----------------------------------------------------------------------

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_DIGITS_DEV = {ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")}
# short/long vowel spellings are treated as the same, so मिनिमाइज़ / मिनीमाइज / मिनिमाईज are one word
_FOLD = str.maketrans({"ी": "ि", "ू": "ु", "ै": "े", "ौ": "ो", "ॉ": "ो", "ँ": "ं", "ॅ": "े", "ः": "",
                       "ई": "इ", "ऊ": "उ", "ऐ": "ए", "औ": "ओ", "ऑ": "ओ", "ऍ": "ए"})


def _n(text):
    """Text -> a plain form that is easy to compare (no nukta dots, folded vowels, no punctuation, lower case)."""
    t = unicodedata.normalize("NFD", text or "").replace("\u093c", "")
    t = t.translate(_ZERO_WIDTH).translate(_DIGITS_DEV).translate(_FOLD).lower()
    t = re.sub(r"[^\w\u0900-\u097F\s]", " ", t.replace("।", " "))
    return re.sub(r"\s+", " ", t).strip()


def _set(words):
    return {_n(w) for w in words.split() if _n(w)}


def _has(toks, words):
    return any(t in words for t in toks)


# words that were written as two (or hyphenated) words are joined first
_JOIN = [(_n(a), _n(b)) for a, b in (
    ("वाई फाई", "वाईफाई"), ("वाई-फाई", "वाईफाई"), ("वाय फाय", "वाईफाई"), ("वाइ फाइ", "वाईफाई"), ("wi fi", "wifi"),
    ("ब्लू टूथ", "ब्लूटूथ"), ("blue tooth", "bluetooth"), ("स्क्रीन शॉट", "स्क्रीनशॉट"), ("screen shot", "screenshot"),
    ("फुल स्क्रीन", "फुलस्क्रीन"), ("full screen", "fullscreen"), ("न्यू टैब", "नया टैब"), ("new tab", "नया टैब"),
    ("वॉल्यूम", "वॉल्यूम"), ("फाइल एक्सप्लोरर", "एक्सप्लोरर"), ("file explorer", "एक्सप्लोरर"),
    ("पावर पॉइंट", "पावरपॉइंट"), ("पावर प्वाइंट", "पावरपॉइंट"), ("एम एस वर्ड", "वर्ड"), ("एम एस एक्सेल", "एक्सेल"),
    ("कौन सा", "कौनसा"), ("कौन सी", "कौनसा"), ("कौन से", "कौनसा"))]


# ---------------- the words ----------------
UP = _set("बढ़ाओ बढ़ा बढ़ाइए बढ़ाइये बढ़ाएं बढ़ाना बढ़ाया बढाओ ज्यादा ज़्यादा अधिक तेज़ तेज ऊपर "
          "up increase raise higher more louder brighter badhao badha badhaao badhao zyada jyada tez ooper upar")
DOWN = _set("घटाओ घटा घटाइए घटाइये घटाएं घटाना कम धीमा धीमी धीरे हल्का हल्की नीचे डिम "
            "down decrease lower less reduce dim dimmer softer quieter ghatao ghata kam dheere halka neeche low")
ASK = _set("क्या कितने कितना कितनी बताओ बताइए बताइये बता बताना कौन कौनसा है हैं हुआ हुए गए गया अभी कैसा कैसी कैसे "
           "what kya kitne kitna batao bataiye abhi kaisa kaisi hai")
FILLER = _set("करो कर दो दीजिए कीजिए कीजिये कर दीजिए प्लीज़ प्लीज please जरा ज़रा थोड़ा थोड़ी थोड़े अभी फिर से को का की के "
              "ये यह वह वो इसे उसे मेरा मेरी मेरे अपना अपनी अपने हाँ हां जी और ओके okay ok बस ही भी तो न "
              "karo kar do karna zara thoda ko ka ki ke ye yeh")
SONG = _set("गाना गाने गाना संगीत म्यूजिक म्यूज़िक सॉन्ग सोंग गीत song music gaana gana gaane")
PLAY = _set("चलाओ चला बजाओ बजा चालू शुरू स्टार्ट प्ले चलाइए बजाइए लगाओ लगा play start chalao bajao chalu shuru lagao")
STOPW = _set("रोको रुको रोक रोकिए रोकिये पॉज़ पॉज बंद बन्द स्टॉप रुकिए pause stop band ruko roko")
NEXTW = _set("अगला अगले अगली नेक्स्ट बदलो बदल स्किप next skip agla agle badlo")
PREVW = _set("पिछला पिछले पिछली प्रीवियस previous pichla pichle")
ON = _set("चालू चालु ऑन ओन शुरू खोलो एक्टिवेट इनेबल on chalu enable activate")
OFF = _set("बंद बन्द ऑफ ओफ ऑफ़ डिसेबल off band disable बंध")
OPENW = _set("खोलो खोल खोलिए खोलिये ओपन open kholo khol")

TIME_W = _set("समय टाइम बजे बज घड़ी time samay baje")
DATE_W = _set("तारीख तारिख तिथि दिनांक डेट date tarikh tareekh")
DAY_W = _set("दिन वार din")
WEATHER_W = _set("मौसम वेदर बारिश बरसात गर्मी ठंड ठण्ड सर्दी तापमान टेम्परेचर टेंपरेचर तापमान धूप छाता बादल उमस "
                 "mausam weather temperature barish baarish garmi thand")
BRIGHT_W = _set("ब्राइटनेस ब्राइट रोशनी चमक brightness bright brighter dimmer")
VOLUME_W = _set("वॉल्यूम वोल्यूम वाल्यूम आवाज साउंड volume awaz awaaz aawaz sound")
MUTE_W = _set("म्यूट अनम्यूट चुप mute unmute")
MIN_W = _set("मिनिमाइज मिनिमाईज मिनीमाइज़ छोटा छोटी छोटे minimize minimise chhota chota")
MAX_W = _set("मैक्सिमाइज मैक्सीमाइज मैक्सिमाईज बड़ा बड़ी बड़े फुलस्क्रीन maximize maximise fullscreen bada badi")
RESTORE_W = _set("रीस्टोर रिस्टोर restore")
WINDOW_W = _set("विंडो विन्डो खिड़की टैब टेब टैब्स window windows tab tabs स्क्रीन")
TAB_W = _set("टैब टेब टैब्स tab tabs")
CLOSE_W = _set("बंद बन्द क्लोज close band")
NEW_W = _set("नया नई नयी न्यू new naya nayi")
SCROLL_W = _set("स्क्रॉल स्क्रोल scroll")
LITTLE_W = _set("थोड़ा थोड़ी थोड़े जरा little thoda zara")
LOT_W = _set("बहुत ज्यादा काफी lot bahut")
DESK_W = _set("डेस्कटॉप डेस्कटाप desktop")
ALL_W = _set("सब सारे सारी सभी everything all")
SHOT_W = _set("स्क्रीनशॉट screenshot")
REFRESH_W = _set("रिफ्रेश रीफ्रेश रिलोड रीलोड refresh reload")
BACK_W = _set("बैक पीछे वापस back")
FWD_W = _set("फॉरवर्ड आगे forward")
GO_W = _set("जाओ जाइए जाइये चलो go")
WIFI_W = _set("वाईफाई वायफाय वायफाई वाईफाय वाइफाइ wifi")
BT_W = _set("ब्लूटूथ ब्लुटूथ bluetooth")
LOCK_W = _set("लॉक लाक lock")
LAPTOP_W = _set("लैपटॉप लैपटाप कंप्यूटर कम्प्यूटर पीसी laptop computer pc स्क्रीन")
TIMER_W = _set("टाइमर timer")
ALARM_W = _set("अलार्म रिमाइंडर याद alarm reminder yaad")
CANCEL_W = _set("रद्द कैंसल हटाओ cancel delete remove")
FULL_W = _set("फुल मैक्स मैक्सिमम पूरा पूरी सबसे full max maximum")
HALF_W = _set("आधा आधी half")
PCT_W = _set("प्रतिशत परसेंट फीसदी percent प्रसेंट")

_UNITS = {_n(k): v for k, v in {"सेकंड": 1, "सेकेंड": 1, "सेकण्ड": 1, "second": 1, "seconds": 1, "sec": 1,
                                  "मिनट": 60, "मिनिट": 60, "minute": 60, "minutes": 60, "min": 60,
                                  "घंटा": 3600, "घंटे": 3600, "घण्टा": 3600, "घंटों": 3600, "hour": 3600,
                                  "hours": 3600, "hr": 3600}.items()}

# Hindi number words 3-100 (1 and 2 are left out on purpose: "कर दो" means "please do", not 2)
_NUM_TABLE = [
    (3, "तीन"), (4, "चार"), (5, "पांच पाँच पाच"), (6, "छह छः छे"), (7, "सात"), (8, "आठ"), (9, "नौ"), (10, "दस"),
    (11, "ग्यारह"), (12, "बारह"), (13, "तेरह"), (14, "चौदह"), (15, "पंद्रह पन्द्रह पंद्रा"), (16, "सोलह"),
    (17, "सत्रह"), (18, "अठारह"), (19, "उन्नीस"), (20, "बीस"), (21, "इक्कीस"), (22, "बाईस"), (23, "तेईस"),
    (24, "चौबीस"), (25, "पच्चीस पचीस"), (26, "छब्बीस"), (27, "सत्ताईस"), (28, "अट्ठाईस अठाईस"), (29, "उनतीस"),
    (30, "तीस"), (31, "इकतीस"), (32, "बत्तीस"), (33, "तैंतीस"), (34, "चौंतीस"), (35, "पैंतीस"), (36, "छत्तीस"),
    (37, "सैंतीस"), (38, "अड़तीस"), (39, "उनतालीस"), (40, "चालीस"), (41, "इकतालीस"), (42, "बयालीस"),
    (43, "तैंतालीस"), (44, "चौवालीस"), (45, "पैंतालीस"), (46, "छियालीस"), (47, "सैंतालीस"), (48, "अड़तालीस"),
    (49, "उनचास"), (50, "पचास"), (51, "इक्यावन"), (52, "बावन"), (53, "तिरपन"), (54, "चौवन"), (55, "पचपन"),
    (56, "छप्पन"), (57, "सत्तावन"), (58, "अट्ठावन अठावन"), (59, "उनसठ"), (60, "साठ"), (61, "इकसठ"),
    (62, "बासठ"), (63, "तिरसठ"), (64, "चौंसठ"), (65, "पैंसठ"), (66, "छियासठ"), (67, "सड़सठ"), (68, "अड़सठ"),
    (69, "उनहत्तर"), (70, "सत्तर"), (71, "इकहत्तर"), (72, "बहत्तर"), (73, "तिहत्तर"), (74, "चौहत्तर"),
    (75, "पचहत्तर"), (76, "छिहत्तर"), (77, "सतहत्तर"), (78, "अठहत्तर"), (79, "उनासी"), (80, "अस्सी"),
    (81, "इक्यासी"), (82, "बयासी"), (83, "तिरासी"), (84, "चौरासी"), (85, "पचासी"), (86, "छियासी"),
    (87, "सत्तासी"), (88, "अट्ठासी अठासी"), (89, "नवासी"), (90, "नब्बे"), (91, "इक्यानवे"), (92, "बानवे"),
    (93, "तिरानवे"), (94, "चौरानवे"), (95, "पंचानवे"), (96, "छियानवे"), (97, "सत्तानवे"), (98, "अट्ठानवे अठानवे"),
    (99, "निन्यानवे"), (100, "सौ sau"),
    # Hindi in English letters (round numbers only)
    (5, "paanch panch"), (10, "das"), (15, "pandrah"), (20, "bees"), (25, "pachees pachchis"), (30, "tees"),
    (35, "paintees"), (40, "chalis"), (45, "paitalis"), (50, "pachas"), (55, "pachpan"), (60, "saath"),
    (65, "painsath"), (70, "sattar"), (75, "pachattar"), (80, "assi"), (85, "pachasi"), (90, "nabbe"),
    (95, "panchanve"),
]
_NUM = {}
for _v, _ws in _NUM_TABLE:
    for _w in _ws.split():
        _NUM[_n(_w)] = _v
_NUM_SMALL = {_n("एक"): 1, _n("दो"): 2, _n("ek"): 1, _n("do"): 2, _n("दो"): 2}      # only used right before a time unit
_NUM_SMALL.update(_NUM)

# apps the user may name ("क्रोम मिनिमाइज़ करो")
_APPS = {_n(k): v for k, v in {
    "क्रोम": "chrome", "गूगल": "chrome", "ब्राउज़र": "chrome", "ब्राउजर": "chrome", "एज": "edge", "स्पॉटिफाई": "spotify",
    "स्पोटिफाई": "spotify", "वर्ड": "word", "एक्सेल": "excel", "पावरपॉइंट": "powerpoint", "नोटपैड": "notepad",
    "व्हाट्सएप": "whatsapp", "वॉट्सएप": "whatsapp", "व्हाट्सऐप": "whatsapp", "यूट्यूब": "youtube", "एक्सप्लोरर": "explorer",
    "टर्मिनल": "terminal", "कैलकुलेटर": "calculator", "कैमरा": "camera", "सेटिंग्स": "settings", "पेंट": "paint",
    "टीम्स": "teams", "जूम": "zoom", "वीएलसी": "vlc"}.items()}

# cities she may be asked about (Devanagari -> the English name the weather service understands)
_PLACES = {_n(k): v for k, v in {
    "मुंबई": "Mumbai", "मुम्बई": "Mumbai", "बॉम्बे": "Mumbai", "दिल्ली": "Delhi", "पुणे": "Pune", "पूना": "Pune",
    "बेंगलुरु": "Bengaluru", "बैंगलोर": "Bengaluru", "बंगलौर": "Bengaluru", "चेन्नई": "Chennai", "कोलकाता": "Kolkata",
    "हैदराबाद": "Hyderabad", "अहमदाबाद": "Ahmedabad", "जयपुर": "Jaipur", "लखनऊ": "Lucknow", "नागपुर": "Nagpur",
    "नासिक": "Nashik", "नाशिक": "Nashik", "ठाणे": "Thane", "वाशी": "Vashi", "पनवेल": "Panvel", "गोवा": "Goa",
    "भोपाल": "Bhopal", "इंदौर": "Indore", "सूरत": "Surat", "पटना": "Patna", "चंडीगढ़": "Chandigarh",
    "लंदन": "London", "दुबई": "Dubai", "अमृतसर": "Amritsar", "आगरा": "Agra", "वाराणसी": "Varanasi",
    "बनारस": "Varanasi", "कानपुर": "Kanpur", "रायपुर": "Raipur", "रांची": "Ranchi", "कोच्चि": "Kochi",
    "कोची": "Kochi", "शिमला": "Shimla", "मनाली": "Manali", "उदयपुर": "Udaipur", "जोधपुर": "Jodhpur",
    "कल्याण": "Kalyan", "बेलापुर": "Belapur", "नेरुल": "Nerul", "कोल्हापुर": "Kolhapur", "औरंगाबाद": "Aurangabad",
    "खारघर": ""}.items()}                       # Kharghar = her home area = "" (the program already knows it)
_NOT_PLACE = _set("आज कल परसों अभी यहां यहाँ का की के में मे मेरे मेरा आपके तुम्हारे बाहर शहर इलाके बारे "
                  "बात कुछ क्या कैसा कैसी आसपास यहीं today tomorrow now here the my in of")
_PLACE_LINK = _set("का की के में मे")

# the commands (same format as brain.py: action, arg, say, risky). "say" is the English sentence hindi_fast.py turns into Hindi.
_ACTIONS = {
    "time": lambda: _cmd("time"),
    "date": lambda: _cmd("date"),
    "weather": lambda: _cmd("weather", ("", 0)),
    "weather_tomorrow": lambda: _cmd("weather", ("", 1)),
    "brightness_up": lambda: _cmd("brightness", (None, "up"), ""),
    "brightness_down": lambda: _cmd("brightness", (None, "down"), ""),
    "volume_up": lambda: _cmd("volume", "up", "Volume up."),
    "volume_down": lambda: _cmd("volume", "down", "Volume down."),
    "mute": lambda: _cmd("volume", "mute", "Toggling mute."),
    "minimize": lambda: _cmd("window", ("minimize", "")),
    "maximize": lambda: _cmd("window", ("maximize", "")),
    "restore": lambda: _cmd("window", ("restore", "")),
    "show_desktop": lambda: _cmd("show_desktop", say="Showing the desktop."),
    "new_tab": lambda: _cmd("new_tab", say="Opening a new tab."),
    "close_tab": lambda: _cmd("close_tab", say="Closing the tab."),
    "next_tab": lambda: _cmd("next_tab", say="Next tab."),
    "prev_tab": lambda: _cmd("prev_tab", say="Previous tab."),
    "close_window": lambda: _cmd("close_window", say="Closing the window."),
    "scroll_up": lambda: _cmd("scroll", 600, "Scrolling up."),
    "scroll_down": lambda: _cmd("scroll", -600, "Scrolling down."),
    "top": lambda: _cmd("top", say="Scrolling to the top."),
    "bottom": lambda: _cmd("bottom", say="Scrolling to the bottom."),
    "screenshot": lambda: _cmd("screenshot", say="Screenshot saved in Pictures, Screenshots."),
    "back": lambda: _cmd("back", say="Going back."),
    "forward": lambda: _cmd("forward", say="Going forward."),
    "refresh": lambda: _cmd("refresh", say="Refreshing."),
    "pause": lambda: _cmd("pause", say="Pausing."),
    "resume": lambda: _cmd("play_current", say="Playing."),
    "next_song": lambda: _cmd("next_song", say="Next song."),
    "prev_song": lambda: _cmd("prev_song", say="Previous song."),
    "lock": lambda: _cmd("lock", say="Locking the laptop."),
    "wifi_on": lambda: _cmd("radio", ("wifi", True), "Turning Wi-Fi on."),
    "wifi_off": lambda: _cmd("radio", ("wifi", False), "Turning Wi-Fi off."),
    "bluetooth_on": lambda: _cmd("radio", ("bluetooth", True), "Turning Bluetooth on."),
    "bluetooth_off": lambda: _cmd("radio", ("bluetooth", False), "Turning Bluetooth off."),
}


def _cmd(action, arg=None, say="", risky=False):
    return {"action": action, "arg": arg, "say": say, "risky": risky}


def _answer(text):
    return _cmd("answer", text, text)


def _number(s, toks):
    """A level like 50 from digits ('50', '५०') or Hindi words ('पचास'); 'full/max' = 100, 'half' = 50."""
    m = re.search(r"\d+", s)
    if m:
        return int(m.group(0))
    for t in toks:
        if t in _NUM:
            return _NUM[t]
    if _has(toks, FULL_W):
        return 100
    if _has(toks, HALF_W):
        return 50
    return None


def _timer_seconds(toks):
    """'5 मिनट', 'दो घंटे', 'आधा घंटा', 'डेढ़ घंटा' -> seconds (or None)."""
    total = 0
    for i, t in enumerate(toks):
        if t not in _UNITS:
            continue
        prev = toks[i - 1] if i else ""
        if prev.isdigit():
            total += int(prev) * _UNITS[t]
        elif prev in _NUM_SMALL:
            total += _NUM_SMALL[prev] * _UNITS[t]
        elif prev in HALF_W:
            total += _UNITS[t] // 2
        elif prev in (_n("डेढ़"), _n("dedh")):
            total += _UNITS[t] * 3 // 2
        elif prev in (_n("ढाई"), _n("dhai")):
            total += _UNITS[t] * 5 // 2
    return total or None


_TALK = [   # (phrases, replies). She is a woman: feminine forms ("हूँ", "करती").
    (("कैसी हो", "कैसे हो", "कैसे हैं", "कैसी हैं", "क्या हाल", "हाल चाल", "तुम कैसी", "आप कैसे", "आप कैसी",
      "kaise ho", "kaisi ho", "kaise hain", "kya haal", "how are you"),
     ["मैं बिल्कुल ठीक हूँ, पूछने के लिए शुक्रिया! बताइए, मैं आपकी क्या मदद करूँ?",
      "मैं अच्छी हूँ, शुक्रिया! आपके लिए क्या कर सकती हूँ?"]),
    (("तुम्हारा नाम", "आपका नाम", "तेरा नाम", "तुम कौन हो", "आप कौन हैं", "आप कौन हो", "अपना नाम", "नाम क्या है तुम्हारा",
      "tumhara naam", "aapka naam", "tum kaun ho", "aap kaun ho", "your name"),
     ["मैं रो हूँ, आपकी वॉइस असिस्टेंट। रोजर दैट, हमेशा आपकी सेवा में!"]),
    (("किसने बनाया", "तुम्हें किसने", "तुझे किसने", "आपको किसने", "तुम्हारा निर्माता", "आपकी निर्माता", "kisne banaya",
      "who made you"),
     ["मुझे वैभवी ने अपने कैपस्टोन प्रोजेक्ट के तौर पर बनाया है।"]),
    (("तुम क्या कर सकती", "आप क्या कर सकती", "तुम क्या कर सकते", "आप क्या कर सकते", "तुम्हारा काम क्या", "क्या क्या कर सकती",
      "tum kya kar sakti", "aap kya kar sakti", "what can you do"),
     ["मैं आपका लैपटॉप चला सकती हूँ, गाने बजा सकती हूँ, मौसम और समय बता सकती हूँ, टाइमर लगा सकती हूँ और आपके सवालों के जवाब दे सकती हूँ।"]),
]
_THANKS = _set("धन्यवाद शुक्रिया थैंक्स थैंक शुक्रगुज़ार thanks thank shukriya dhanyavad")
_HELLO = _set("नमस्ते नमस्कार हेलो हैलो हाय हलो namaste hello hi")
_GMORN = ("सुप्रभात", "शुभ प्रभात", "गुड मॉर्निंग", "good morning", "suprabhat")
_GNIGHT = ("शुभ रात्रि", "शुभरात्रि", "गुड नाइट", "good night", "shubh ratri")


def _phrase_in(padded, phrases):
    return any((" %s " % _n(p)) in padded for p in phrases)


def _my(s):
    """Your own sentences (MY_SENTENCES above): exact or very close match."""
    if not MY_SENTENCES:
        return None
    table = {_n(k): v for k, v in MY_SENTENCES.items()}
    hit = s if s in table else (difflib.get_close_matches(s, list(table), n=1, cutoff=0.86) or [None])[0]
    if hit is None:
        return None
    v = table[hit]
    if isinstance(v, (tuple, list)) and len(v) == 2 and v[0] == "reply":
        r = v[1]
        return _answer(random.choice(r) if isinstance(r, (list, tuple)) else r)
    if isinstance(v, str) and v in _ACTIONS:
        return _ACTIONS[v]()
    return None


def _weather_place(toks):
    """The city said in the sentence ('पुणे का मौसम', 'मुंबई में बारिश'), '' if none (then: her home area)."""
    for i, t in enumerate(toks):
        if t not in _PLACE_LINK or i == 0:
            continue
        # "पुणे का मौसम": the weather word comes right after.  "पुणे में बारिश / मौसम कैसा है": within two words.
        near = toks[i + 1:i + 3] if t in _set("में मे") else toks[i + 1:i + 2]
        if not _has(near, WEATHER_W):
            continue
        cand = toks[i - 1]
        if cand in _NOT_PLACE or cand in ASK or cand in WEATHER_W or cand.isdigit():
            continue
        if cand in _PLACES:
            return _PLACES[cand]
        if cand.isascii():
            return cand.title()
        return cand                                      # a Hindi name we do not know: the weather service may still know it
    for t in toks:                                       # a bare known city: "पुणे मौसम"
        if t in _PLACES and _PLACES[t]:
            return _PLACES[t]
    return ""


def _parse(text):
    s = _n(text)
    for a, b in _JOIN:
        if a in s:
            s = s.replace(a, b)
    if not s:
        return None
    toks = s.split()
    if len(toks) > 14:                                   # long sentences are for the AI
        return None
    padded = " %s " % s

    c = _my(s)
    if c:
        return c

    # ---------- small talk (she answers in Hindi) ----------
    for phrases, replies in _TALK:
        if _phrase_in(padded, phrases):
            return _answer(random.choice(replies))
    if _has(toks, _THANKS) and len(toks) <= 4:
        return _answer(random.choice(["कोई बात नहीं!", "आपका स्वागत है!", "हमेशा खुशी से!"]))
    if _phrase_in(padded, _GMORN):
        return _answer("सुप्रभात! आपका दिन शानदार रहे।")
    if _phrase_in(padded, _GNIGHT):
        return _answer("शुभ रात्रि! अच्छी नींद लीजिए।")
    if _has(toks, _HELLO) and len(toks) <= 3:
        return _answer("नमस्ते! बताइए, मैं आपकी क्या मदद कर सकती हूँ?")

    # ---------- timers (before "time", so "5 मिनट का टाइमर" is not the clock) ----------
    if _has(toks, TIMER_W) or (_has(toks, ALARM_W) and _has(toks, CANCEL_W)):
        if _has(toks, CANCEL_W) or _has(toks, CLOSE_W):
            return _cmd("cancel_timers", say="Cancelled all timers, alarms and reminders.")
        sec = _timer_seconds(toks)
        if sec and sec <= 86400:
            return _cmd("timer", sec, "")
        return None
    if _has(toks, ALARM_W):                              # alarms and reminders: the AI understands the times
        return None

    # ---------- time and date ----------
    if _has(toks, TIME_W) and (_has(toks, ASK) or len(toks) <= 2) and not any(t.isdigit() for t in toks):
        return _ACTIONS["time"]()
    if _has(toks, DATE_W) and (_has(toks, ASK) or len(toks) <= 3 or _has(toks, _set("आज aaj"))):
        return _ACTIONS["date"]()
    if _has(toks, DAY_W) and _has(toks, _set("आज aaj")) and (_has(toks, ASK) or _has(toks, _set("कौनसा"))):
        return _ACTIONS["date"]()

    # ---------- weather ----------
    if _has(toks, WEATHER_W) and not _has(toks, _set("रेसिपी recipe गाना song")):
        day = 2 if _has(toks, _set("परसों parso")) else (1 if _has(toks, _set("कल kal")) else 0)
        return _cmd("weather", (_weather_place(toks), day), "")

    # ---------- brightness ----------
    if _has(toks, BRIGHT_W):
        lvl = _number(s, toks)
        if lvl is not None and not _has(toks, UP | DOWN):
            return _cmd("brightness", (max(5, min(100, lvl)), ""), "")
        if lvl is not None and _has(toks, PCT_W):
            return _cmd("brightness", (max(5, min(100, lvl)), ""), "")
        up, down = _has(toks, UP), _has(toks, DOWN)
        if up and not down:
            return _ACTIONS["brightness_up"]()
        if down and not up:
            return _ACTIONS["brightness_down"]()
        return None

    # ---------- volume ----------
    if _has(toks, VOLUME_W) or _has(toks, MUTE_W):
        if _has(toks, MUTE_W):
            return _ACTIONS["mute"]()
        lvl = _number(s, toks)
        up, down = _has(toks, UP), _has(toks, DOWN)
        if lvl is not None and not (up or down or _has(toks, ON | OFF)) or (lvl is not None and _has(toks, PCT_W)):
            return _cmd("set_volume", max(0, min(100, lvl)), "Volume set to %d percent." % max(0, min(100, lvl)))
        if up and not down:
            return _ACTIONS["volume_up"]()
        if down and not up:
            return _ACTIONS["volume_down"]()
        if _has(toks, _set("वॉल्यूम वोल्यूम volume")) and _has(toks, OFF):
            return _ACTIONS["mute"]()
        return None

    # ---------- Wi-Fi / Bluetooth ----------
    for words, name in ((WIFI_W, "wifi"), (BT_W, "bluetooth")):
        if _has(toks, words):
            on, off = _has(toks, ON), _has(toks, OFF)
            if on and not off:
                return _ACTIONS[name + "_on"]()
            if off and not on:
                return _ACTIONS[name + "_off"]()
            return None

    # ---------- windows and tabs (minimize / maximize / restore / tabs) ----------
    is_min, is_max, is_res = _has(toks, MIN_W), _has(toks, MAX_W), _has(toks, RESTORE_W)
    if _has(toks, TAB_W) and not (is_min or is_max or is_res):
        if _has(toks, NEW_W):
            return _ACTIONS["new_tab"]()
        if _has(toks, CLOSE_W):
            return _ACTIONS["close_tab"]()
        if _has(toks, NEXTW | FWD_W):
            return _ACTIONS["next_tab"]()
        if _has(toks, PREVW | BACK_W):
            return _ACTIONS["prev_tab"]()
    if _has(toks, _set("विंडो विन्डो खिड़की window")) and _has(toks, CLOSE_W) and not (is_min or is_max or is_res):
        return _ACTIONS["close_window"]()
    if is_min + is_max + is_res == 1:
        if (_has(toks, ALL_W) and is_min) or (_has(toks, DESK_W) and not is_max):
            return _ACTIONS["show_desktop"]()
        do = "minimize" if is_min else ("maximize" if is_max else "restore")
        name = ""
        for t in toks:
            if t in _APPS:
                name = _APPS[t]
                break
            if t.isascii() and t.isalpha() and t not in (MIN_W | MAX_W | RESTORE_W | FILLER | WINDOW_W
                                                         | _set("the my a an it this that window")):
                name = t
                break
        return _cmd("window", (do, name))
    if _has(toks, DESK_W) and _has(toks, _set("दिखाओ दिखाइए दिखाइये देखो जाओ खोलो show")):
        return _ACTIONS["show_desktop"]()

    # ---------- screenshot, lock, refresh, back / forward ----------
    if _has(toks, SHOT_W):
        return _ACTIONS["screenshot"]()
    if _has(toks, LOCK_W) and _has(toks, LAPTOP_W):
        return _ACTIONS["lock"]()
    if _has(toks, REFRESH_W) and len(toks) <= 4:
        return _ACTIONS["refresh"]()
    if len(toks) <= 4 and _has(toks, BACK_W) and (_has(toks, GO_W) or "बेक" in toks or "back" in toks):
        return _ACTIONS["back"]()
    if len(toks) <= 4 and _has(toks, FWD_W) and (_has(toks, GO_W) or "forward" in toks or _n("फॉरवर्ड") in toks):
        return _ACTIONS["forward"]()

    # ---------- scroll ----------
    if _has(toks, SCROLL_W):
        up = _has(toks, _set("ऊपर upar ooper up"))
        down = _has(toks, _set("नीचे neeche down"))
        if _has(toks, _set("सबसे टॉप top")) and up:
            return _ACTIONS["top"]()
        if _has(toks, _set("सबसे बॉटम bottom")) and down:
            return _ACTIONS["bottom"]()
        amt = 300 if _has(toks, LITTLE_W) else (1500 if _has(toks, LOT_W) else 600)
        return _cmd("scroll", amt if (up and not down) else -amt, "Scrolling %s." % ("up" if (up and not down) else "down"))

    # ---------- music: only when NO song name was said (a name goes to the AI) ----------
    if _has(toks, SONG) or _has(toks, _set("पॉज़ पॉज pause")):
        rest = [t for t in toks if t not in SONG and t not in FILLER and t not in PLAY and t not in STOPW
                and t not in NEXTW and t not in PREVW]
        if not rest:
            if _has(toks, PREVW):
                return _ACTIONS["prev_song"]()
            if _has(toks, NEXTW):
                return _ACTIONS["next_song"]()
            if _has(toks, STOPW):
                return _ACTIONS["pause"]()
            if _has(toks, PLAY):
                return _ACTIONS["resume"]()
    return None


def parse(text):
    """A command for a basic Hindi sentence, or None. Never raises."""
    try:
        return _parse(text)
    except Exception:
        return None


def understood(text):
    """True if Roe knows this Hindi sentence as one of her own commands (used to skip the slow speech model)."""
    return parse(text) is not None
