"""
Do It - one small helper that talks to Groq (the free AI).

chat(messages, model, ...) -> the AI's text, or None if it did not work.
When it returns None, the reason is in last_error["msg"].

Needs the Windows variable GROQ_API_KEY (never put the key in code).
Uses only built-in Python (urllib), nothing to install.

MODELS: Groq retired llama-3.3-70b-versatile on 16 Aug 2026 (that caused "Groq error 404").
If a model is ever retired again (404), this file automatically tries the next one in
MODELS, so the assistant keeps working. Check https://console.groq.com/docs/models
and edit MODELS if you want a different one.
"""
import json
import os
import urllib.error
import urllib.request

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]     # tried in this order
last_error = {"msg": ""}
_working = {"model": None}      # the model that worked last time (tried first)
_dead = set()                   # models Groq said do not exist (404): never tried again


def available():
    return bool(os.environ.get("GROQ_API_KEY", "").strip())


def _candidates(model):
    out = []
    for m in (_working["model"], model, *MODELS):
        if m and m not in out and m not in _dead:
            out.append(m)
    return out


def _request(model, messages, json_mode, max_tokens, temperature, timeout, key, simple):
    """One call. Returns (text or None, code). code: 200 ok, HTTP error number, or None = no internet."""
    reasoning = "gpt-oss" in model            # these models "think" first, which uses tokens
    payload = {"model": model, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens + (600 if reasoning else 0)}
    if not simple:
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if reasoning:
            payload["reasoning_effort"] = "low"
            payload["include_reasoning"] = False
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "User-Agent": "DoIt/1.0"})          # Groq can refuse the default Python agent
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = (data["choices"][0]["message"].get("content") or "").strip()
        if not text:
            last_error["msg"] = "Groq sent an empty answer"
            return None, 204
        return text, 200
    except urllib.error.HTTPError as e:
        last_error["msg"] = {401: "Groq says the key is wrong (401)",
                             404: "Groq says that AI model no longer exists (404)",
                             429: "Groq limit reached for now (429)"}.get(e.code, "Groq error %d" % e.code)
        return None, e.code
    except Exception:
        last_error["msg"] = "could not reach Groq (internet?)"
        return None, None


def chat(messages, model=None, json_mode=False, max_tokens=300, temperature=0.0, timeout=10):
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        last_error["msg"] = "no GROQ_API_KEY found"
        return None
    for m in _candidates(model):
        text, code = _request(m, messages, json_mode, max_tokens, temperature, timeout, key, False)
        if code == 400:                       # an option this model does not accept: plain call
            text, code = _request(m, messages, json_mode, max_tokens, temperature, timeout, key, True)
        if text:
            _working["model"] = m
            return text
        if code == 404:
            _dead.add(m)                      # retired: try the next model
            continue
        if code in (400, 204, 429, 500, 502, 503):
            continue                          # this model has a problem right now: try the next
        break                                 # no internet or wrong key: another model will not help
    return None
