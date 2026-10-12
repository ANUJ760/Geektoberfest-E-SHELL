import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import train


class ModelTrainingTests(unittest.TestCase):
    """Verify that train.py resolves paths relative to its own location."""

    def test_train_from_different_working_directory_succeeds(self):
        """Running train.py from an unrelated directory should still write
        the model files next to the script, not into the working directory."""
        with tempfile.TemporaryDirectory() as script_dir, \
                tempfile.TemporaryDirectory() as external_dir:
            # Copy the training script into a fresh directory.
            script_path = Path(script_dir) / "train.py"
            script_path.write_text(Path(train.__file__).read_text())

            # Copy intent_data.py so the import works.
            intent_data_src = Path(train.__file__).resolve().parent / "intent_data.py"
            (Path(script_dir) / "intent_data.py").write_text(
                intent_data_src.read_text()
            )

            # Write a minimal valid intents.json next to the script.
            import json
            sample_intents = {
                "greeting": ["hello", "hi there"],
                "farewell": ["bye", "see you later"],
            }
            with open(Path(script_dir) / "intents.json", "w") as f:
                json.dump(sample_intents, f)

            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=external_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"train.py failed: {result.stderr}")
            self.assertIn("Model trained successfully", result.stdout)
            # Model files should appear next to the script, NOT in the cwd.
            self.assertTrue((Path(script_dir) / "vectorizer.pkl").exists())
            self.assertTrue((Path(script_dir) / "intent_model.pkl").exists())
            self.assertFalse((Path(external_dir) / "vectorizer.pkl").exists())
            self.assertFalse((Path(external_dir) / "intent_model.pkl").exists())

    def test_train_function_custom_base_dir(self):
        """Calling train(base_dir=...) should read intents.json from that
        directory and write the .pkl files there."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            import json
            sample_intents = {
                "greeting": ["hello", "hi there"],
                "farewell": ["bye", "see you later"],
            }
            with open(temp_path / "intents.json", "w") as f:
                json.dump(sample_intents, f)

            output = io.StringIO()
            with redirect_stdout(output):
                train.train(base_dir=temp_path)

            self.assertIn("Model trained successfully", output.getvalue())
            self.assertTrue((temp_path / "vectorizer.pkl").is_file())
            self.assertTrue((temp_path / "intent_model.pkl").is_file())


if __name__ == "__main__":
    unittest.main()
