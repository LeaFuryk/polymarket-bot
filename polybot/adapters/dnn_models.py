"""DNN model architectures for market prediction.

Defines the model classes that DnnPredictor loads at runtime.
Having them in an importable module (instead of notebook __main__)
ensures torch.load() can find the class during unpickling.

Architectures:
  - ResidualMLP: v1, single-snapshot on raw features
  - ContextMLP: v2 ablation, single-snapshot on raw + cross-candle features
  - ContextConditionedTCN: v2 primary, FiLM-conditioned temporal conv on raw sequences + cross-candle context
  - ContextAttention: v2 ablation, FiLM-conditioned attention variant
"""

from __future__ import annotations

import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


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


class CausalConv1d(nn.Module):
    """1D convolution with causal padding (no future leakage)."""

    def __init__(self, in_ch: int, out_ch: int, kernel_size: int, dilation: int = 1) -> None:
        super().__init__()
        self.padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(in_ch, out_ch, kernel_size, padding=self.padding, dilation=dilation)

    def forward(self, x):
        out = self.conv(x)
        if self.padding > 0:
            out = out[:, :, : -self.padding]
        return out


class TCNBlock(nn.Module):
    """Residual temporal conv block with causal padding."""

    def __init__(self, channels: int, kernel_size: int = 3, dilation: int = 1, dropout: float = 0.2) -> None:
        super().__init__()
        self.net = nn.Sequential(
            CausalConv1d(channels, channels, kernel_size, dilation),
            nn.BatchNorm1d(channels),
            nn.GELU(),
            nn.Dropout(dropout),
            CausalConv1d(channels, channels, kernel_size, dilation),
            nn.BatchNorm1d(channels),
        )
        self.act = nn.GELU()

    def forward(self, x):
        return self.act(x + self.net(x))


class FiLMConditioner(nn.Module):
    """Feature-wise Linear Modulation: context → (gamma, beta) for conditioning."""

    def __init__(self, context_size: int, hidden: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(context_size, hidden),
            nn.GELU(),
        )
        self.gamma = nn.Linear(hidden, hidden)
        self.beta = nn.Linear(hidden, hidden)

    def forward(self, context):
        h = self.net(context)
        return self.gamma(h), self.beta(h)


# ---------------------------------------------------------------------------
# v1: ResidualMLP (raw features only)
# ---------------------------------------------------------------------------


class ResidualMLP(nn.Module):
    """Residual MLP for single-snapshot prediction on raw features."""

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


# ---------------------------------------------------------------------------
# v2: ContextMLP (raw + cross-candle, single-snapshot)
# ---------------------------------------------------------------------------


class ContextMLP(nn.Module):
    """ResidualMLP on all features (raw + cross-candle), single-snapshot."""

    def __init__(
        self,
        input_size: int = 33,
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
        # x: (batch, input_size)
        x = self.input_proj(x)
        for block in self.blocks:
            x = block(x)
        return self.head(x)


# ---------------------------------------------------------------------------
# v2: ContextConditionedTCN (FiLM + temporal conv)
# ---------------------------------------------------------------------------


class ContextConditionedTCN(nn.Module):
    """FiLM-conditioned temporal convolution for sequence classification.

    Temporal branch processes raw snapshot sequences via causal conv.
    Context branch modulates the temporal representation via FiLM
    (gamma * hidden + beta) using cross-candle indicators.

    Input: (batch, seq_len, raw_size + context_size)
      - First raw_size columns vary per timestep (raw snapshot features)
      - Last context_size columns are constant per candle (cross-candle indicators)
    """

    def __init__(
        self,
        raw_size: int = 11,
        context_size: int = 22,
        hidden: int = 64,
        n_blocks: int = 3,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.raw_size = raw_size
        self.context_size = context_size

        # Temporal branch
        self.temporal_proj = nn.Conv1d(raw_size, hidden, 1)
        self.temporal_blocks = nn.ModuleList(
            [TCNBlock(hidden, kernel_size=3, dilation=2**i, dropout=dropout) for i in range(n_blocks)]
        )

        # Context branch (FiLM)
        self.film = FiLMConditioner(context_size, hidden)

        # Classification head
        self.head_block = ResidualBlock(hidden, dropout)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):
        if x.dim() == 2:
            # Single-snapshot fallback: (batch, raw+context) → treat as seq_len=1
            x = x.unsqueeze(1)

        # Split features
        raw = x[:, :, : self.raw_size]  # (batch, seq_len, raw_size)
        context = x[:, 0, self.raw_size :]  # (batch, context_size) — take first timestep (constant)

        # Temporal branch: (batch, seq_len, raw) → (batch, raw, seq_len) → TCN → pool
        t = raw.transpose(1, 2)
        t = self.temporal_proj(t)
        for block in self.temporal_blocks:
            t = block(t)
        t = t.mean(dim=2)  # global avg pool → (batch, hidden)

        # FiLM conditioning
        gamma, beta = self.film(context)
        conditioned = gamma * t + beta

        # Head
        return self.head(self.head_block(conditioned))


# ---------------------------------------------------------------------------
# v2: ContextAttention (FiLM + self-attention)
# ---------------------------------------------------------------------------


class ContextAttention(nn.Module):
    """FiLM-conditioned self-attention for sequence classification.

    Same input format as ContextConditionedTCN.
    """

    def __init__(
        self,
        raw_size: int = 11,
        context_size: int = 22,
        d_model: int = 64,
        n_heads: int = 4,
        n_layers: int = 2,
        seq_len: int = 50,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.raw_size = raw_size
        self.context_size = context_size

        # Temporal branch
        self.input_proj = nn.Linear(raw_size, d_model)
        self.pos_embed = nn.Parameter(torch.randn(1, seq_len, d_model) * 0.02)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_model * 2,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

        # Context branch (FiLM)
        self.film = FiLMConditioner(context_size, d_model)

        # Head
        self.head_block = ResidualBlock(d_model, dropout)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x):
        if x.dim() == 2:
            x = x.unsqueeze(1)

        raw = x[:, :, : self.raw_size]
        context = x[:, 0, self.raw_size :]

        # Attention on raw features
        t = self.input_proj(raw) + self.pos_embed[:, : raw.size(1), :]
        t = self.encoder(t)
        t = t.mean(dim=1)  # pool

        # FiLM conditioning
        gamma, beta = self.film(context)
        conditioned = gamma * t + beta

        return self.head(self.head_block(conditioned))
