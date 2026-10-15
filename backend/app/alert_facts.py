"""Measured values an official NWS alert states in its own text (surf, tide, gusts, rain, snow), for number cards.

Only numbers written in the alert are used; a range shows its upper end, as the alert's "up to" value.
"""
import re

NUMBER = r'(\d+(?:\.\d+)?)'
RANGE = NUMBER + r'(?:\s*(?:to|-)\s*' + NUMBER + r')?'
PATTERNS = {
    'wave_ft': r'(?:waves?|surf|seas)\b[^.\n]{0,70}?' + RANGE + r'\s*(?:feet|foot|ft)\b',
    'tide_ft': r'\btides?\b[^.\n]{0,90}?' + RANGE + r'\s*(?:feet|foot|ft)\b',
    'gust_mph': r'\bgusts?\b[^.\n]{0,25}?' + RANGE + r'\s*(?:mph|miles per hour)',
    'snow_inches': r'\bsnow(?:fall)?\b[^.\n]{0,70}?' + RANGE + r'\s*inch',
    'rainfall_inches': r'\brain(?:fall)?\b[^.\n]{0,70}?' + RANGE + r'\s*inch',
}
KEYS = tuple(PATTERNS)


def extract(text):
    flat = re.sub(r'(?<=\d),(?=\d{3})', '', re.sub(r'\s+', ' ', text or ''))
    found = {}
    for key, pattern in PATTERNS.items():
        values = [float(high or low) for low, high in re.findall(pattern, flat, re.I)]
        if values:
            found[key] = max(values)
    return found
