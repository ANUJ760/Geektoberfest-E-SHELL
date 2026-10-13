import contextlib
import io
import json
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

import evaluate
from evaluate import UNKNOWN, Prediction
from intent_data import IntentDataError

PROJECT_DIR = Path(__file__).resolve().parent.parent
HAS_MODEL = bool(find_spec("sklearn"))


def prediction(expected, predicted, confidence=0.5, phrase="some phrase", top_label=None):
    return Prediction(phrase, expected, predicted, top_label or predicted, confidence)


class PredictionTests(unittest.TestCase):
    def test_correct_abstained_and_misrouted_are_mutually_exclusive(self):
        cases = {
            ("a", "a"): (True, False, False),
            ("a", UNKNOWN): (False, True, False),
            ("a", "b"): (False, False, True),
            (UNKNOWN, UNKNOWN): (True, False, False),
            (UNKNOWN, "b"): (False, False, True),
        }

        for (expected, predicted), flags in cases.items():
            with self.subTest(expected=expected, predicted=predicted):
                p = prediction(expected, predicted)
                self.assertEqual((p.correct, p.abstained, p.misrouted), flags)


class HelperTests(unittest.TestCase):
    def test_wilson_interval_for_a_half(self):
        low, high = evaluate.wilson_interval(50, 100)

        self.assertAlmostEqual(low, 0.404, places=2)
        self.assertAlmostEqual(high, 0.596, places=2)

    def test_wilson_interval_stays_within_zero_and_one(self):
        for successes, total in ((0, 10), (10, 10), (1, 3), (0, 0)):
            with self.subTest(successes=successes, total=total):
                low, high = evaluate.wilson_interval(successes, total)
                self.assertTrue(0.0 <= low <= high <= 1.0)

    def test_more_data_gives_a_narrower_interval(self):
        small = evaluate.wilson_interval(7, 10)
        large = evaluate.wilson_interval(700, 1000)

        self.assertLess(large[1] - large[0], small[1] - small[0])

    def test_pct_handles_an_empty_denominator(self):
        self.assertEqual(evaluate.pct(1, 4), "25.0%")
        self.assertEqual(evaluate.pct(0, 0), "n/a")

    def test_mean(self):
        self.assertEqual(evaluate.mean([1, 2, 3]), 2)
        self.assertIsNone(evaluate.mean([]))

    def test_overlap_ignores_case_and_spacing(self):
        train = {"a": ["disk usage"], "b": ["time"]}
        test = {"a": ["  DISK   usage "], "b": ["clock"]}

        self.assertEqual(evaluate.find_overlap(train, test), [("  DISK   usage ", "a", "a")])

    def test_overlap_also_ignores_case_and_spacing_in_the_training_data(self):
        train = {"a": ["  Disk   USAGE "]}
        test = {"a": ["disk usage"]}

        self.assertEqual(evaluate.find_overlap(train, test), [("disk usage", "a", "a")])

    def test_overlap_reports_a_phrase_trained_under_another_intent(self):
        overlap = evaluate.find_overlap({"a": ["time"]}, {"b": ["time"]})

        self.assertEqual(overlap, [("time", "a", "b")])

    def test_no_overlap_means_an_empty_list(self):
        self.assertEqual(evaluate.find_overlap({"a": ["x"]}, {"a": ["y"]}), [])


class EvaluatePhrasesTests(unittest.TestCase):
    def test_every_phrase_is_scored_in_file_order(self):
        calls = []

        def predictor(text):
            calls.append(text)
            return "a", "a", 0.9

        results = evaluate.evaluate_phrases({"a": ["one", "two"], "b": ["three"]}, predictor)

        self.assertEqual(calls, ["one", "two", "three"])
        self.assertEqual([(r.phrase, r.expected, r.predicted) for r in results],
                         [("one", "a", "a"), ("two", "a", "a"), ("three", "b", "a")])


SAMPLE_TRAIN = {"a": ["a1", "a2"], "b": ["b1"], "c": ["c1", "c2", "c3"]}


