# AI-Driven Equity Research & Portfolio Decision Support System

> [!WARNING]
> **SURVIVOR-BIASED DATASET NOTICE**
> Every result, metric, signal, and report produced by this project carries the label **`SURVIVOR-BIASED`**.
> The historical dataset contains only tickers that survived through February 2026 (no delistings, no bankruptcies, no acquisitions).
> Absolute returns, base rates, and SELL-signal validation are optimistic and cannot be treated as real-world expectations.
> Relative comparisons between models on identical data remain informative, but this system is strictly a decision-support research tool, **not** investment advice or an automated trading bot.

---

## 1. Overview

This project is a research-grade decision-support platform for large-cap Nasdaq-100 stocks. For every trading day and eligible stock, it:
1. Predicts relative performance over the next 20 trading days (excess return vs. universe average).
2. Converts predictions into transparent `BUY` / `HOLD` / `SELL` / `AVOID` / `NEUTRAL` signals via an explicit, rule-based engine.
3. Applies a risk layer (volatility veto, position size limits).
4. Constructs a top-$N$ equal-weighted portfolio.
5. Evaluates the complete pipeline through a realistic, cost-aware, leakage-controlled walk-forward backtest.
6. Presents findings, explainability (SHAP & permutation importance), and empirical limitations via a Streamlit dashboard.

The core scientific product is **evaluation honesty and leak-free methodology**.

---

## 2. Global Contracts & Time Conventions

- **Decision Time:** Close of day $t$. All features, universe eligibility, and signals use information dated $\le t$ only.
- **Execution:** Orders fill at the **adjusted open of $t+1$**.
- **Exit Reference:** The label's exit price is the adjusted open of $t+1+h$ ($h=20$ trading days).
- **Label Definition:**
  $$\text{Label}(t, h) = \ln\left(\frac{\text{Adj Open}_{t+1+h}}{\text{Adj Open}_{t+1}}\right)$$
- **Target ($y$):** 20-day forward excess log return over the eligible universe mean.
- **Locked Test Period:** Dates $\ge$ 2020-01-02 are strictly locked behind an automated programmatic guard until Stage S16.

---

## 3. Quickstart

### Prerequisites
- Python $\ge 3.11$ (CPU-only, no GPU required)
- Git

### Installation
```bash
# Clone the repository
git clone <repo-url>
cd AI-Equity-Research-System

# Create and activate virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# Install package in editable mode with development dependencies
pip install -e ".[dev]"
```

### Basic Commands
```bash
# Inspect current project stage and status
python -m nasdaq100.cli status

# Run test suite
pytest
```
