"""Optional AI helpers. AI only reads language; engine.py does all arithmetic.
Both helpers fall back gracefully, so the app works with no key or no internet."""
import json
import os
import re
import urllib.request

MODEL = os.environ.get("MONEYTWIN_MODEL", "claude-sonnet-5-5")
URL = "https://api.anthropic.com/v1/messages"


def _call(system: str, user: str, max_tokens=400) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY set")
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return "".join(b.get("text", "") for b in json.load(r)["content"])


# ---------- goal parsing ----------
def _money(s):
    return float(s.replace(",", ""))


def rules_parse(text: str, cats: list) -> dict:
    """Offline fallback: regex reader for sentences like
    'I want ₹1,800 headphones within 20 days. Don't reduce food or travel, keep ₹500 untouched.'"""
    t, f = " " + text + " ", {"purchase_name": None, "amount": None, "within_days": None,
                              "minimum_balance": None, "protected_categories": []}
    cur = r"(?:₹|rs\.?|inr)?\s*"
    for pat in (rf"(?:keep|maintain|leave|protect)\s+(?:at least\s+)?{cur}([\d,]+)\s*(?:untouched|aside|safe|as (?:a )?buffer|minimum)?",
                rf"(?:minimum balance|buffer)\s+(?:of\s+)?{cur}([\d,]+)", rf"{cur}([\d,]+)\s*(?:buffer|untouched)"):
        m = re.search(pat, t, re.I)
        if m and m.group(1).strip(","):
            f["minimum_balance"] = _money(m.group(1))
            t = t.replace(m.group(0), " ")
            break
    m = re.search(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", t, re.I) or re.search(r"\b(\d[\d,]{2,})\b(?!\s*days?)", t)
    if m:
        f["amount"] = _money(m.group(1))
        t = t.replace(m.group(0), " ", 1)
    m = re.search(r"(?:within|in|by)\s+(\d+)\s*(day|week)s?", t, re.I)
    if m:
        f["within_days"] = int(m.group(1)) * (7 if m.group(2).lower() == "week" else 1)
    m = re.search(r"(?:want|need|buy|get|purchase)\s+(?:to buy\s+)?(?:a|an|the|these|some|new)?\s*"
                  r"([a-z][a-z0-9 \-]{1,30}?)(?=\s+(?:within|in|by|for|before|without|but|and)\b|[.,;]|\s*$)", t, re.I)
    if m:
        f["purchase_name"] = m.group(1).strip().title()
    if re.search(r"don'?t|do not|without|never|not (?:touch|reduce|cut)|protect", t, re.I):
        f["protected_categories"] = [c for c in cats if re.search(rf"\b{re.escape(c.lower())}\b", t.lower())]
    return f


def _clean(f: dict, cats: list) -> dict:
    """Validate whatever came back (AI or rules). Unknown or invalid values become None, never guesses."""
    def pos(v, ints=False):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return (int(v) if ints else v) if v > 0 else None
    low = {c.lower(): c for c in cats}
    prot = [low[str(c).lower()] for c in (f.get("protected_categories") or []) if str(c).lower() in low]
    mb = f.get("minimum_balance")
    try:
        mb = float(mb) if mb is not None and float(mb) >= 0 else None
    except (TypeError, ValueError):
        mb = None
    name = f.get("purchase_name")
    return {"purchase_name": str(name).strip()[:40] if name else None, "amount": pos(f.get("amount")),
            "within_days": pos(f.get("within_days"), True), "minimum_balance": mb, "protected_categories": prot}


def parse_goal(text: str, cats: list) -> dict:
    system = ("Extract a purchase goal from the user's sentence. Reply with ONLY a JSON object with keys: "
              "purchase_name (string|null), amount (number in rupees|null), within_days (integer|null), "
              "protected_categories (array chosen only from the allowed list), minimum_balance (number|null). "
              "Use null when something is not stated. Never guess or invent values. Allowed categories: " + json.dumps(cats))
    try:
        raw = re.sub(r"^```(?:json)?|```$", "", _call(system, text[:600]).strip(), flags=re.M).strip()
        fields, source, note = _clean(json.loads(raw), cats), "ai", None
    except Exception as e:  # no key, offline, bad JSON ... -> offline reader
        fields, source = _clean(rules_parse(text, cats), cats), "rules"
        note = "AI was unavailable, so the built-in reader handled this. Please check the fields."
    missing = [k for k in ("purchase_name", "amount") if not fields[k]]
    return {"fields": fields, "source": source, "note": note, "missing": missing}


# ---------- friendly explanation ----------
def friendly_explain(lines: list) -> str:
    """Rewrite already-calculated lines in a warmer voice. Rejected if it introduces any new number."""
    src = " ".join(lines)
    out = _call("Rewrite these calculated budgeting facts as 2-4 friendly sentences for a student. "
                "Do not add, change or round any number or date. Do not give orders; describe trade-offs.", src).strip()
    nums = lambda s: set(re.findall(r"\d[\d,]*", s))
    if not nums(out) <= nums(src):
        raise ValueError("AI introduced numbers that were not calculated")
    return out
