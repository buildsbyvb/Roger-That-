"""
Roe - Step 11: internet search + weather (default place = Kharghar, Navi Mumbai).

answer(query, kind)  -> searches the web (DuckDuckGo, free, no key), reads the best
                        pages, and asks Groq for a SHORT spoken summary.
                        kind = general | news | recipe | tutorial
                        Returns None if searching is not possible (then the caller
                        just opens Google).
weather(place, day)  -> current weather / forecast from Open-Meteo (free, no key).
last["sources"]      -> [(title, url), ...] of the last search (for "open the first link").

Install once:  py -3.11 -m pip install ddgs
"""
import concurrent.futures
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import llm

# ---------------- Settings you can change ----------------
DEFAULT_PLACE = "Kharghar"            # used whenever you do NOT say a place ("what is the temperature")
DEFAULT_AREA = "Kharghar, Navi Mumbai"
DEFAULT_LAT, DEFAULT_LON = 19.0474, 73.0699   # Kharghar, Navi Mumbai (fixed, so it is instant and always right)
USE_WINDOWS_LOCATION = False  # True = ask Windows for your real position instead (slow, about 10 seconds,
                              # and often wrong). Leave False.
READ_PAGE_FOR_SHORT_ANSWERS = False   # False = short answers use only the search snippets (much faster).
                                      # Recipes, tutorials and "explain in detail" still read a web page.
SEARCH_REGION = "in-en"   # search results for India (English)
GROQ_MODEL = "openai/gpt-oss-20b"      # fast model (llm.py falls back to another model by itself)
# ---------------------------------------------------------

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DoIt/1.0"
last = {"sources": [], "query": ""}


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------
def _ddgs_class():
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            return DDGS
        except ImportError:
            return None


def have_search():
    return _ddgs_class() is not None


def search(query, kind="general", n=6):
    DDGS = _ddgs_class()
    if DDGS is None:
        raise RuntimeError("the search package is not installed (py -3.11 -m pip install ddgs)")
    d = DDGS()
    try:
        rows = (d.news(query, region=SEARCH_REGION, max_results=n) if kind == "news"
                else d.text(query, region=SEARCH_REGION, max_results=n))
    except TypeError:                                  # older/newer versions with other arguments
        rows = (d.news(query, max_results=n) if kind == "news" else d.text(query, max_results=n))
    out = []
    for r in rows or []:
        url = r.get("href") or r.get("url") or ""
        if not url.startswith("http"):
            continue
        out.append({"title": (r.get("title") or "").strip(),
                    "url": url,
                    "snippet": (r.get("body") or "").strip(),
                    "date": (r.get("date") or "")[:10],
                    "source": r.get("source") or ""})
    return out


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.parts.append(data.strip())


def page_text(url, limit=3000):
    """Plain text of a web page (first part only). Empty string if it fails."""
    if not re.match(r"^https?://", url):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=6) as r:
            if "html" not in r.headers.get("Content-Type", ""):
                return ""
            raw = r.read(400000)
            enc = r.headers.get_content_charset() or "utf-8"
        p = _Text()
        p.feed(raw.decode(enc, "ignore"))
        return re.sub(r"\s+", " ", " ".join(p.parts))[:limit]
    except Exception:
        return ""


SUMMARY_BASE = """You are the voice of "Roe", a friendly voice assistant like Siri or Google Assistant.
Answer the user's question using ONLY the search results below. The answer is read aloud, so write plain, natural
sentences: no lists, no markdown, no links, no brackets, no citation numbers like [1], no "according to the results",
no "here is what I found". The user's words come from speech recognition and may be slightly misheard: answer what
they most likely meant (for example "sign which recipe" means "sandwich recipe").
If the results do not really answer the question, say so honestly in one sentence."""
LANG_EN = "Write the answer in English."
LANG_HI = ("Write the answer in natural spoken Hindi in Devanagari script (the speaker is a woman: use feminine "
           "forms). Keep names, numbers and units as they are.")

