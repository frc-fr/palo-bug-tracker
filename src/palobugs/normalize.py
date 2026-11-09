"""Name the hardware cited by the text of an issue.

The Release Notes of PAN-OS have no chapter per platform: an issue concerns a
model or a family only when its text names it, as "(PA-5420 firewalls only)".
A mention means "the notes cite it", never "only this model is affected".
"Panorama" alone names the software as often as the appliance: it is no family.
"""
import re
from typing import List, Set

PA_MODEL = re.compile(r"(?<![\w-])PA-(\d{3,4})(R?)(-5G)?(?![\w-])")
OTHER_MODEL = re.compile(r"(?<![\w-])(M-\d{3}|WF-?500(?:-?B)?|VM-(?:\d{2,4}|FLEX))(?![\w-])")
SERIES = re.compile(r"(?<![\w-])PA-(\d{3,4})(?:\s*|-)Series\b", re.I)
NAMED_FAMILIES = [
    (re.compile(r"\bVM-Series\b|(?<![\w-])PA-VM\b"), "VM-Series"),
    (re.compile(r"\bCN-Series\b|(?<![\w-])CN-(?:NGFW|MGMT)\b"), "CN-Series"),
    (re.compile(r"\bM-Series\b"), "M-Series"),
]
# Round numbers name a family, except these models.
ROUND_MODELS = {"200", "500", "7500"}


def pa_family(number: str) -> str:
    """PA-5420 is a PA-5400 Series, PA-455 a PA-400 Series; PA-5450 and PA-7500 are their own."""
    if number in ("5450", "7500"):
        return f"PA-{number} Series"
    head = number[:2] if len(number) == 4 else number[:1]
    return f"PA-{head}{'0' * (len(number) - len(head))} Series"


def family_of_model(model: str) -> str:
    match = re.fullmatch(r"PA-(\d{3,4})R?(?:-5G)?", model)
    if match:
        return pa_family(match.group(1))
    if model.startswith("M-"):
        return "M-Series"
    if model.startswith("WF-500"):
        return "WF-500"
    return "VM-Series"


def is_family_number(number: str) -> bool:
    return number.endswith("00") and number not in ROUND_MODELS


def strip_ids(text: str) -> str:
    """Issue IDs look like models (WF500-6271): they are removed before reading the text."""
    return re.sub(r"\b(?:PAN|WF500|GPC|PLUG|WIF|CYR|ADI|SA)-\d{3,7}\b", " ", text)


def canonical_model(raw: str) -> str:
    if raw.upper().startswith("WF"):
        return "WF-500-B" if raw.upper().endswith("B") else "WF-500"
    return raw


def models_in(text: str) -> List[str]:
    text = strip_ids(text)
    found: Set[str] = set()
    for number, rugged, cellular in PA_MODEL.findall(text):
        if not is_family_number(number) or rugged or cellular:
            found.add(f"PA-{number}{rugged}{cellular}")
    found.update(canonical_model(raw) for raw in OTHER_MODEL.findall(text))
    return sorted(found, key=model_key)


def families_in(text: str) -> List[str]:
    text = strip_ids(text)
    found: Set[str] = set()
    for number in SERIES.findall(text):
        found.add(pa_family(number))
    for number, rugged, cellular in PA_MODEL.findall(text):
        if is_family_number(number) and not rugged and not cellular:
            found.add(pa_family(number))
    for pattern, family in NAMED_FAMILIES:
        if pattern.search(text):
            found.add(family)
    return sorted(found, key=family_key)


def model_key(model: str):
    numbers = re.findall(r"\d+", model)
    return (model.split("-")[0], int(numbers[0]) if numbers else 0, model)


def family_key(family: str):
    numbers = re.findall(r"\d+", family)
    return (0 if family.startswith("PA-") else 1, int(numbers[0]) if numbers else 0, family)
