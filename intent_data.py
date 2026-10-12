import json


class IntentDataError(Exception):
    """Raised when intents.json cannot be used for training."""


def normalize_phrase(phrase):
    # TfidfVectorizer lowercases text, so these are the same phrase to the model.
    return " ".join(phrase.lower().split())


def validate_intents(intents):
    """Return a list of problems found in already-loaded intent data."""
    if not isinstance(intents, dict):
        return [
            f"The top level must be an object mapping intent names to phrase lists, "
            f"but it is a {type(intents).__name__}."
        ]

    problems = []
    seen = {}  # normalized phrase -> intent that first used it
    valid_intents = 0

    for intent, phrases in intents.items():
        if not intent.strip():
            problems.append("Found an intent with an empty name.")
        if not isinstance(phrases, list):
            problems.append(
                f"Intent '{intent}' must have a list of phrases, but it has a "
                f"{type(phrases).__name__}."
            )
            continue
        if not phrases:
            problems.append(f"Intent '{intent}' has an empty phrase list.")
            continue

        intent_is_valid = True
        for position, phrase in enumerate(phrases, start=1):
            if not isinstance(phrase, str):
                problems.append(
                    f"Intent '{intent}', phrase #{position}: expected text but found "
                    f"{type(phrase).__name__} ({phrase!r})."
                )
                intent_is_valid = False
                continue
            if not phrase.strip():
                problems.append(f"Intent '{intent}', phrase #{position}: the phrase is blank.")
                intent_is_valid = False
                continue

            key = normalize_phrase(phrase)
            first_intent = seen.setdefault(key, intent)
            if first_intent != intent:
                problems.append(
                    f"The phrase '{phrase}' is listed under both '{first_intent}' and "
                    f"'{intent}', so the model cannot tell them apart."
                )

        if intent_is_valid:
            valid_intents += 1

    if not problems and valid_intents < 2:
        problems.append("Training needs at least two different intents.")

    return problems


def load_intents(path):
    """Read and validate an intents file, raising IntentDataError with a clear message."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            intents = json.load(f)
    except FileNotFoundError:
        raise IntentDataError(f"Could not find {path}. Run training from the project folder.")
    except json.JSONDecodeError as error:
        raise IntentDataError(
            f"{path} is not valid JSON: {error.msg} (line {error.lineno}, column {error.colno})."
        )
    except UnicodeDecodeError:
        raise IntentDataError(f"{path} must be saved as UTF-8 text.")
    except OSError as error:
        raise IntentDataError(f"Could not read {path}: {error.strerror or error}.")

    problems = validate_intents(intents)
    if problems:
        details = "\n".join(f"  - {problem}" for problem in problems)
        raise IntentDataError(f"{path} has {len(problems)} problem(s):\n{details}")

    return intents
