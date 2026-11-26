"""Privacy Shield (Feature D): hide personal data before anything goes to a cloud provider.

Applies only to cloud providers. Each value becomes a stable placeholder for the request ([PHONE_1]
everywhere the same number appears). The placeholder -> value map never leaves this PC: the server
sends it to the page (localhost) so the page can show real values, and saves the answer with real values.

Detectors (in this order, so a longer pattern wins over a shorter one inside it):
  email, UPI ID (known handles), card number (13-19 digits, Luhn), Aadhaar (12 digits starting 2-9;
  4-4-4 grouping, or an ungrouped 12-digit run that passes Verhoeff), PAN, IFSC, Indian mobile number.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Tuple

UPI_HANDLES = sorted("""okhdfcbank okicici oksbi okaxis ybl ibl axl paytm upi apl ptyes ptaxis pthdfc ptsbi icici hdfcbank sbi
axisbank kotak yesbank yesbankltd barodampay aubank idfcbank idfcfirst indus federal rbl jupiteraxis fam slice naviaxis
waaxis wahdfcbank waicici wasbi airtel airtelpaymentsbank freecharge jio timecosmos pingpay abfspay icicipay axisb
dbs hsbc citi citigold kmbl kbl kvb uboi unionbank pnb boi cnrb centralbank indianbank iob psb ucobank mahb""".split(),
                     key=len, reverse=True)

NAMES = {"EMAIL": ("email address", "email addresses"), "UPI": ("UPI ID", "UPI IDs"), "CARD": ("card number", "card numbers"),
         "AADHAAR": ("Aadhaar number", "Aadhaar numbers"), "PAN": ("PAN", "PANs"), "IFSC": ("IFSC code", "IFSC codes"),
         "PHONE": ("phone number", "phone numbers")}
ORDER = ["EMAIL", "UPI", "CARD", "AADHAAR", "PAN", "IFSC", "PHONE"]

EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
UPI = re.compile(r"(?<![\w.-])[A-Za-z0-9][A-Za-z0-9._-]{1,255}@(?:" + "|".join(map(re.escape, UPI_HANDLES)) + r")(?![\w.@-])", re.I)
CARD = re.compile(r"(?<![\d-])(?<!\d )\d(?:[ -]?\d){12,18}(?![\d])(?! \d)(?!-\d)")
AADHAAR_GROUPED = re.compile(r"(?<![\d-])(?<!\d )[2-9]\d{3}([ -])\d{4}\1\d{4}(?!\d)(?! \d)(?!-\d)")
AADHAAR_PLAIN = re.compile(r"(?<![\w-])[2-9]\d{11}(?![\w])")
PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
PHONE = re.compile(r"(?<![\w+])(?:(?:\+91|91)[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?![\w])")
PLACEHOLDER = re.compile(r"(?:\[\s*)?\b(EMAIL|UPI|CARD|AADHAAR|PAN|IFSC|PHONE)[ _-]?(\d{1,4})\b(?:\s*\])?", re.I)


def luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
       [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
       [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
       [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VD[c][_VP[i % 8][ord(ch) - 48]]
    return c == 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class Shield:
    """One per request: masks text, remembers placeholder <-> value, restores answers."""

    def __init__(self):
        self.by_value: Dict[Tuple[str, str], str] = {}  # (type, normalised value) -> placeholder
        self.values: Dict[str, str] = {}                 # placeholder -> original text (first seen form)
        self.counts: Counter = Counter()

    def _ph(self, kind: str, raw: str) -> str:
        norm = raw.lower() if kind in ("EMAIL", "UPI") else (_digits(raw) if kind in ("CARD", "AADHAAR", "PHONE") else raw.upper())
        if kind == "PHONE":
            norm = norm[-10:]  # +91 / 0 prefixes are the same number
        key = (kind, norm)
        if key not in self.by_value:
            self.counts[kind] += 1
            ph = f"[{kind}_{self.counts[kind]}]"
            self.by_value[key] = ph
            self.values[ph] = raw
        return self.by_value[key]

    def mask(self, text: str) -> str:
        if not text:
            return text

        def sub(rx, kind, ok=None):
            nonlocal text

            def rep(m):
                raw = m.group(0)
                if ok and not ok(raw):
                    return raw
                return self._ph(kind, raw)
            text = rx.sub(rep, text)

        sub(EMAIL, "EMAIL")
        sub(UPI, "UPI")
        sub(CARD, "CARD", lambda r: 13 <= len(_digits(r)) <= 19 and luhn(_digits(r)))
        sub(AADHAAR_GROUPED, "AADHAAR")
        sub(AADHAAR_PLAIN, "AADHAAR", lambda r: verhoeff(r))
        sub(PAN, "PAN")
        sub(IFSC, "IFSC")
        sub(PHONE, "PHONE")
        return text

    def found(self) -> Counter:
        c = Counter()
        for ph in self.values:
            c[ph.strip("[]").rsplit("_", 1)[0]] += 1
        return c

    def summary(self, provider: str) -> str:
        c = self.found()
        if not c:
            return ""
        parts = []
        for k in sorted((k for k in ORDER if c[k]), key=lambda k: (-c[k], ORDER.index(k))):  # most frequent first
            one, many = NAMES[k]
            parts.append(f"{c[k]} {one if c[k] == 1 else many}")
        listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        return f"Privacy Shield hid {listed} before sending to {provider}."

    def unmask(self, text: str) -> str:
        return unmask(text, self.values)


def unmask(text: str, values: Dict[str, str]) -> str:
    """Put real values back, tolerating small changes the model makes ([PHONE 1], PHONE_1, [phone-1])."""
    if not text or not values:
        return text
    canon = {k.strip("[]").upper(): v for k, v in values.items()}

    def rep(m):
        key = f"{m.group(1).upper()}_{m.group(2)}"
        return canon.get(key, m.group(0))
    return PLACEHOLDER.sub(rep, text)
