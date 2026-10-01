#!/usr/bin/env python3
"""Check the menu bar app's localizations (English and Simplified Chinese).

Fails when
  * a key used with NSLocalizedString("...") in macos/App/*.swift is missing
    from en.lproj or zh-Hans.lproj Localizable.strings,
  * a .strings file does not parse (plutil -lint),
  * the two Localizable.strings or InfoPlist.strings files have different keys,
  * a translation uses different printf-style format specifiers than its key.
Keys present in the .strings files but no longer used are reported as warnings.

Usage: python3 macos/Tools/check-localization.py [--list]
  --list   print the keys used in the Swift sources and exit
"""

import json
import re
import subprocess
import sys
from pathlib import Path

MACOS_DIR = Path(__file__).resolve().parents[1]
SOURCES = MACOS_DIR / "App"
RESOURCES = MACOS_DIR / "Resources"
LANGUAGES = ("en", "zh-Hans")

CALL = re.compile(r'NSLocalizedString\(\s*"((?:[^"\\\n]|\\.)*)"')
FORMAT = re.compile(r"%(?:\d+\$)?[-+ #0']*\d*(?:\.\d+)?(?:hh|h|ll|l|q|z|t|j)?([@dDiuUxXoOfeEgGcCsSpaA%])")
SWIFT_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "'": "'", "\\": "\\"}


def swift_unescape(literal):
    """Turns the text of a Swift string literal into the string it denotes."""

    result = []
    index = 0
    while index < len(literal):
        character = literal[index]
        if character != "\\":
            result.append(character)
            index += 1
            continue
        following = literal[index + 1] if index + 1 < len(literal) else ""
        if following == "u" and literal[index + 2:index + 3] == "{":
            end = literal.index("}", index)
            result.append(chr(int(literal[index + 3:end], 16)))
            index = end + 1
        elif following in SWIFT_ESCAPES:
            result.append(SWIFT_ESCAPES[following])
            index += 2
        else:
            raise ValueError("unsupported escape \\" + following)
    return "".join(result)


def used_keys():
    keys = {}
    for path in sorted(SOURCES.glob("*.swift")):
        text = path.read_text(encoding="utf-8")
        if "\\(" in "".join(CALL.findall(text)):
            raise SystemExit(f"{path.name}: NSLocalizedString keys must not use string interpolation")
        for match in CALL.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            keys.setdefault(swift_unescape(match.group(1)), f"{path.name}:{line}")
    return keys


def lint(path, problems):
    result = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        problems.append(f"{path.relative_to(MACOS_DIR)} does not parse: {(result.stdout + result.stderr).strip()}")
        return False
    return True


def load_strings(path, problems):
    if not path.is_file():
        problems.append(f"{path.relative_to(MACOS_DIR)} is missing")
        return {}
    if not lint(path, problems):
        return {}
    result = subprocess.run(["plutil", "-convert", "json", "-o", "-", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        problems.append(f"{path.relative_to(MACOS_DIR)} cannot be read: {result.stderr.strip()}")
        return {}
    return json.loads(result.stdout)


def specifiers(text):
    return sorted(conversion for conversion in FORMAT.findall(text) if conversion != "%")


def main():
    keys = used_keys()
    if "--list" in sys.argv[1:]:
        for key in sorted(keys):
            print(json.dumps(key, ensure_ascii=False))
        return 0

    problems = []
    warnings = []
    tables = {}
    for language in LANGUAGES:
        lproj = RESOURCES / f"{language}.lproj"
        tables[language] = load_strings(lproj / "Localizable.strings", problems)
        tables[f"{language}/InfoPlist"] = load_strings(lproj / "InfoPlist.strings", problems)

    for language in LANGUAGES:
        table = tables[language]
        for key, location in sorted(keys.items(), key=lambda item: item[1]):
            if key not in table:
                problems.append(f"{location}: {json.dumps(key, ensure_ascii=False)} is missing from {language}.lproj/Localizable.strings")
            elif specifiers(table[key]) != specifiers(key):
                problems.append(
                    f"{language}.lproj: format specifiers of {json.dumps(key, ensure_ascii=False)} do not match its translation"
                )
        for key in sorted(set(table) - set(keys)):
            warnings.append(f"{language}.lproj/Localizable.strings: unused key {json.dumps(key, ensure_ascii=False)}")

    first, second = LANGUAGES
    for suffix in ("", "/InfoPlist"):
        left, right = tables[first + suffix], tables[second + suffix]
        for key in sorted(set(left) ^ set(right)):
            owner = first if key in left else second
            problems.append(f"{json.dumps(key, ensure_ascii=False)} is only in {owner}.lproj/{'InfoPlist' if suffix else 'Localizable'}.strings")

    for warning in warnings:
        print("warning: " + warning)
    for problem in problems:
        print("error: " + problem)
    if problems:
        return 1
    print(f"Localization OK: {len(keys)} keys used in macos/App, present in {', '.join(LANGUAGES)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
