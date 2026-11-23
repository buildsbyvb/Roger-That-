"""
Roe - instant Hindi for the most common short replies (no internet, no waiting).

When you speak Hindi, Roe used to ask the AI to translate each English reply, which takes a second or two.
For the common replies below the Hindi is ready at once. Anything not listed still goes to the AI as before.
Add your own lines to PHRASES if you like (English sentence exactly as Roe says it -> Hindi).
"""
import re

PHRASES = {
    "I could not see any videos on the screen.": "मुझे स्क्रीन पर कोई वीडियो नहीं दिख रहा।",
    "I could not see anything to open on the screen.": "मुझे स्क्रीन पर खोलने के लिए कुछ नहीं दिख रहा।",
    "I could not read the phone screen. Keep it unlocked and try again.": "मैं फ़ोन की स्क्रीन नहीं पढ़ पाई। उसे अनलॉक रखिए और फिर कोशिश कीजिए।",
    "Message sent.": "मैसेज भेज दिया।",
    "Typed it.": "टाइप कर दिया।",
    "Opening Images.": "इमेजेस खोल रही हूँ।",
    "Opening Videos.": "वीडियो खोल रही हूँ।",
    "Opening Audio.": "ऑडियो खोल रही हूँ।",
    "Opening Downloads.": "डाउनलोड्स खोल रही हूँ।",
    "Opening Documents.": "डॉक्यूमेंट्स खोल रही हूँ।",
    "Closing the window.": "विंडो बंद कर रही हूँ।",
    "Closing the tab.": "टैब बंद कर रही हूँ।",
    "Opening a new tab.": "नया टैब खोल रही हूँ।",
    "Next tab.": "अगला टैब।",
    "Previous tab.": "पिछला टैब।",
    "Going back.": "पीछे जा रही हूँ।",
    "Going forward.": "आगे जा रही हूँ।",
    "Refreshing.": "रिफ्रेश कर रही हूँ।",
    "Showing the desktop.": "डेस्कटॉप दिखा रही हूँ।",
    "Switching window.": "विंडो बदल रही हूँ।",
    "Screenshot saved in Pictures, Screenshots.": "स्क्रीनशॉट पिक्चर्स के स्क्रीनशॉट्स फ़ोल्डर में सेव हो गया।",
    "Selecting all.": "सब कुछ सेलेक्ट कर रही हूँ।",
    "Copied.": "कॉपी हो गया।",
    "Pasted.": "पेस्ट हो गया।",
    "Undone.": "अनडू कर दिया।",
    "Saving.": "सेव कर रही हूँ।",
    "Pressed enter.": "एंटर दबा दिया।",
    "Scrolling to the top.": "सबसे ऊपर जा रही हूँ।",
    "Scrolling to the bottom.": "सबसे नीचे जा रही हूँ।",
    "Showing the notification bar.": "नोटिफ़िकेशन बार दिखा रही हूँ।",
    "Showing quick settings.": "क्विक सेटिंग्स दिखा रही हूँ।",
    "Scrolling up.": "ऊपर स्क्रॉल कर रही हूँ।",
    "Scrolling down.": "नीचे स्क्रॉल कर रही हूँ।",
    "Volume up.": "आवाज़ बढ़ा रही हूँ।",
    "Volume down.": "आवाज़ कम कर रही हूँ।",
    "Toggling mute.": "म्यूट बदल रही हूँ।",
    "Done.": "हो गया।",
    "Okay.": "ठीक है।",
    "Okay, cancelled.": "ठीक है, रद्द कर दिया।",
    "Okay, I will keep listening.": "ठीक है, मैं सुनती रहूँगी।",
    "Sorry, I did not catch that. Could you say it again?": "माफ़ कीजिए, मैं समझ नहीं पाई। क्या आप दोबारा बोल सकते हैं?",
    "I do not know how to do that yet.": "मुझे यह अभी करना नहीं आता।",
    "You had no timers, alarms or reminders.": "आपका कोई टाइमर, अलार्म या रिमाइंडर नहीं था।",
    "Reading aloud. Say stop reading to stop me.": "पढ़कर सुना रही हूँ। रुकने के लिए 'स्टॉप रीडिंग' बोलिए।",
    "I could not change the brightness. It only works on the laptop's own screen.": "मैं ब्राइटनेस नहीं बदल पाई। यह सिर्फ़ लैपटॉप की अपनी स्क्रीन पर काम करता है।",
    "I could not get the weather right now. Is the internet working?": "अभी मौसम की जानकारी नहीं मिल पाई। क्या इंटरनेट चल रहा है?",
    "I could not get the weather for Kharghar right now.": "अभी खारघर का मौसम नहीं मिल पाया।",
    "Locking the laptop.": "लैपटॉप लॉक कर रही हूँ।",
    "Pausing.": "रोक रही हूँ।",
    "Paused.": "रोक दिया।",
    "Playing.": "चला रही हूँ।",
    "Playing your song.": "आपका गाना चला रही हूँ।",
    "I pressed pause.": "मैंने पॉज़ दबा दिया।",
    "It is already playing.": "यह पहले से चल रहा है।",
    "Opened Spotify and playing.": "स्पॉटिफाई खोलकर चला रही हूँ।",
    "Nothing is playing right now.": "अभी कुछ नहीं चल रहा।",
    "Next song.": "अगला गाना।",
    "Previous song.": "पिछला गाना।",
    "Turning Wi-Fi on.": "वाई-फ़ाई चालू कर रही हूँ।",
    "Turning Wi-Fi off.": "वाई-फ़ाई बंद कर रही हूँ।",
    "Turning Bluetooth on.": "ब्लूटूथ चालू कर रही हूँ।",
    "Turning Bluetooth off.": "ब्लूटूथ बंद कर रही हूँ।",
    "Windows did not let me switch it, so I opened the settings page.": "विंडोज़ ने इसे बदलने नहीं दिया, इसलिए मैंने सेटिंग्स का पेज खोल दिया।",
    "Cancelled all timers, alarms and reminders.": "सभी टाइमर, अलार्म और रिमाइंडर रद्द कर दिए।",
    "Click on the window you want to control first, then say it again.": "पहले उस विंडो पर क्लिक कीजिए जिसे चलाना है, फिर दोबारा बोलिए।",
    "I could not find a window to minimize.": "मुझे मिनिमाइज़ करने के लिए कोई विंडो नहीं मिली।",
    "I could not find a window to maximize.": "मुझे मैक्सिमाइज़ करने के लिए कोई विंडो नहीं मिली।",
    "I could not find a window to restore.": "मुझे रीस्टोर करने के लिए कोई विंडो नहीं मिली।",
}
_PAST = {"Minimized": "मिनिमाइज़", "Maximized": "मैक्सिमाइज़", "Restored": "रीस्टोर", "Closed": "बंद"}
_DAYS = {"Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार", "Thursday": "गुरुवार",
         "Friday": "शुक्रवार", "Saturday": "शनिवार", "Sunday": "रविवार"}
