"""MoneyTwin planning engine.

Every number the user sees comes from this file: plain Python, no AI.
simulate() builds a day-by-day balance; metrics() reads it; find_plans()
searches only the changes the user allows; analyze() packages the answer.
"""
from __future__ import annotations

import itertools
import math
import re
from datetime import date, timedelta

MAX_HORIZON = 90


class ValidationError(Exception):
    def __init__(self, errors):
        super().__init__("invalid input")
        self.errors = errors


# ---------- formatting ----------
def inr(x: float) -> str:
    x = round(x)
    s = str(abs(int(x)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        s = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head) + "," + tail
    return ("-" if x < 0 else "") + "₹" + s


def fd(d) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.day} {d:%b}"


# ---------- demo data ----------
def demo(today: date | None = None) -> dict:
    t = today or date.today()
    iso = lambda n: (t + timedelta(days=n)).isoformat()
    return {
        "start": iso(0), "balance": 4500, "buffer": 500,
        "income": {"amount": 8000, "next_date": iso(10), "cycle_days": 30},
        "bills": [{"name": "Phone + data plan", "amount": 450, "date": iso(6), "refund": False}],
        "categories": [
            {"name": "Food", "daily": 90, "protected": True},
            {"name": "Travel", "daily": 40, "protected": True},
            {"name": "Eating out", "daily": 45, "protected": False},
            {"name": "Entertainment", "daily": 25, "protected": False},
        ],
        "savings": {"goal_name": "Laptop fund", "goal": 10000, "saved": 2000, "contribution": 1000},
        "purchase": {"name": "Headphones", "amount": 1800, "date": iso(0)},
        "within_days": 20, "min_price_pct": 60,
    }


# ---------- validation (meaning-aware, never crashes) ----------
def _num(v, field, errs, lo=None, hi=None, required=True):
    if v is None or v == "" or isinstance(v, bool):
        if required:
            errs.append({"field": field, "message": "Enter a value."})
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        errs.append({"field": field, "message": "Must be a number."})
        return None
    if math.isnan(n) or math.isinf(n):
        errs.append({"field": field, "message": "Must be a finite number."})
        return None
    if lo is not None and n < lo:
        errs.append({"field": field, "message": f"Must be at least {lo:g}."})
    if hi is not None and n > hi:
        errs.append({"field": field, "message": f"Must be at most {hi:g}."})
    return n


def _date(v, field, errs):
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        errs.append({"field": field, "message": "Pick a valid date."})
        return None


