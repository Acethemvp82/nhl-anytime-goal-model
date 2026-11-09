import unittest
import pandas as pd
from simulation import simulate_anytime_goal, simulate_skaters


class SimulationTests(unittest.TestCase):
    def test_deterministic(self):
        kw = dict(shots_per_game=3, goals=12, shots=120,
                  games_played=40, trials=10000, seed=42)
        self.assertEqual(simulate_anytime_goal(**kw),
                         simulate_anytime_goal(**kw))

    def test_invalid_data(self):
        self.assertIsNone(simulate_anytime_goal(
            shots_per_game=2, goals=5, shots=4, games_played=10))
        self.assertIsNone(simulate_anytime_goal(
            shots_per_game=None, goals=5, shots=40, games_played=10))

    def test_preserves_board(self):
        df = pd.DataFrame([dict(Player_ID=123, Player="Test", Goals=12,
                                Shots=120, GP=40, **{"L10 S/GP": 3,
                                "Final Anytime": 82, "Team Rank": 1,
                                "Hammer": "🔨"})])
        before = df.copy(deep=True)
        result = simulate_skaters(df, slate_date="2026-11-09")
        pd.testing.assert_frame_equal(df, before)
        self.assertEqual(result.loc[0, "Final Anytime"], 82)
        self.assertTrue(0 <= result.loc[0, "Sim Goal %"] <= 100)


if __name__ == "__main__":
    unittest.main()
