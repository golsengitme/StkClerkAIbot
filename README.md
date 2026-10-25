# StkClerkAIbot

AI assistant for the West Jordan Utah Copper Hills Stake clerk.

The procedures it should answer from are in `docs/stake-clerk-training-manual.md`.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # add your keys
uv run stkclerkaibot
```
