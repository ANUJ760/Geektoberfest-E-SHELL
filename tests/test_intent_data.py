import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from intent_data import IntentDataError, load_intents, validate_intents

PROJECT_DIR = Path(__file__).resolve().parent.parent


class ValidateIntentsTests(unittest.TestCase):
    def problems(self, intents):
        return validate_intents(intents)

    def assert_one_problem(self, intents, *expected_parts):
        problems = self.problems(intents)
        self.assertEqual(len(problems), 1, problems)
        for part in expected_parts:
            self.assertIn(part, problems[0])

    def test_valid_data_has_no_problems(self):
        self.assertEqual(self.problems({"a": ["one", "two"], "b": ["three"]}), [])

    def test_the_real_intents_file_is_valid(self):
        intents = load_intents(PROJECT_DIR / "intents.json")

        self.assertGreaterEqual(len(intents), 2)

    def test_top_level_must_be_an_object(self):
        for data in ([], [["a", ["x"]]], "text", 5, None):
            with self.subTest(data=data):
                self.assert_one_problem(data, "top level must be an object", type(data).__name__)

    def test_empty_phrase_list_names_the_intent(self):
        self.assert_one_problem({"a": ["x"], "b": ["y"], "empty": []}, "'empty'", "empty phrase list")

    def test_phrases_must_be_a_list(self):
        for value in ("just text", {"x": 1}, 5, None):
            with self.subTest(value=value):
                self.assert_one_problem(
                    {"a": ["x"], "b": ["y"], "bad": value}, "'bad'", "list of phrases", type(value).__name__
                )

    def test_non_text_phrase_reports_intent_position_and_value(self):
        self.assert_one_problem(
            {"a": ["x"], "b": ["y", 42]}, "'b'", "phrase #2", "expected text", "int", "42"
        )

    def test_nested_list_and_null_phrases_are_invalid(self):
        problems = self.problems({"a": ["x"], "b": [["y"], None]})

        self.assertEqual(len(problems), 2, problems)
        self.assertIn("phrase #1", problems[0])
        self.assertIn("list", problems[0])
        self.assertIn("phrase #2", problems[1])
        self.assertIn("NoneType", problems[1])

    def test_blank_phrases_are_invalid(self):
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=blank):
                self.assert_one_problem(
                    {"a": ["x"], "b": ["y", blank]}, "'b'", "phrase #2", "blank"
                )

    def test_empty_intent_name_is_invalid(self):
        self.assert_one_problem({"a": ["x"], "b": ["y"], " ": ["z"]}, "empty name")

    def test_same_phrase_under_different_intents_is_reported(self):
        self.assert_one_problem(
            {"first": ["disk usage"], "second": ["disk usage"]},
            "'disk usage'", "'first'", "'second'", "cannot tell them apart",
        )

    def test_duplicates_ignore_case_and_extra_spacing(self):
        for other in ("DISK USAGE", "  Disk   usage ", "disk usage\n"):
            with self.subTest(other=other):
                self.assert_one_problem(
                    {"first": ["disk usage"], "second": [other]}, "'first'", "'second'"
                )

    def test_repeating_a_phrase_within_one_intent_is_allowed(self):
        self.assertEqual(self.problems({"a": ["same", "same", "SAME"], "b": ["other"]}), [])

    def test_a_phrase_shared_by_three_intents_is_reported_for_each_extra_intent(self):
        problems = self.problems({"a": ["x"], "b": ["x"], "c": ["x"]})

        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(all("'a'" in problem for problem in problems))

    def test_every_problem_is_reported_together(self):
        problems = self.problems(
            {"empty": [], "numbers": [1], "blank": [" "], "a": ["dup"], "b": ["dup"], "wrong": "x"}
        )

        self.assertEqual(len(problems), 5, problems)

    def test_at_least_two_intents_are_required(self):
        self.assert_one_problem({"only": ["x"]}, "at least two")
        self.assert_one_problem({}, "at least two")

    def test_intents_that_fail_do_not_count_toward_the_minimum(self):
        problems = self.problems({"good": ["x"], "empty": []})

        self.assertEqual(len(problems), 1)
        self.assertIn("empty phrase list", problems[0])


class LoadIntentsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "intents.json"

    def error_for(self, text, encoding="utf-8"):
        self.path.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
        with self.assertRaises(IntentDataError) as context:
            load_intents(self.path)
        return str(context.exception)

    def test_valid_file_is_loaded(self):
        self.path.write_text(json.dumps({"a": ["one"], "b": ["two"]}), encoding="utf-8")

        self.assertEqual(load_intents(self.path), {"a": ["one"], "b": ["two"]})

    def test_non_ascii_phrases_are_loaded(self):
        self.path.write_text(json.dumps({"a": ["café"], "b": ["日本語"]}, ensure_ascii=False), encoding="utf-8")

        self.assertEqual(load_intents(self.path)["a"], ["café"])

    def test_malformed_json_reports_the_line_and_column(self):
        message = self.error_for('{\n  "a": ["x",],\n  "b": ["y"]\n}')

        self.assertIn("not valid JSON", message)
        self.assertIn("line 2", message)
        self.assertIn("column", message)
        self.assertIn(str(self.path), message)

    def test_truncated_and_empty_files_are_reported_as_invalid_json(self):
        for text in ('{"a": ["x"', "", "   "):
            with self.subTest(text=text):
                self.assertIn("not valid JSON", self.error_for(text))

    def test_missing_file_is_reported(self):
        with self.assertRaises(IntentDataError) as context:
            load_intents(Path(self.temp_dir.name) / "missing.json")

        self.assertIn("Could not find", str(context.exception))

    def test_directory_instead_of_file_is_reported(self):
        with self.assertRaises(IntentDataError) as context:
            load_intents(self.temp_dir.name)

        self.assertIn("Could not", str(context.exception))

    def test_file_that_is_not_utf8_is_reported(self):
        self.assertIn("UTF-8", self.error_for(b'{"a": ["\xff\xfe"]}'))

    def test_invalid_content_lists_every_problem_with_a_count(self):
        message = self.error_for(json.dumps({"a": [], "b": [3], "c": ["x"], "d": ["x"]}))

        self.assertIn("has 3 problem(s)", message)
        self.assertIn("'a'", message)
        self.assertIn("'b'", message)
        self.assertIn("'c'", message)
        self.assertEqual(message.count("\n  - "), 3)

    def test_wrong_top_level_type_is_reported_after_loading(self):
        self.assertIn("top level must be an object", self.error_for("[1, 2]"))


@unittest.skipUnless(find_spec("sklearn"), "scikit-learn is not installed")
class TrainScriptTests(unittest.TestCase):
    """Runs train.py in a throwaway copy so the real model files are never touched."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.work = Path(self.temp_dir.name)
        for name in ("train.py", "intent_data.py", "intents.json"):
            shutil.copy(PROJECT_DIR / name, self.work / name)

    def train(self):
        return subprocess.run(
            [sys.executable, "-W", "ignore", "train.py"],
            cwd=self.work,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def test_valid_data_still_trains_and_saves_the_model(self):
        result = self.train()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Model trained successfully", result.stdout)
        self.assertTrue((self.work / "vectorizer.pkl").is_file())
        self.assertTrue((self.work / "intent_model.pkl").is_file())

    def test_invalid_data_gives_a_clear_message_and_saves_nothing(self):
        (self.work / "intents.json").write_text(
            json.dumps({"a": [], "b": ["x"], "c": ["x"]}), encoding="utf-8"
        )

        result = self.train()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot train", result.stderr)
        self.assertIn("Intent 'a' has an empty phrase list", result.stderr)
        self.assertIn("'x' is listed under both 'b' and 'c'", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.work / "vectorizer.pkl").exists())
        self.assertFalse((self.work / "intent_model.pkl").exists())

    def test_malformed_json_gives_a_clear_message_without_a_traceback(self):
        (self.work / "intents.json").write_text('{"a": ["x",]}', encoding="utf-8")

        result = self.train()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.work / "vectorizer.pkl").exists())


if __name__ == "__main__":
    unittest.main()