def sample_predictions():
    return [
        prediction("a", "a", 0.60, "a-right"),
        prediction("a", "a", 0.40, "a-right-2"),
        prediction("a", UNKNOWN, 0.08, "a-missed", top_label="a"),
        prediction("b", "c", 0.30, "b-wrong-1"),
        prediction("b", "c", 0.20, "b-wrong-2"),
        prediction("c", "a", 0.25, "c-wrong"),
        prediction("c", UNKNOWN, 0.05, "c-missed", top_label="b"),
        prediction(UNKNOWN, UNKNOWN, 0.03, "nonsense", top_label="a"),
        prediction(UNKNOWN, "b", 0.20, "tell me a joke"),
    ]


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.summary = evaluate.summarize(sample_predictions(), SAMPLE_TRAIN)

    def test_headline_counts(self):
        s = self.summary

        self.assertEqual(s["total"], 9)
        self.assertEqual(s["correct"], 3)
        self.assertEqual(len(s["in_scope"]), 7)
        self.assertEqual(s["in_scope_correct"], 2)
        self.assertEqual(len(s["misrouted"]), 3)
        self.assertEqual(len(s["abstained"]), 2)
        self.assertEqual(len(s["out_scope"]), 2)
        self.assertEqual(s["out_rejected"], 1)
        self.assertEqual([p.phrase for p in s["out_executed"]], ["tell me a joke"])

    def test_counts_add_up(self):
        s = self.summary

        self.assertEqual(s["in_scope_correct"] + len(s["misrouted"]) + len(s["abstained"]), len(s["in_scope"]))

    def test_threshold_effect_uses_the_top_label_without_the_threshold(self):
        # "a-missed" had the right top label, "c-missed" did not.
        self.assertEqual(self.summary["top_label_correct"], 2 + 1 + 0 + 0 + 0 + 0 + 0)

    def test_average_confidence_by_outcome(self):
        s = self.summary

        self.assertAlmostEqual(s["mean_conf_correct"], 0.50)
        self.assertAlmostEqual(s["mean_conf_misrouted"], (0.30 + 0.20 + 0.25) / 3)
        self.assertAlmostEqual(s["mean_conf_abstained"], (0.08 + 0.05) / 2)

    def test_per_intent_counts_precision_and_training_size(self):
        rows = self.summary["per_intent"]

        self.assertEqual(rows["a"], {
            "train": 2, "test": 3, "correct": 2, "abstained": 1, "misrouted": 0,
            "chosen": 3, "chosen_right": 2,
        })
        self.assertEqual(rows["b"]["test"], 2)
        self.assertEqual(rows["b"]["misrouted"], 2)
        self.assertEqual(rows["c"]["train"], 3)
        self.assertEqual(rows["c"]["chosen"], 2)
        self.assertEqual(rows["c"]["chosen_right"], 0)

    def test_confusions_are_sorted_by_count_then_name_and_include_out_of_scope_hits(self):
        pairs = [(pair, len(phrases)) for pair, phrases in self.summary["confusions"]]

        self.assertEqual(pairs, [
            (("b", "c"), 2),
            (("c", "a"), 1),
            ((UNKNOWN, "b"), 1),
        ])

    def test_not_recognised_phrases_are_not_counted_as_confusions(self):
        for (expected, predicted), _ in self.summary["confusions"]:
            self.assertNotEqual(predicted, UNKNOWN)

    def test_an_intent_with_no_test_phrases_is_still_listed(self):
        summary = evaluate.summarize([prediction("a", "a")], {"a": ["x"], "z": ["y"]})

        self.assertEqual(summary["per_intent"]["z"]["test"], 0)


