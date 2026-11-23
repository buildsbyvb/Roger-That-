"""
Roe - random greeting when you say "activate voice".

Each time a different one (it never repeats the same greeting twice in a row).
Add or change greetings in the list below.
"""
import random
import time

GREETINGS = [
    "Hi!",
    "Hello!",
    "Hey there!",
    "Hi, I am listening.",
    "Hello, how can I help you?",
    "Hey! What can I do for you?",
    "Hi there!",
    "Hello again!",
    "Hey, I am all ears.",
    "Roe reporting for duty!",
    "Aye aye, captain! I am listening.",
    "Roger that! What is the mission?",
]
TIME_GREETINGS = {                     # used sometimes, by the time of day
    "morning": "Good morning!",
    "afternoon": "Good afternoon!",
    "evening": "Good evening!",
}
TIME_CHANCE = 0.25                     # 25 % of the time it greets by the time of day

_last = {"text": ""}


def _part_of_day():
    h = time.localtime().tm_hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return None                        # late night: no "good ..." greeting


def greeting():
    part = _part_of_day()
    if part and random.random() < TIME_CHANCE and TIME_GREETINGS[part] != _last["text"]:
        _last["text"] = TIME_GREETINGS[part]
        return _last["text"]
    choices = [g for g in GREETINGS if g != _last["text"]]
    _last["text"] = random.choice(choices)
    return _last["text"]