LENGTH = {
    "short": 'Answer in ONE short sentence that states the answer directly, for example "The capital of India is New Delhi."',
    "detail": "Explain in 3 to 5 short sentences.",
    "news": "Give the 3 most important headlines, one short sentence each.",
    "recipe": "Say the dish, its main ingredients, then the main steps, in 3 to 5 short sentences.",
    "tutorial": "Say the first few steps, in 3 to 5 short sentences.",
}


def clean_answer(text):
    """Removes Wikipedia-style [1] marks, markdown and filler openings."""
    text = re.sub(r"\[\s*\d+(?:\s*[,-]\s*\d+)*\s*\]", "", text)
    text = re.sub(r"\[(?:citation needed|note \d+|[a-z])\]", "", text, flags=re.I)
    text = re.sub(r"[*#`_~]", "", text)
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(?:here is what i found|here's what i found)[.:,]?\s*", "", text, flags=re.I)


def first_sentence(text, limit=220):
    text = clean_answer(text)
    m = re.search(r"(?<=[.!?])\s", text)
    one = text[:m.start()] if m else text
    return one[:limit].rstrip()


NEAR_ME = re.compile(r"\b(?:near me|nearby|near by|around me|near here|in my area|around here|close to me)\b", re.I)


def answer(query, kind="general", detailed=False, hindi=False):
    last["sources"] = []                                  # never show links of an older search
    if NEAR_ME.search(query):                             # "restaurants near me" -> near Kharghar
        query = NEAR_ME.sub("in " + DEFAULT_AREA, query)
    try:
        rows = search(query, kind)
    except Exception as e:
        print("(search problem: %s)" % e)
        return None
    if not rows:
        return "I searched the web but found nothing useful for that."
    last["sources"] = [(r["title"], r["url"]) for r in rows[:5]]
    last["query"] = query

    pages = {}
    if kind != "news" and (READ_PAGE_FOR_SHORT_ANSWERS or detailed or kind in ("recipe", "tutorial")):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = {i: ex.submit(page_text, rows[i]["url"]) for i in range(min(1, len(rows)))}   # 1 page = faster
            for i, f in futs.items():
                try:
                    pages[i] = f.result(timeout=5)
                except Exception:
                    pages[i] = ""

    blocks = []
    for i, r in enumerate(rows[:5]):
        head = "[%d] %s %s" % (i + 1, r["title"], ("(%s)" % r["date"]) if r["date"] else "")
        body = pages.get(i) or r["snippet"]
        blocks.append("%s\n%s" % (head, body[:2500]))
    length = LENGTH["detail"] if (detailed and kind == "general") else LENGTH.get(kind, LENGTH["short"])
    text = llm.chat(
        [{"role": "system", "content": SUMMARY_BASE + "\n" + length + "\n" + (LANG_HI if hindi else LANG_EN)},
         {"role": "user", "content": "Question: %s\n\nSearch results:\n%s" % (query, "\n\n".join(blocks))}],
        model=GROQ_MODEL, max_tokens=350 if detailed else 200, temperature=0.3, timeout=15)
    if text:
        return clean_answer(text)
    snippet = rows[0]["snippet"] or rows[0]["title"]      # no AI: first sentence of the first snippet
    return first_sentence(snippet)


# ------------------------------------------------------------------
# Weather (Open-Meteo, free, no key)
# ------------------------------------------------------------------
WMO = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light rain showers",
       81: "rain showers", 82: "heavy rain showers", 85: "snow showers", 86: "heavy snow showers",
       95: "a thunderstorm", 96: "a thunderstorm with hail", 99: "a thunderstorm with heavy hail"}
_here_cache = {}


def _get_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _geocode(name, prefer_country=None):
    """(latitude, longitude, name) of a place she named. Open-Meteo first, then OpenStreetMap
    (which knows small areas such as Vashi, Panvel, Belapur)."""
    name = re.sub(r"\s+", " ", name).strip(" ,.")
    if re.search(r"\bkharghar\b", name, re.I):          # her home area: no lookup needed
        return DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE
    try:
        url = ("https://geocoding-api.open-meteo.com/v1/search?name=%s&count=5&language=en&format=json"
               % urllib.parse.quote(name))
        res = (_get_json(url).get("results") or [])
        if res:
            if prefer_country:
                res = [r for r in res if r.get("country_code") == prefer_country] or res
            r = res[0]
            return r["latitude"], r["longitude"], r.get("name", name)
    except Exception:
        pass
    d = _get_json("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&accept-language=en&q=%s"
                  % urllib.parse.quote(name), timeout=8)
    if not d:
        raise LookupError("place not found")
    shown = d[0].get("name") or d[0].get("display_name", name).split(",")[0]
    return float(d[0]["lat"]), float(d[0]["lon"]), shown