def validate(raw) -> dict:
    errs: list = []
    r = raw if isinstance(raw, dict) else {}
    cfg = {
        "start": _date(r.get("start"), "start", errs),
        # an opening balance may legitimately be negative
        "balance": _num(r.get("balance"), "balance", errs, lo=-1e7, hi=1e9),
        "buffer": _num(r.get("buffer"), "buffer", errs, lo=0, hi=1e9),
    }
    inc = r.get("income") if isinstance(r.get("income"), dict) else {}
    income = {
        "amount": _num(inc.get("amount"), "income.amount", errs, lo=0, hi=1e9),
        "next_date": _date(inc.get("next_date"), "income.next_date", errs),
        "cycle_days": _num(inc.get("cycle_days"), "income.cycle_days", errs, lo=1, hi=90),
    }
    if cfg["start"] and income["next_date"] and income["next_date"] < cfg["start"]:
        errs.append({"field": "income.next_date", "message": "Allowance date can't be before today's date."})
    cfg["income"] = income

    bills = []
    for i, b in enumerate(r.get("bills") or []):
        b = b if isinstance(b, dict) else {}
        refund = bool(b.get("refund"))
        amt = _num(b.get("amount"), f"bills.{i}.amount", errs)
        if amt is not None and amt < 0 and not refund:
            errs.append({"field": f"bills.{i}.amount",
                         "message": "Expenses can't be negative. Tick 'refund' if money is coming back."})
        if refund and amt is not None:
            amt = -abs(amt)
        if not str(b.get("name", "")).strip():
            errs.append({"field": f"bills.{i}.name", "message": "Name this bill."})
        bills.append({"name": str(b.get("name", "")).strip(), "amount": amt,
                      "date": _date(b.get("date"), f"bills.{i}.date", errs), "refund": refund})
    cfg["bills"] = bills

    cats, seen = [], set()
    for i, c in enumerate(r.get("categories") or []):
        c = c if isinstance(c, dict) else {}
        name = str(c.get("name", "")).strip()
        if not name:
            errs.append({"field": f"categories.{i}.name", "message": "Name this category."})
        elif name.lower() in seen:
            errs.append({"field": f"categories.{i}.name", "message": "Category names must be unique."})
        seen.add(name.lower())
        cats.append({"name": name, "daily": _num(c.get("daily"), f"categories.{i}.daily", errs, lo=0, hi=1e7),
                     "protected": bool(c.get("protected"))})
    cfg["categories"] = cats

    s = r.get("savings") if isinstance(r.get("savings"), dict) else {}
    cfg["savings"] = {"goal_name": str(s.get("goal_name") or "Savings goal"),
                      "goal": _num(s.get("goal"), "savings.goal", errs, lo=0),
                      "saved": _num(s.get("saved"), "savings.saved", errs, lo=0),
                      "contribution": _num(s.get("contribution"), "savings.contribution", errs, lo=0)}

    p = r.get("purchase") if isinstance(r.get("purchase"), dict) else {}
    cfg["purchase"] = {"name": str(p.get("name") or "").strip(),
                       "amount": _num(p.get("amount"), "purchase.amount", errs, lo=0.01, hi=1e9),
                       "date": _date(p.get("date"), "purchase.date", errs)}
    if not cfg["purchase"]["name"]:
        errs.append({"field": "purchase.name", "message": "What are you buying?"})
    wd = _num(r.get("within_days"), "within_days", errs, lo=1, hi=MAX_HORIZON)
    cfg["within_days"] = int(wd) if wd is not None else 20
    mp = _num(r.get("min_price_pct", 60), "min_price_pct", errs, lo=10, hi=100)
    cfg["min_price_pct"] = mp if mp is not None else 60

    if not errs:
        n = horizon_days(cfg)
        off = (cfg["purchase"]["date"] - cfg["start"]).days
        if off < 0 or off > n:
            errs.append({"field": "purchase.date",
                         "message": f"Pick a date between today and {fd(cfg['start'] + timedelta(days=n))} (forecast window)."})
    if errs:
        raise ValidationError(errs)
    return cfg


def clean_scn(raw) -> dict:
    r = raw if isinstance(raw, dict) else {}
    errs = []
    s = {"delay_days": _num(r.get("delay_days", 0), "scenario.delay_days", errs, lo=0, hi=14) or 0,
         "extra_expense": _num(r.get("extra_expense", 0), "scenario.extra_expense", errs, lo=0, hi=1e9) or 0,
         "travel_increase": _num(r.get("travel_increase", 0), "scenario.travel_increase", errs, lo=0, hi=1e6) or 0,
         "income_cut": _num(r.get("income_cut", 0), "scenario.income_cut", errs, lo=0, hi=1e9) or 0}
    if errs:
        raise ValidationError(errs)
    s["delay_days"] = int(s["delay_days"])
    return s


def clean_adj(raw, cfg) -> dict:
    r = raw if isinstance(raw, dict) else {}
    cuts = {}
    protected = {c["name"] for c in cfg["categories"] if c["protected"]}
    for k, v in (r.get("cuts") or {}).items():
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if k not in protected and v > 0:        # protected categories can never be cut
            cuts[k] = min(v, 100.0)
    so = r.get("savings_override")
    try:
        so = None if so in (None, "") else max(float(so), 0.0)
    except (TypeError, ValueError):
        so = None
    return {"cuts": cuts, "savings_override": so}