class RenderReportTests(unittest.TestCase):
    def render(self, predictions=None, train=None, top=10):
        train = train or SAMPLE_TRAIN
        summary = evaluate.summarize(predictions or sample_predictions(), train)
        return evaluate.render_report(summary, train, 0.12, top=top)

    def test_report_has_every_section(self):
        report = self.render()

        for heading in (
            "# Model evaluation report",
            "## Summary",
            "## Effect of the confidence threshold",
            "## Results by intent",
            "## Most confused intent pairs",
            "## Supported phrases the model did not recognise",
            "## Out-of-scope requests",
            "## Limits of this report",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, report)

    def test_report_states_the_numbers(self):
        report = self.render()

        self.assertIn("| Test phrases | 9 (7 supported requests, 2 out-of-scope requests) |", report)
        self.assertIn("3/9 = 33.3%", report)
        self.assertIn("wrong command", report)
        self.assertIn("3/7 = 42.9%", report)
        self.assertIn("1/2 = 50.0%", report)
        self.assertIn("confidence threshold 0.12", report)

    def test_report_gives_an_interval_and_warns_about_small_samples(self):
        report = self.render()

        self.assertIn("95% interval", report)
        self.assertIn("one phrase moves the overall figure by 11.1 points", report)

    def test_report_does_not_oversell_the_probabilities(self):
        report = self.render()

        self.assertIn("not calibrated", report)
        self.assertIn("never as a measure of how sure the model is", report)

    def test_confused_pairs_list_examples(self):
        report = self.render()

        self.assertIn("| `b` | `c` | 2 | \"b-wrong-1\", \"b-wrong-2\" |", report)

    def test_top_limits_the_number_of_confused_pairs(self):
        report = self.render(top=1)

        self.assertIn("| `b` | `c` |", report)
        self.assertNotIn("| `c` | `a` |", report)

    def test_unrecognised_phrases_are_grouped_by_intent(self):
        report = self.render()

        self.assertIn("2 phrases", report)
        self.assertIn("- `a`: \"a-missed\"", report)
        self.assertIn("- `c`: \"c-missed\"", report)

    def test_out_of_scope_hits_are_named(self):
        self.assertIn("\"tell me a joke\" -> `b`", self.render())

    def test_a_clean_run_says_so(self):
        clean = [prediction("a", "a"), prediction("b", "b"), prediction(UNKNOWN, UNKNOWN)]

        report = self.render(clean, {"a": ["x"], "b": ["y"]})

        self.assertIn("No test phrase was answered with a wrong command.", report)
        self.assertIn("Every out-of-scope request was refused with `unknown`.", report)
        self.assertIn("## Supported phrases the model did not recognise\n\nNone.", report)

    def test_report_is_plain_ascii_so_it_prints_on_any_terminal(self):
        self.render().encode("ascii")


class LoadInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.dir = Path(self.temp_dir.name)

    def write(self, name, data):
        path = self.dir / name
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def load(self, train, test):
        return evaluate.load_inputs(self.write("train.json", train), self.write("test.json", test))

    def test_valid_files_load(self):
        train, test = self.load({"a": ["a1"], "b": ["b1"]}, {"a": ["a2"], "unknown": ["zzz"]})

        self.assertEqual(set(train), {"a", "b"})
        self.assertEqual(set(test), {"a", "unknown"})

    def test_an_intent_name_typo_is_reported(self):
        with self.assertRaises(IntentDataError) as context:
            self.load({"a": ["a1"], "b": ["b1"]}, {"a": ["a2"], "dsik_usage": ["x"]})

        message = str(context.exception)
        self.assertIn("'dsik_usage'", message)
        self.assertIn("not in", message)
        self.assertIn("unknown", message)

    def test_a_training_phrase_in_the_test_set_is_rejected(self):
        with self.assertRaises(IntentDataError) as context:
            self.load({"a": ["a1"], "b": ["b1"]}, {"a": ["A1"], "b": ["b2"]})

        message = str(context.exception)
        self.assertIn("1 test phrase(s) also appear in the training data", message)
        self.assertIn("'A1'", message)
        self.assertIn("inflate", message)

    def test_malformed_test_file_is_reported(self):
        train = self.write("train.json", {"a": ["a1"], "b": ["b1"]})
        test = self.write("test.json", '{"a": ["x",]}')

        with self.assertRaises(IntentDataError) as context:
            evaluate.load_inputs(train, test)

        self.assertIn("not valid JSON", str(context.exception))

    def test_a_missing_test_file_is_reported(self):
        train = self.write("train.json", {"a": ["a1"], "b": ["b1"]})

        with self.assertRaises(IntentDataError) as context:
            evaluate.load_inputs(train, self.dir / "missing.json")

        self.assertIn("Could not find", str(context.exception))