_MONTHS = {"January": "जनवरी", "February": "फ़रवरी", "March": "मार्च", "April": "अप्रैल", "May": "मई",
           "June": "जून", "July": "जुलाई", "August": "अगस्त", "September": "सितंबर", "October": "अक्टूबर",
           "November": "नवंबर", "December": "दिसंबर"}
_UNITS = {"second": "सेकंड", "seconds": "सेकंड", "minute": "मिनट", "minutes": "मिनट",
          "hour": "घंटे", "hours": "घंटे"}

_WEATHER = {"clear sky": "आसमान साफ़", "mostly clear": "ज़्यादातर साफ़ आसमान", "partly cloudy": "थोड़े बादल",
            "overcast": "घने बादल", "foggy": "कोहरा", "light drizzle": "हल्की फुहारें", "drizzle": "फुहारें",
            "heavy drizzle": "तेज़ फुहारें", "freezing drizzle": "जमने वाली फुहारें", "light rain": "हल्की बारिश",
            "rain": "बारिश", "heavy rain": "तेज़ बारिश", "freezing rain": "जमने वाली बारिश",
            "light snow": "हल्की बर्फ़बारी", "snow": "बर्फ़बारी", "heavy snow": "भारी बर्फ़बारी",
            "snow grains": "बर्फ़ के कण", "light rain showers": "हल्की बौछारें", "rain showers": "बारिश की बौछारें",
            "heavy rain showers": "तेज़ बौछारें", "snow showers": "बर्फ़ की बौछारें",
            "heavy snow showers": "भारी बर्फ़ की बौछारें", "a thunderstorm": "आंधी-तूफ़ान और बिजली",
            "a thunderstorm with hail": "ओलों के साथ आंधी-तूफ़ान",
            "a thunderstorm with heavy hail": "भारी ओलों के साथ आंधी-तूफ़ान", "mixed weather": "मिला-जुला मौसम"}
_CITIES = {"Kharghar, Navi Mumbai": "खारघर, नवी मुंबई", "Kharghar": "खारघर", "Navi Mumbai": "नवी मुंबई",
           "Mumbai": "मुंबई", "Delhi": "दिल्ली", "Pune": "पुणे", "Bengaluru": "बेंगलुरु", "Chennai": "चेन्नई",
           "Kolkata": "कोलकाता", "Hyderabad": "हैदराबाद", "Ahmedabad": "अहमदाबाद", "Jaipur": "जयपुर",
           "Lucknow": "लखनऊ", "Nagpur": "नागपुर", "Nashik": "नाशिक", "Thane": "ठाणे", "Vashi": "वाशी",
           "Panvel": "पनवेल", "Goa": "गोवा", "Bhopal": "भोपाल", "Indore": "इंदौर", "Surat": "सूरत", "Patna": "पटना",
           "London": "लंदन", "Dubai": "दुबई"}