# ---------- simulation ----------
def horizon_days(cfg) -> int:
    return min((cfg["income"]["next_date"] - cfg["start"]).days + 20, MAX_HORIZON)


def simulate(cfg, scn, adj, buy=None):
    """Day-by-day closing balances. buy = (date, amount) or None."""
    start, n, inc = cfg["start"], horizon_days(cfg), cfg["income"]
    contrib = adj["savings_override"] if adj["savings_override"] is not None else cfg["savings"]["contribution"]
    cats, has_travel = [], False
    for c in cfg["categories"]:
        d = c["daily"]
        if not c["protected"]:
            d *= 1 - adj["cuts"].get(c["name"], 0) / 100
        if "travel" in c["name"].lower():
            d += scn["travel_increase"]
            has_travel = True
        cats.append((c["name"], d))
    if scn["travel_increase"] and not has_travel:
        cats.append(("Extra travel", scn["travel_increase"]))

    income_days, k = set(), 0
    while True:
        off = (inc["next_date"] - start).days + int(k * inc["cycle_days"]) + scn["delay_days"]
        if off > n:
            break
        income_days.add(off)
        k += 1
    bills = {}
    for b in cfg["bills"]:
        bills.setdefault((b["date"] - start).days, []).append(b)
    buy_off = (buy[0] - start).days if buy else None

    bal, days = cfg["balance"], []
    for i in range(n + 1):
        ev = []
        if i in income_days:
            ev.append(("Allowance arrives", max(inc["amount"] - scn["income_cut"], 0)))
            if contrib:
                ev.append(("Savings transfer", -contrib))
        for b in bills.get(i, []):
            ev.append((("Refund: " if b["amount"] < 0 else "Bill: ") + b["name"], -b["amount"]))
        if i == 1 and scn["extra_expense"]:
            ev.append(("Unexpected expense", -scn["extra_expense"]))
        if i == buy_off:
            ev.append(("Purchase: " + cfg["purchase"]["name"], -buy[1]))
        ev += [(nm, -d) for nm, d in cats if d > 0]
        bal += sum(a for _, a in ev)
        days.append({"date": (start + timedelta(days=i)).isoformat(), "balance": round(bal, 2),
                     "events": [{"label": l, "amount": round(a, 2)} for l, a in ev]})
    return days


def metrics(days, buffer):
    fb = next((d["date"] for d in days if d["balance"] < buffer), None)
    fz = next((d["date"] for d in days if d["balance"] < 0), None)
    low = min(days, key=lambda d: d["balance"])
    return {"first_below_buffer": fb, "first_below_zero": fz, "lowest": low["balance"],
            "lowest_date": low["date"], "buffer_ok": fb is None}


def status(m):
    if m["first_below_zero"]:
        return {"level": "zero", "text": f"Runs out on {fd(m['first_below_zero'])}"}
    if m["first_below_buffer"]:
        return {"level": "buffer", "text": f"Below buffer on {fd(m['first_below_buffer'])}"}
    return {"level": "ok", "text": f"Buffer intact (lowest {inr(m['lowest'])})"}


def goal_info(cfg, scn, adj):
    s, inc = cfg["savings"], cfg["income"]
    c = adj["savings_override"] if adj["savings_override"] is not None else s["contribution"]
    remaining = s["goal"] - s["saved"]
    if remaining <= 0:
        return {"status": "reached", "date": None, "contribution": c}
    if c <= 0:
        return {"status": "paused", "date": None, "contribution": c}
    n = math.ceil(remaining / c)
    d = inc["next_date"] + timedelta(days=scn["delay_days"] + int((n - 1) * inc["cycle_days"]))
    return {"status": "on_track", "date": d.isoformat(), "contribution": c}


# ---------- plan finder: searches ONLY allowed changes ----------
def _run(cfg, scn, adj, off, amount):
    days = simulate(cfg, scn, adj, (cfg["start"] + timedelta(days=off), amount))
    return metrics(days, cfg["buffer"])