LOCATION_SCRIPT = r"""
try {
  Add-Type -AssemblyName System.Device
  $w = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::High)
  [void]$w.TryStart($false, [TimeSpan]::FromSeconds(8))
  $i = 0
  while ($w.Status -ne 'Ready' -and $i -lt 60) { Start-Sleep -Milliseconds 200; $i++ }
  $c = $w.Position.Location
  if ($c.IsUnknown) { 'unknown' } else {
    [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0},{1},{2}', $c.Latitude, $c.Longitude, $c.HorizontalAccuracy)
  }
} catch { 'error: ' + $_.Exception.Message }
"""


def _windows_location():
    """(lat, lon, accuracy in metres) from the Windows location service, or None."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", LOCATION_SCRIPT],
                           capture_output=True, timeout=25, creationflags=0x08000000)
        lines = r.stdout.decode("utf-8", "ignore").strip().splitlines()
        out = lines[-1] if lines else ""
        m = re.fullmatch(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?|NaN)", out)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))
        acc = float(m.group(3)) if m.group(3) != "NaN" else 0.0
        if abs(lat) > 90 or abs(lon) > 180 or (lat == 0 and lon == 0):
            return None
        return lat, lon, acc
    except Exception:
        return None


def _place_name(lat, lon):
    """Area / town name for a position (OpenStreetMap Nominatim, free)."""
    try:
        d = _get_json("https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=13"
                      "&accept-language=en&lat=%s&lon=%s" % (lat, lon), timeout=8)
        a = d.get("address", {})
        for key in ("suburb", "city_district", "neighbourhood", "town", "city", "village", "county"):
            if a.get(key):
                return a[key]
    except Exception:
        pass
    return "your area"


def _here():
    """(lat, lon, name) of "here". It is ALWAYS Kharghar, Navi Mumbai, unless USE_WINDOWS_LOCATION is on."""
    if USE_WINDOWS_LOCATION and os.name == "nt":
        c = _here_cache.get("v")
        if c and time.time() - c[1] < 1800:
            return c[0]
        loc = _windows_location()
        if loc and loc[2] <= 5000:
            v = (loc[0], loc[1], _place_name(loc[0], loc[1]))
            _here_cache["v"] = (v, time.time())
            return v
    return DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE


def weather(place="", day=0):
    """day: 0 = now/today, 1 = tomorrow, 2 = day after tomorrow."""
    try:
        lat, lon, name = _geocode(place) if place else _here()
    except Exception:
        return ("I could not find %s. Please say the place name again, for example: weather in Pune."
                % place) if place else "I could not get the weather for Kharghar right now."
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
               "&current=temperature_2m,apparent_temperature,weather_code"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&timezone=auto&forecast_days=3" % (lat, lon))
        d = _get_json(url)
        day = max(0, min(2, int(day)))
        dl = d["daily"]
        cond = WMO.get(dl["weather_code"][day], "mixed weather")
        hi, lo = round(dl["temperature_2m_max"][day]), round(dl["temperature_2m_min"][day])
        rain = dl["precipitation_probability_max"][day]
        rain_txt = (" The chance of rain is %d percent." % rain) if rain is not None and rain >= 20 else ""
        if day == 0:
            c = d["current"]
            now = WMO.get(c["weather_code"], "mixed weather")
            return ("Right now in %s it is %d degrees and %s, feels like %d. "
                    "Today's high is %d and the low is %d.%s"
                    % (name, round(c["temperature_2m"]), now, round(c["apparent_temperature"]), hi, lo, rain_txt))
        word = "Tomorrow" if day == 1 else "The day after tomorrow"
        return "%s in %s: %s, high %d and low %d.%s" % (word, name, cond, hi, lo, rain_txt)
    except Exception:
        return "I could not get the weather right now. Is the internet working?"