_APPS_HI = {"chrome": "क्रोम", "edge": "एज", "spotify": "स्पॉटिफाई", "word": "वर्ड", "excel": "एक्सेल",
            "powerpoint": "पावरपॉइंट", "notepad": "नोटपैड", "whatsapp": "व्हाट्सएप", "youtube": "यूट्यूब",
            "explorer": "फाइल एक्सप्लोरर", "terminal": "टर्मिनल", "calculator": "कैलकुलेटर", "camera": "कैमरा",
            "settings": "सेटिंग्स", "paint": "पेंट", "teams": "टीम्स", "zoom": "ज़ूम", "vlc": "वीएलसी"}


def _app(name):
    return _APPS_HI.get(name.strip().lower(), name)


def _rain(p):
    return (" बारिश की संभावना %s प्रतिशत है।" % p) if p else ""



def quick(message):
    """Hindi for a known English reply, or None (then the AI translates it)."""
    if not message:
        return None
    m = message.strip()
    if m in PHRASES:
        return PHRASES[m]
    x = re.match(r"^Brightness is now (\d+) percent\.$", m)
    if x:
        return "ब्राइटनेस अब %s प्रतिशत है।" % x.group(1)
    x = re.match(r"^Volume set to (\d+) percent\.$", m)
    if x:
        return "आवाज़ %s प्रतिशत कर दी।" % x.group(1)
    x = re.match(r"^Right now in (.+?) it is (-?\d+) degrees and (.+?), feels like (-?\d+)\. "
                 r"Today's high is (-?\d+) and the low is (-?\d+)\.(?: The chance of rain is (\d+) percent\.)?$", m)
    if x:
        place, now, cond, feel, hi, lo, rain = x.groups()
        return ("अभी %s में तापमान %s डिग्री है, मौसम: %s। महसूस %s डिग्री जैसा हो रहा है। "
                "आज का अधिकतम तापमान %s और न्यूनतम %s डिग्री है।%s"
                % (_CITIES.get(place, place), now, _WEATHER.get(cond, cond), feel, hi, lo, _rain(rain)))
    x = re.match(r"^(Tomorrow|The day after tomorrow) in (.+?): (.+?), high (-?\d+) and low (-?\d+)\."
                 r"(?: The chance of rain is (\d+) percent\.)?$", m)
    if x:
        when, place, cond, hi, lo, rain = x.groups()
        return ("%s %s में मौसम: %s, अधिकतम %s और न्यूनतम %s डिग्री।%s"
                % ("कल" if when == "Tomorrow" else "परसों", _CITIES.get(place, place), _WEATHER.get(cond, cond),
                   hi, lo, _rain(rain)))
    x = re.match(r"^I could not find an open window called (.+)\.$", m)
    if x:
        return "मुझे %s नाम की कोई खुली विंडो नहीं मिली।" % _app(x.group(1))
    x = re.match(r"^Closed (.+)\.$", m)
    if x:
        return "%s बंद कर दिया।" % _app(x.group(1))
    x = re.match(r"^Opening (.+)\.$", m)
    if x:
        return "%s खोल रही हूँ।" % x.group(1)
    x = re.match(r"^(Minimized|Maximized|Restored) (.+)\.$", m)
    if x and x.group(2) != "the window":
        return "%s %s कर दिया।" % (_app(x.group(2)), _PAST[x.group(1)])
    if x:
        return "विंडो %s कर दी।" % _PAST[x.group(1)]
    x = re.match(r"^It is (\d{1,2}):(\d{2}) (AM|PM)\.$", m)
    if x:
        h, mi, ap = int(x.group(1)), int(x.group(2)), x.group(3)
        part = "सुबह" if ap == "AM" else ("दोपहर" if h in (12, 1, 2, 3) else "शाम" if h < 8 else "रात")
        return "अभी %s के %d बजे हैं।" % (part, h) if mi == 0 else \
               "अभी %s के %d बजकर %d मिनट हुए हैं।" % (part, h, mi)
    x = re.match(r"^Today is (\w+), (\d{1,2}) (\w+) (\d{4})\.$", m)
    if x and x.group(1) in _DAYS and x.group(3) in _MONTHS:
        return "आज %s, %s %s %s है।" % (_DAYS[x.group(1)], x.group(2), _MONTHS[x.group(3)], x.group(4))
    x = re.match(r"^Timer set for (\d+) (\w+)\.$", m)
    if x and x.group(2) in _UNITS:
        unit = "घंटा" if (x.group(2) == "hour" and x.group(1) == "1") else _UNITS[x.group(2)]
        return "%s %s का टाइमर लग गया।" % (x.group(1), unit)
    return None
