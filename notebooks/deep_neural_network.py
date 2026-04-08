"""Deep Neural Network runner for bet outcome prediction.

Runs PyTorch in a subprocess (_dnn_worker.py) to avoid libomp conflict with XGBoost.
Same interface as LLM Engineering's DeepNeuralNetworkRunner: setup(), train(), predict.

Usage:
    runner = DeepNeuralNetworkRunner(X_train, y_train, X_val, y_val)
    runner.setup()
    runner.train(epochs=20)
    probs = runner.predict_proba(X_test)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

WORKER_SCRIPT = str(Path(__file__).parent / "_dnn_worker.py")

# Architecture constants (must match _dnn_worker.py)
HIDDEN_SIZE = 128
NUM_LAYERS = 6


class DeepNeuralNetworkRunner:
    """Runs DNN training and inference in a subprocess."""

    def __init__(self, X_train, y_train, X_val, y_val):
        self.X_train = X_train
        self.y_train = y_train
        self.X_val = X_val
        self.y_val = y_val
        self._tmp = tempfile.mkdtemp()
        self._model_path = str(Path(self._tmp) / "model.pth")
        self._n_params = 0

    def setup(self):
        """Save data to disk for subprocess."""
        np.save(Path(self._tmp) / "X_train.npy", self.X_train)
        np.save(Path(self._tmp) / "y_train.npy", self.y_train)
        np.save(Path(self._tmp) / "X_val.npy", self.X_val)
        np.save(Path(self._tmp) / "y_val.npy", self.y_val)

        inp = self.X_train.shape[1]
        h = HIDDEN_SIZE
        p = inp * h + h + h + h
        p += (NUM_LAYERS - 2) * 2 * (h * h + h + h + h)
        p += h + 1
        self._n_params = p

        print(f"  DeepNeuralNetwork: ~{p:,} parameters")
        print(f"  Architecture: {inp} -> {h} -> {NUM_LAYERS - 2}xResBlock({h}) -> 1")

    def train(self, epochs=20, patience=5):
        """Train in subprocess."""
        args = json.dumps(
            {
                "cmd": "train",
                "X_train": str(Path(self._tmp) / "X_train.npy"),
                "y_train": str(Path(self._tmp) / "y_train.npy"),
                "X_val": str(Path(self._tmp) / "X_val.npy"),
                "y_val": str(Path(self._tmp) / "y_val.npy"),
                "model_path": self._model_path,
                "epochs": epochs,
                "patience": patience,
            }
        )
        result = subprocess.run(
            [sys.executable, WORKER_SCRIPT, args],
            capture_output=True,
            text=True,
        )
        print(result.stdout, end="")
        if result.returncode != 0:
            print(f"DNN training failed:\n{result.stderr}")

    def predict_proba(self, X):
        """Predict in subprocess, return probabilities."""
        input_path = str(Path(self._tmp) / "X_predict.npy")
        output_path = str(Path(self._tmp) / "probs.npy")
        np.save(input_path, X)

        args = json.dumps(
            {
                "cmd": "predict",
                "X_input": input_path,
                "model_path": self._model_path,
                "output_path": output_path,
            }
        )
        result = subprocess.run(
            [sys.executable, WORKER_SCRIPT, args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"DNN predict failed:\n{result.stderr}")
            return np.full(len(X), 0.5)
        return np.load(output_path)

    def predict(self, X):
        """Binary predictions."""
        return (self.predict_proba(X) >= 0.5).astype(int)

    def param_count(self):
        """Trainable parameter count."""
        return self._n_params

    def save(self, path):
        """Copy model weights to a persistent path."""
        import shutil

        shutil.copy2(self._model_path, path)
        print(f"Saved to {path}")

    def load(self, path):
        """Load model weights from a path."""
        import shutil

        shutil.copy2(path, self._model_path)
        print(f"Loaded from {path}")
