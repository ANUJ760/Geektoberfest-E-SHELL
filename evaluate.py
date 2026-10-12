"""Measure how the saved intent model handles phrases it was never trained on.

Usage:
    venv/bin/python evaluate.py
    venv/bin/python evaluate.py --markdown docs/model-evaluation.md

The test phrases live in evaluation_phrases.json, separate from intents.json.
The key "unknown" holds out-of-scope requests that should be refused.
"""
import argparse
import math
import platform
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from intent_data import IntentDataError, load_intents, normalize_phrase

BASE_DIR = Path(__file__).resolve().parent
UNKNOWN = "unknown"


@dataclass
class Prediction:
    phrase: str
    expected: str
    predicted: str  # what E-SHELL would act on: the top intent, or "unknown" below the threshold
    top_label: str  # the highest-scoring intent, ignoring the threshold
    confidence: float  # probability of top_label, not a calibrated chance of being right

    @property
    def correct(self):
        return self.predicted == self.expected

    @property
    def abstained(self):
        return self.predicted == UNKNOWN and self.expected != UNKNOWN

    @property
    def misrouted(self):
        """A different real intent was chosen, so the wrong command would run."""
        return self.predicted not in (self.expected, UNKNOWN)


def predict_with_confidence(text):
    """Return (predicted, top_label, confidence) using the same rule as model.predict_intent."""
    import model  # loads the saved files, so only import it when evaluating

    probabilities = model.model.predict_proba(model.vectorizer.transform([text]))[0]
    best = int(probabilities.argmax())
    top_label = str(model.model.classes_[best])
    confidence = float(probabilities[best])
    predicted = top_label if confidence >= model.MIN_CONFIDENCE else UNKNOWN
    return predicted, top_label, confidence


def evaluate_phrases(test_set, predictor=predict_with_confidence):
    predictions = []
    for expected, phrases in test_set.items():
        for phrase in phrases:
            predicted, top_label, confidence = predictor(phrase)
            predictions.append(Prediction(phrase, expected, predicted, top_label, confidence))
    return predictions


def find_overlap(train, test):
    """Return (phrase, train intent, test intent) for test phrases that were also trained on."""
    trained = {normalize_phrase(p): intent for intent, phrases in train.items() for p in phrases}
    return [
        (phrase, trained[normalize_phrase(phrase)], intent)
        for intent, phrases in test.items()
        for phrase in phrases
        if normalize_phrase(phrase) in trained
    ]


def wilson_interval(successes, total, z=1.96):
    """95% interval for a proportion; wide when there are few phrases."""
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def mean(values):
    return sum(values) / len(values) if values else None


def summarize(predictions, train):
    in_scope = [p for p in predictions if p.expected != UNKNOWN]
    out_scope = [p for p in predictions if p.expected == UNKNOWN]

    per_intent = {}
    for intent in sorted(set(train) | {p.expected for p in in_scope}):
        mine = [p for p in in_scope if p.expected == intent]
        chosen = [p for p in predictions if p.predicted == intent]
        per_intent[intent] = {
            "train": len(train.get(intent, [])),
            "test": len(mine),
            "correct": sum(p.correct for p in mine),
            "abstained": sum(p.abstained for p in mine),
            "misrouted": sum(p.misrouted for p in mine),
            "chosen": len(chosen),
            "chosen_right": sum(p.correct for p in chosen),
        }

    confusions = defaultdict(list)
    for p in predictions:
        if p.misrouted or (p.expected == UNKNOWN and p.predicted != UNKNOWN):
            confusions[(p.expected, p.predicted)].append(p.phrase)

    return {
        "predictions": predictions,
        "total": len(predictions),
        "correct": sum(p.correct for p in predictions),
        "in_scope": in_scope,
        "in_scope_correct": sum(p.correct for p in in_scope),
        "misrouted": [p for p in in_scope if p.misrouted],
        "abstained": [p for p in in_scope if p.abstained],
        "out_scope": out_scope,
        "out_rejected": sum(p.predicted == UNKNOWN for p in out_scope),
        "out_executed": [p for p in out_scope if p.predicted != UNKNOWN],
        "top_label_correct": sum(p.top_label == p.expected for p in in_scope),
        "mean_conf_correct": mean([p.confidence for p in in_scope if p.correct]),
        "mean_conf_misrouted": mean([p.confidence for p in in_scope if p.misrouted]),
        "mean_conf_abstained": mean([p.confidence for p in in_scope if p.abstained]),
        "per_intent": per_intent,
        "confusions": sorted(confusions.items(), key=lambda item: (-len(item[1]), item[0])),
    }


