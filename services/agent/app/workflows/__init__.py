"""Orchestration: the main graph (main.py) routes each message to a workflow —
the receipt workflow (receipt.py), the bookkeeping assistant (assistant.py) — and
categorization (categorize.py) is a subgraph both share."""

from .main import build_main_graph

__all__ = ["build_main_graph"]