def find_plans(cfg, scn, adj, cmp_):
    n, buf, amt = horizon_days(cfg), cfg["buffer"], cfg["purchase"]["amount"]
    sel = (cfg["purchase"]["date"] - cfg["start"]).days
    base_adj = {"cuts": {}, "savings_override": None}
    late = {**scn, "delay_days": max(scn["delay_days"], cmp_["delay_days"])}
    protected = [c["name"] for c in cfg["categories"] if c["protected"]] + ["Bills", f"{inr(buf)} buffer"]
    plans, none_reason = [], None

    # 1) earliest feasible purchase date
    found = next((o for o in range(n + 1) if _run(cfg, scn, base_adj, o, amt)["buffer_ok"]), None)
    if found is None:
        m = _run(cfg, scn, base_adj, n, amt)
        none_reason = (f"Even buying on {fd(cfg['start'] + timedelta(days=n))}, your balance drops below the "
                       f"{inr(buf)} buffer on {fd(m['first_below_buffer'])}. Try a lower price, a smaller buffer, "
                       f"or adjusting a flexible category.")
    else:
        d = cfg["start"] + timedelta(days=found)
        robust = _run(cfg, late, base_adj, found, amt)["buffer_ok"]
        late_note = ("Still safe if the allowance is late." if robust
                     else f"Would not survive an allowance {late['delay_days']} days late.")
        within = found <= cfg["within_days"]
        summary = (f"Buy on {fd(d)}: the first date that keeps your balance above {inr(buf)}. " + late_note)
        if not within:
            summary += f" This is after your {cfg['within_days']}-day deadline."
        plans.append({"key": "earliest", "title": f"Wait until {fd(d)}", "summary": summary,
                      "changes": [f"Purchase date → {fd(d)}"], "protected": protected, "robust": robust,
                      "apply": {"date": d.isoformat()}})

    sel_ok = _run(cfg, scn, base_adj, sel, amt)["buffer_ok"]
    if not sel_ok:
        # 2) lower price on the chosen date
        step = 10 if amt < 5000 else 50
        floor = amt * cfg["min_price_pct"] / 100
        p = amt - step
        while p >= floor:
            if _run(cfg, scn, base_adj, sel, p)["buffer_ok"]:
                plans.append({"key": "price", "title": f"Spend {inr(p)} instead",
                              "summary": f"On {fd(cfg['start'] + timedelta(days=sel))}, a price up to {inr(p)} fits "
                                         f"({inr(amt - p)} less).",
                              "changes": [f"Price {inr(amt)} → {inr(p)}"], "protected": protected,
                              "robust": _run(cfg, late, base_adj, sel, p)["buffer_ok"],
                              "apply": {"amount": p}})
                break
            p -= step
        # 3) fewest lifestyle changes (only categories the user marked adjustable)
        adjustable = [c["name"] for c in cfg["categories"] if not c["protected"] and c["daily"] > 0]
        best = None
        for size in range(1, len(adjustable) + 1):
            for combo in itertools.combinations(adjustable, size):
                for pct in range(10, 101, 10):
                    cuts = {k: pct for k in combo}
                    if _run(cfg, scn, {"cuts": cuts, "savings_override": None}, sel, amt)["buffer_ok"]:
                        if best is None or pct < best[0]:
                            best = (pct, combo)
                        break
            if best:
                break
        if best:
            pct, combo = best
            plans.append({"key": "cuts", "title": "Trim " + " & ".join(combo),
                          "summary": f"Cut {', '.join(combo)} by {pct}% and buy on "
                                     f"{fd(cfg['start'] + timedelta(days=sel))}.",
                          "changes": [f"{k} −{pct}%" for k in combo], "protected": protected,
                          "robust": _run(cfg, late, {"cuts": {k: pct for k in combo}, "savings_override": None},
                                         sel, amt)["buffer_ok"],
                          "apply": {"cuts": {k: pct for k in combo}}})
        # 4) temporarily lower the savings transfer (shows the delayed goal date)
        c0 = cfg["savings"]["contribution"]
        for c in range(int(c0) - 250, -1, -250):
            a2 = {"cuts": {}, "savings_override": float(c)}
            if _run(cfg, scn, a2, sel, amt)["buffer_ok"]:
                g0, g1 = goal_info(cfg, scn, base_adj), goal_info(cfg, scn, a2)
                when = f"{cfg['savings']['goal_name']} moves from {fd(g0['date'])} to {fd(g1['date'])}" \
                    if g1["date"] and g0["date"] else f"{cfg['savings']['goal_name']} is paused"
                plans.append({"key": "savings", "title": f"Save {inr(c)} instead of {inr(c0)}",
                              "summary": f"Lower the transfer and buy on time. {when}.",
                              "changes": [f"Savings transfer {inr(c0)} → {inr(c)}"], "protected": protected,
                              "robust": _run(cfg, late, a2, sel, amt)["buffer_ok"],
                              "apply": {"savings_override": c}})
                break
    return plans, none_reason, sel_ok