def fmt_conf(value):
    return f"{value:.2f}" if value is not None else "n/a"


def render_report(summary, train, min_confidence, top=10, command="venv/bin/python evaluate.py"):
    s = summary
    total, in_scope, out_scope = s["total"], len(s["in_scope"]), len(s["out_scope"])
    low, high = wilson_interval(s["correct"], total)
    train_total = sum(len(v) for v in train.values())

    lines = [
        "# Model evaluation report",
        "",
        f"Generated by `{command}` on phrases the model was not trained on "
        "(`evaluation_phrases.json`, kept separate from `intents.json`).",
        f"Model: TF-IDF + LogisticRegression, trained on {train_total} phrases across {len(train)} intents, "
        f"confidence threshold {min_confidence}. Environment: Python {platform.python_version()}, "
        f"scikit-learn {sklearn_version()}.",
        "",
        "## Summary",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Test phrases | {total} ({in_scope} supported requests, {out_scope} out-of-scope requests) |",
        f"| Handled correctly (overall) | {s['correct']}/{total} = {pct(s['correct'], total)} "
        f"(95% interval {100 * low:.0f}%-{100 * high:.0f}%) |",
        f"| Supported requests understood | {s['in_scope_correct']}/{in_scope} = {pct(s['in_scope_correct'], in_scope)} |",
        f"| Supported requests answered with the **wrong command** | {len(s['misrouted'])}/{in_scope} = "
        f"{pct(len(s['misrouted']), in_scope)} |",
        f"| Supported requests not recognised (safe, but unhelpful) | {len(s['abstained'])}/{in_scope} = "
        f"{pct(len(s['abstained']), in_scope)} |",
        f"| Out-of-scope requests correctly refused | {s['out_rejected']}/{out_scope} = "
        f"{pct(s['out_rejected'], out_scope)} |",
        "",
        f"With {total} phrases, one phrase moves the overall figure by {100 / total:.1f} points, so treat small "
        "differences between runs as noise. Wrong commands are the costly mistake; not recognising a phrase only "
        "shows the help message.",
        "",
        "## Effect of the confidence threshold",
        "",
        f"The model ranks intents by probability and E-SHELL only acts when the top probability is at least "
        f"{min_confidence}; otherwise it answers `unknown`.",
        "",
        "| | Supported requests understood |",
        "|---|---|",
        f"| Top-ranked intent, no threshold | {s['top_label_correct']}/{in_scope} = {pct(s['top_label_correct'], in_scope)} |",
        f"| With the threshold (what users get) | {s['in_scope_correct']}/{in_scope} = {pct(s['in_scope_correct'], in_scope)} |",
        "",
        "| Average top probability | Value |",
        "|---|---|",
        f"| Correct answers | {fmt_conf(s['mean_conf_correct'])} |",
        f"| Wrong commands | {fmt_conf(s['mean_conf_misrouted'])} |",
        f"| Not recognised | {fmt_conf(s['mean_conf_abstained'])} |",
        "",
        "These probabilities are small because the model splits its belief across "
        f"{len(train)} intents, and they are not calibrated: 0.30 does not mean a 30% chance of being right. "
        "Use them only to compare against the threshold, never as a measure of how sure the model is.",
        "",
        "## Results by intent",
        "",
        "| Intent | Training phrases | Test phrases | Correct | Not recognised | Wrong command | Recall | Precision |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for intent, row in s["per_intent"].items():
        lines.append(
            f"| `{intent}` | {row['train']} | {row['test']} | {row['correct']} | {row['abstained']} | "
            f"{row['misrouted']} | {pct(row['correct'], row['test'])} | {pct(row['chosen_right'], row['chosen'])} |"
        )
    lines += [
        "",
        "Recall is the share of that intent's test phrases understood. Precision is how often the model was right "
        "when it chose that intent.",
        "",
        "## Most confused intent pairs",
        "",
    ]

    confusions = s["confusions"][:top]
    if confusions:
        lines += ["| Expected | Model chose | Count | Example phrases |", "|---|---|---|---|"]
        for (expected, chosen), phrases in confusions:
            examples = ", ".join(f"\"{phrase}\"" for phrase in phrases[:3])
            lines.append(f"| `{expected}` | `{chosen}` | {len(phrases)} | {examples} |")
    else:
        lines.append("No test phrase was answered with a wrong command.")

    lines += ["", "## Supported phrases the model did not recognise", ""]
    if s["abstained"]:
        grouped = defaultdict(list)
        for p in s["abstained"]:
            grouped[p.expected].append(p.phrase)
        lines += ["<details>", f"<summary>{len(s['abstained'])} phrases</summary>", ""]
        for intent in sorted(grouped):
            joined = ", ".join(f"\"{phrase}\"" for phrase in grouped[intent])
            lines.append(f"- `{intent}`: {joined}")
        lines += ["", "</details>"]
    else:
        lines.append("None.")

    lines += ["", "## Out-of-scope requests", ""]
    if s["out_executed"]:
        lines.append("These unsupported requests were wrongly matched to a command:")
        lines.append("")
        for p in s["out_executed"]:
            lines.append(f"- \"{p.phrase}\" -> `{p.predicted}` (probability {p.confidence:.2f})")
    else:
        lines.append("Every out-of-scope request was refused with `unknown`.")

    lines += [
        "",
        "## Limits of this report",
        "",
        "- The test phrases were written by hand for this project. They are a rough guide, not a sample of real users.",
        "- Results come from the saved `.pkl` files, so retrain (`venv/bin/python train.py`) after changing "
        "`intents.json`, then re-run this report.",
        "- `edit_file`, `make_executable` and `run_file` are only ever acted on through their exact typed forms "
        "(`edit x`, `make x executable`, `run x`), never because the model guessed them.",
        "",
    ]
    return "\n".join(lines)


def sklearn_version():
    try:
        import sklearn

        return sklearn.__version__
    except ImportError:
        return "unknown"


def load_inputs(intents_path, phrases_path):
    """Load and cross-check both files. Raises IntentDataError with a clear message."""
    train = load_intents(intents_path)
    test = load_intents(phrases_path)

    unknown_labels = sorted(set(test) - set(train) - {UNKNOWN})
    if unknown_labels:
        raise IntentDataError(
            f"{phrases_path} uses intent name(s) that are not in {intents_path}: "
            + ", ".join(f"'{label}'" for label in unknown_labels)
            + f". Use \"{UNKNOWN}\" for out-of-scope phrases."
        )

    overlap = find_overlap(train, test)
    if overlap:
        details = "\n".join(
            f"  - '{phrase}' is a test phrase for '{test_intent}' but is also trained as '{train_intent}'"
            for phrase, train_intent, test_intent in overlap
        )
        raise IntentDataError(
            f"{len(overlap)} test phrase(s) also appear in the training data, which would inflate the score:\n"
            f"{details}\nRemove them from one of the files."
        )

    return train, test


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate the intent model on held-out phrases.")
    parser.add_argument("--intents", default=BASE_DIR / "intents.json", help="training phrases")
    parser.add_argument("--phrases", default=BASE_DIR / "evaluation_phrases.json", help="held-out test phrases")
    parser.add_argument("--markdown", help="also write the report to this file")
    parser.add_argument("--top", type=int, default=10, help="how many confused pairs to list")
    args = parser.parse_args(argv)

    try:
        train, test = load_inputs(args.intents, args.phrases)
    except IntentDataError as error:
        print(f"Cannot evaluate: {error}", file=sys.stderr)
        return 2

    import model

    stale = set(train) ^ {str(label) for label in model.model.classes_}
    if stale:
        print(
            "Warning: the saved model does not match intents.json "
            f"({', '.join(sorted(stale))}). Retrain with train.py first.",
            file=sys.stderr,
        )

    summary = summarize(evaluate_phrases(test), train)
    command = "venv/bin/python evaluate.py" + (f" --markdown {args.markdown}" if args.markdown else "")
    report = render_report(summary, train, model.MIN_CONFIDENCE, top=args.top, command=command)

    print(report)
    if args.markdown:
        Path(args.markdown).write_text(report, encoding="utf-8", newline="\n")
        print(f"Wrote {args.markdown}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
