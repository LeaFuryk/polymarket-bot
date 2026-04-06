"""PyTorch DNN worker — runs in a subprocess to avoid libomp conflict with XGBoost.

Called by DeepNeuralNetworkRunner via subprocess. Do not import directly.

Architecture reused from LLM Engineering week6/pricer/deep_neural_network.py:
  ResidualBlock with skip connections, LayerNorm, Dropout.
"""

import json
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader, TensorDataset


class ResidualBlock(nn.Module):
    def __init__(self, hidden_size, dropout_prob):
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout_prob),
            nn.Linear(hidden_size, hidden_size),
            nn.LayerNorm(hidden_size),
        )
        self.relu = nn.ReLU()

    def forward(self, x):
        return self.relu(x + self.block(x))


class DeepNeuralNetwork(nn.Module):
    def __init__(self, input_size, num_layers=6, hidden_size=128, dropout_prob=0.3):
        super().__init__()
        self.input_layer = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout_prob),
        )
        self.residual_blocks = nn.ModuleList([ResidualBlock(hidden_size, dropout_prob) for _ in range(num_layers - 2)])
        self.output_layer = nn.Sequential(
            nn.Linear(hidden_size, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        x = self.input_layer(x)
        for block in self.residual_blocks:
            x = block(x)
        return self.output_layer(x)


def train(args):
    X_train = np.load(args["X_train"])
    y_train = np.load(args["y_train"])
    X_val = np.load(args["X_val"])
    y_val = np.load(args["y_val"])
    epochs = args.get("epochs", 20)
    patience = args.get("patience", 5)

    np.random.seed(42)
    torch.manual_seed(42)

    X_t = torch.tensor(X_train, dtype=torch.float32)
    y_t = torch.tensor(y_train, dtype=torch.float32).unsqueeze(1)
    X_v = torch.tensor(X_val, dtype=torch.float32)
    y_v = torch.tensor(y_val, dtype=torch.float32).unsqueeze(1)

    model = DeepNeuralNetwork(X_t.shape[1])
    total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"DNN: {total_params:,} params", flush=True)

    loss_fn = nn.BCELoss()
    optimizer = optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
    scheduler = CosineAnnealingLR(optimizer, T_max=10, eta_min=1e-5)
    loader = DataLoader(TensorDataset(X_t, y_t), batch_size=512, shuffle=True)

    best_val_loss = float("inf")
    best_state = None
    no_improve = 0

    for epoch in range(1, epochs + 1):
        model.train()
        for bx, by in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(bx), by)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        model.eval()
        with torch.no_grad():
            vl = loss_fn(model(X_v), y_v).item()
            va = ((model(X_v) >= 0.5).float() == y_v).float().mean().item()

        if vl < best_val_loss:
            best_val_loss = vl
            best_state = model.state_dict()
            no_improve = 0
            marker = " *"
        else:
            no_improve += 1
            marker = ""

        print(f"  Epoch {epoch}/{epochs}: val_loss={vl:.4f} val_acc={va * 100:.1f}%{marker}", flush=True)
        scheduler.step()

        if no_improve >= patience:
            print(f"  Early stopping at epoch {epoch}", flush=True)
            break

    if best_state:
        model.load_state_dict(best_state)
    torch.save(model.state_dict(), args["model_path"])
    print(f"  Saved to {args['model_path']}", flush=True)


def predict(args):
    X = np.load(args["X_input"])
    model = DeepNeuralNetwork(X.shape[1])
    model.load_state_dict(torch.load(args["model_path"], weights_only=True))
    model.eval()
    with torch.no_grad():
        probs = model(torch.tensor(X, dtype=torch.float32)).numpy().flatten()
    np.save(args["output_path"], probs)


if __name__ == "__main__":
    args = json.loads(sys.argv[1])
    if args["cmd"] == "train":
        train(args)
    elif args["cmd"] == "predict":
        predict(args)
