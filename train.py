import pickle
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Ensure the project directory is importable so ``intent_data`` can be found
# even when the script is invoked from an unrelated working directory.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from intent_data import IntentDataError, load_intents

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
except ModuleNotFoundError as error:
    if error.name == "sklearn":
        raise SystemExit(
            "scikit-learn is not installed for this Python interpreter.\n"
            "Run training with the project virtual environment instead:\n"
            "  venv/bin/python train.py"
        ) from error
    raise


def train(base_dir=BASE_DIR):
    """Train the intent classifier, reading and writing files under *base_dir*.

    By default *base_dir* is the directory containing this script, so running
    ``python /path/to/train.py`` from any working directory produces the model
    files next to the script rather than in the caller's current directory.
    """
    base_path = Path(base_dir)

    try:
        intents = load_intents(str(base_path / "intents.json"))
    except IntentDataError as error:
        raise SystemExit(f"Cannot train: {error}")

    X = []
    y = []

    for intent, phrases in intents.items():
        for phrase in phrases:
            X.append(phrase)
            y.append(intent)

    vectorizer = TfidfVectorizer()
    X_vec = vectorizer.fit_transform(X)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_vec, y)

    with open(base_path / "vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)

    with open(base_path / "intent_model.pkl", "wb") as f:
        pickle.dump(model, f)

    print("✅ Model trained successfully")


if __name__ == "__main__":
    train()