# ---------- full analysis ----------
def analyze(body) -> dict:
    body = body if isinstance(body, dict) else {}
    cfg = validate(body.get("inputs"))
    scn, adj = clean_scn(body.get("scenario")), None
    adj = clean_adj(body.get("adjust"), cfg)
    errs = []
    c = body.get("compare") if isinstance(body.get("compare"), dict) else {}
    cmp_ = {"delay_days": int(_num(c.get("delay_days", 7), "compare.delay_days", errs, lo=1, hi=14) or 7),
            "income_cut": _num(c.get("income_cut", 1500), "compare.income_cut", errs, lo=0) or 0}
    if errs:
        raise ValidationError(errs)

    p = cfg["purchase"]
    buy = (p["date"], p["amount"])
    cur_days, prop_days = simulate(cfg, scn, adj, None), simulate(cfg, scn, adj, buy)
    mc, mp = metrics(cur_days, cfg["buffer"]), metrics(prop_days, cfg["buffer"])

    variants = [("expected", "Allowance on time", {**scn, "delay_days": 0, "income_cut": 0}),
                ("delayed", f"Allowance {cmp_['delay_days']} days late", {**scn, "delay_days": cmp_["delay_days"], "income_cut": 0}),
                ("lower", f"Allowance {inr(cmp_['income_cut'])} lower", {**scn, "delay_days": 0, "income_cut": cmp_["income_cut"]})]
    rows = []
    for key, label, s in variants:
        rc, rp = metrics(simulate(cfg, s, adj, None), cfg["buffer"]), metrics(simulate(cfg, s, adj, buy), cfg["buffer"])
        rows.append({"key": key, "label": label, "current": status(rc), "decision": status(rp)})

    plans, none_reason, sel_ok = find_plans(cfg, scn, adj, cmp_)
    goal = goal_info(cfg, scn, adj)
    first_income = next((d["date"] for d in prop_days for e in d["events"] if e["label"] == "Allowance arrives"), None)

    # plain-language explanation built from the numbers above
    L, name, pd = [], p["name"], fd(p["date"])
    if mp["first_below_buffer"]:
        t = f"Buying {name} ({inr(p['amount'])}) on {pd} would put your projected balance below your {inr(cfg['buffer'])} buffer on {fd(mp['first_below_buffer'])}"
        if first_income and mp["first_below_buffer"] < first_income:
            gap = (date.fromisoformat(first_income) - date.fromisoformat(mp["first_below_buffer"])).days
            t += f", {gap} day{'s' if gap != 1 else ''} before your allowance arrives on {fd(first_income)}"
        L.append({"tone": "bad", "text": t + "."})
        if mp["first_below_zero"]:
            L.append({"tone": "bad", "text": f"It would also take you below ₹0 on {fd(mp['first_below_zero'])}."})
    else:
        L.append({"tone": "ok", "text": f"Buying {name} on {pd} keeps you above your {inr(cfg['buffer'])} buffer. "
                                        f"Lowest projected balance: {inr(mp['lowest'])} on {fd(mp['lowest_date'])}."})
    L.append({"tone": "info", "text": f"Lowest balance without the purchase: {inr(mc['lowest'])}; with it: {inr(mp['lowest'])}."})
    if rows[0]["decision"]["level"] == "ok":
        for r in rows[1:]:
            if r["decision"]["level"] != "ok":
                L.append({"tone": "warn", "text": f"This works if the allowance is on time, but not under “{r['label']}”: {r['decision']['text'].lower()}."})
    if goal["status"] == "on_track":
        L.append({"tone": "info", "text": f"{cfg['savings']['goal_name']}: on track for {fd(goal['date'])} at {inr(goal['contribution'])} per allowance."})
    elif goal["status"] == "paused":
        L.append({"tone": "warn", "text": f"{cfg['savings']['goal_name']} is paused while the transfer is ₹0."})

    # assumptions shown in full, not hidden in a disclaimer
    A = [f"Today is {fd(cfg['start'])}; opening balance {inr(cfg['balance'])}.",
         f"Allowance {inr(cfg['income']['amount'])} arrives {fd(cfg['income']['next_date'])} and every {int(cfg['income']['cycle_days'])} days.",
         "Daily spending: " + ", ".join(f"{c['name']} {inr(c['daily'])}" + (" (protected)" if c["protected"] else "") for c in cfg["categories"]) + ".",
         "Bills: " + (", ".join(f"{b['name']} {inr(b['amount'])} on {fd(b['date'])}" for b in cfg["bills"]) or "none") + ".",
         f"Savings transfer {inr(goal['contribution'])} leaves on each allowance day.",
         f"Forecast window: {horizon_days(cfg)} days. These are hypothetical scenarios, not predictions."]
    if scn["delay_days"]: A.append(f"Scenario on: allowance {scn['delay_days']} days late.")
    if scn["extra_expense"]: A.append(f"Scenario on: unexpected {inr(scn['extra_expense'])} expense tomorrow.")
    if scn["travel_increase"]: A.append(f"Scenario on: travel +{inr(scn['travel_increase'])} per day.")
    if scn["income_cut"]: A.append(f"Scenario on: allowance {inr(scn['income_cut'])} lower.")
    if adj["cuts"]: A.append("Cuts applied: " + ", ".join(f"{k} −{v:g}%" for k, v in adj["cuts"].items()) + ".")

    earliest = next((x for x in plans if x["key"] == "earliest"), None)
    if mp["buffer_ok"]:
        chosen, reason = f"Buy on {pd} as planned", "keeps your balance above the buffer in the entered scenario"
    elif earliest:
        chosen, reason = earliest["title"], "it is the first purchase date that keeps your balance above the buffer"
    else:
        chosen, reason = "No feasible plan under these constraints", none_reason
    changes = [f"If “{r['label']}”: {r['decision']['text']}." for r in rows[1:] if r["decision"]["text"] != rows[0]["decision"]["text"]]
    receipt = {"purchase": f"{name} ({inr(p['amount'])})", "selected_plan": chosen, "reason": reason,
               "protected": [c["name"] for c in cfg["categories"] if c["protected"]] + ["Bills"],
               "assumptions": A[:5], "what_would_change": changes + ["Edit any number above (buffer, allowance date, daily spending) and the plan reruns."]}

    return {"horizon": horizon_days(cfg), "buffer": cfg["buffer"], "balance": cfg["balance"],
            "next_income": first_income, "delay_days": scn["delay_days"],
            "current": {"days": [{"date": d["date"], "balance": d["balance"]} for d in cur_days], "metrics": mc},
            "proposed": {"days": prop_days, "metrics": mp},
            "scenarios": rows, "plans": plans, "no_plan_reason": none_reason, "chosen_date_ok": sel_ok,
            "goal": goal, "explanation": L, "assumptions": A, "receipt": receipt,
            "adjustable": [c["name"] for c in cfg["categories"] if not c["protected"]]}
