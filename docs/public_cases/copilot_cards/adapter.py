"""仅模拟终端输入并观察上游真实执行后的牌组，不生成或修正牌。"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
from unittest.mock import patch


def inspect_deck(num_players, metric):
    answers = [str(num_players)] + ["Player " + str(i + 1) for i in range(num_players)]
    with patch("builtins.input", side_effect=answers), redirect_stdout(io.StringIO()):
        result = runpy.run_path(str(Path(__file__).with_name("upstream.py")), run_name="__main__")
    hands = [player["hand"] for player in result["players"]]
    dealt = [card for hand in hands for card in hand]
    all_cards = result["deck"] + dealt
    if metric == "deck_count":
        return len(all_cards)
    if metric == "cards":
        return sorted(all_cards)
    if metric == "hand_sizes":
        return [len(hand) for hand in hands]
    if metric == "dealt_unique":
        return len(dealt) == len(set(dealt))
    raise ValueError("Unknown observation metric")