class ProjectDataTests(unittest.TestCase):
    """Guards for contributors editing intents.json or evaluation_phrases.json."""

    def test_held_out_phrases_are_valid_and_never_trained_on(self):
        train, test = evaluate.load_inputs(PROJECT_DIR / "intents.json", PROJECT_DIR / "evaluation_phrases.json")

        self.assertEqual(evaluate.find_overlap(train, test), [])

    def test_every_intent_has_held_out_phrases(self):
        train, test = evaluate.load_inputs(PROJECT_DIR / "intents.json", PROJECT_DIR / "evaluation_phrases.json")

        self.assertEqual(sorted(set(train) - set(test)), [])

    def test_there_are_out_of_scope_phrases_to_check_refusals(self):
        _, test = evaluate.load_inputs(PROJECT_DIR / "intents.json", PROJECT_DIR / "evaluation_phrases.json")

        self.assertGreaterEqual(len(test[UNKNOWN]), 5)


@unittest.skipUnless(HAS_MODEL, "scikit-learn is not installed")
class SavedModelTests(unittest.TestCase):
    def test_evaluation_matches_what_the_shell_would_do(self):
        from model import predict_intent

        _, test = evaluate.load_inputs(PROJECT_DIR / "intents.json", PROJECT_DIR / "evaluation_phrases.json")

        for phrases in test.values():
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    predicted, _, _ = evaluate.predict_with_confidence(phrase)
                    self.assertEqual(predicted, predict_intent(phrase))

    def test_confidence_is_a_probability_and_the_threshold_is_respected(self):
        import model

        for phrase in ("disk usage", "asdf qwerty", "what is the meaning of life"):
            with self.subTest(phrase=phrase):
                predicted, top_label, confidence = evaluate.predict_with_confidence(phrase)
                self.assertTrue(0.0 <= confidence <= 1.0)
                if confidence < model.MIN_CONFIDENCE:
                    self.assertEqual(predicted, UNKNOWN)
                else:
                    self.assertEqual(predicted, top_label)

    def test_gibberish_is_refused(self):
        predicted, _, _ = evaluate.predict_with_confidence("asdf qwerty")

        self.assertEqual(predicted, UNKNOWN)


@unittest.skipUnless(HAS_MODEL, "scikit-learn is not installed")
class MainTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.dir = Path(self.temp_dir.name)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = evaluate.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_run_prints_the_report(self):
        code, out, _ = self.run_main()

        self.assertEqual(code, 0)
        self.assertIn("# Model evaluation report", out)
        self.assertIn("## Results by intent", out)

    def test_markdown_option_writes_the_same_report_to_a_file(self):
        target = self.dir / "report.md"

        code, out, err = self.run_main("--markdown", str(target))

        self.assertEqual(code, 0)
        self.assertEqual(target.read_text(encoding="utf-8").strip(), out.strip())
        self.assertIn("Wrote", err)

    def test_overlapping_data_stops_before_scoring(self):
        phrases = self.dir / "phrases.json"
        phrases.write_text(json.dumps({"disk_usage": ["disk usage"], "unknown": ["zzz"]}), encoding="utf-8")

        code, out, err = self.run_main("--phrases", str(phrases))

        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("Cannot evaluate", err)
        self.assertIn("'disk usage'", err)

    def test_a_missing_phrases_file_is_a_clear_error(self):
        code, out, err = self.run_main("--phrases", str(self.dir / "nope.json"))

        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("Could not find", err)

    def test_a_model_that_does_not_match_the_training_data_is_flagged(self):
        intents = self.dir / "intents.json"
        real = json.loads((PROJECT_DIR / "intents.json").read_text(encoding="utf-8"))
        real["brand_new_intent"] = ["a brand new thing nobody trained"]
        intents.write_text(json.dumps(real), encoding="utf-8")
        phrases = self.dir / "phrases.json"
        phrases.write_text(json.dumps({"disk_usage": ["how much disk space is left"], "unknown": ["zzzz"]}),
                           encoding="utf-8")

        code, _, err = self.run_main("--intents", str(intents), "--phrases", str(phrases))

        self.assertEqual(code, 0)
        self.assertIn("does not match intents.json", err)
        self.assertIn("brand_new_intent", err)


if __name__ == "__main__":
    unittest.main()
