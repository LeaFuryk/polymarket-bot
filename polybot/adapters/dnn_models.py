"""DNN model architectures for raw market data prediction.

Defines the model classes that DnnPredictor loads at runtime.
Having them in an importable module (instead of notebook __main__)
ensures torch.load() can find the class during unpickling.
"""

from __future__ import annotations

import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(self, hidden_size: int, dropout: float = 0.3) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, hidden_size),
            nn.LayerNorm(hidden_size),
        )
        self.act = nn.GELU()

    def forward(self, x):
        return self.act(x + self.block(x))


class ResidualMLP(nn.Module):
    """Residual MLP for single-snapshot prediction on 11 raw features."""

    def __init__(
        self,
        input_size: int = 11,
        hidden: int = 128,
        n_blocks: int = 4,
        dropout: float = 0.3,
    ) -> None:
        super().__init__()
        self.input_proj = nn.Sequential(
            nn.Linear(input_size, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.blocks = nn.ModuleList([ResidualBlock(hidden, dropout) for _ in range(n_blocks)])
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):
        x = self.input_proj(x)
        for block in self.blocks:
            x = block(x)
        return self.head(x)
