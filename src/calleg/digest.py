"""The Legislative Counsel's Digest from a bill version's XML: the plain summary of existing
law and of what the bill would do, printed at the top of every bill.

Bill XML (the BILL_VERSION_TBL_*.lob files in the leginfo export) marks it with a
LegislativeCounselDigest element or DigestText paragraphs. Older exports that lack it fall back to the text between
"LEGISLATIVE COUNSEL'S DIGEST" and the digest key ("Vote:") or the enacting clause."""
from __future__ import annotations

import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ELEM = re.compile(r"<(?:\w+:)?LegislativeCounselDigest\b[^>]*>(.*?)</(?:\w+:)?LegislativeCounselDigest>", re.S | re.I)
_DTEXT = re.compile(r"<(?:\w+:)?DigestText\b[^>]*>(.*?)</(?:\w+:)?DigestText>", re.S | re.I)
_DIGEST_KEY = re.compile(r"<(?:\w+:)?DigestKey\b.*?</(?:\w+:)?DigestKey>", re.S | re.I)
_TEXT = re.compile(r"LEGISLATIVE COUNSEL[’'`]?S DIGEST(.*?)(?:Vote:|DIGEST KEY|The people of the State of California do enact)", re.S | re.I)
MAX_CHARS = 4000   # the summary of what the bill does comes first; very long digests are cut


def clean(s: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", s)).strip()


def extract(xml: str) -> str:
    m = _ELEM.search(xml)
    if m:
        return clean(_DIGEST_KEY.sub(" ", m.group(1)))[:MAX_CHARS]
    parts = _DTEXT.findall(xml)
    if parts:
        return clean(" ".join(parts))[:MAX_CHARS]
    m = _TEXT.search(clean(xml))
    return m.group(1).strip(" :")[:MAX_CHARS] if m else ""
