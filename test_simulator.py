"""Exercise the deployed simulator function and its real Streamlit UI in isolation.

Extract only simulator code so tests never fetch live NHL data or execute the board.
"""
import ast
import copy
import hashlib
from pathlib import Path
import textwrap
import unittest
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

SOURCE = Path(__file__).with_name('app.py').read_text()
TREE = ast.parse(SOURCE)
FUNCTION = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'run_goal_monte_carlo')
FUNCTION_SOURCE = ast.get_source_segment(SOURCE, FUNCTION)
SCOPE = dict(np=np, pd=pd, hashlib=hashlib)
exec(FUNCTION_SOURCE, SCOPE)
run_sim = SCOPE['run_goal_monte_carlo']


def record(pid='123', **changes):
    values = dict(player_id=pid, player='Test Player', team='BUF', overall_rank=2,
                  team_rank=1, hammer='🔨', goals=12, shots=120, gp=40,
                  season_spg=3., recent_spg=3., opp_ga=3., goalie_match=50.,
                  goal_match=70., goal_threat=75., final_anytime=80.,
                  lineup_status='Projected', shot_trend=.5)
    values.update(changes)
    return tuple(values.values())


class SimulatorTests(unittest.TestCase):
    def test_repeatable_and_order_independent(self):
        records = (record('1'), record('2', recent_spg=4))
        before = copy.deepcopy(records)
        first = run_sim(records, '2026-11-09')
        pd.testing.assert_frame_equal(first, run_sim(records, '2026-11-09'))
        pd.testing.assert_frame_equal(first, run_sim(records[::-1], '2026-11-09').iloc[::-1].reset_index(drop=True))
        self.assertEqual(records, before)
        for col, expected in [('Overall Rank', 2), ('Team Rank', 1), ('Hammer', '🔨'), ('Final Anytime', 80.)]:
            self.assertEqual(first.loc[0, col], expected)

    def test_agrees_with_known_poisson_probability(self):
        result = run_sim((record(),), '2026-11-09').iloc[0]
        # Neutral opponent/goalie: conversion=(12+3)/(120+30)=0.1, lambda=3.
        self.assertAlmostEqual(result['Sim Goal %'], 100*(1-np.exp(-.3)), delta=2)
        self.assertAlmostEqual(result['Sim Avg Goals'], .3, delta=.025)
        self.assertEqual(result['Sim Trials'], 10000)

    def test_bad_stats_are_missing_not_zero(self):
        for changes in [dict(gp=0), dict(gp=4), dict(shots=9), dict(goals=121),
                        dict(goals=None), dict(shots=np.nan), dict(season_spg=np.inf),
                        dict(season_spg=-1)]:
            with self.subTest(changes=changes):
                row = run_sim((record(**changes),), '2026-11-09').iloc[0]
                self.assertTrue(pd.isna(row['Sim Goal %']))
                self.assertEqual(row['Sim Status'], 'Insufficient data')

    def test_zero_shots_volume_is_valid(self):
        row = run_sim((record(season_spg=0, recent_spg=0),), '2026-11-09').iloc[0]
        self.assertEqual(row['Sim Goal %'], 0)

    def test_missing_recent_uses_season(self):
        row = run_sim((record(recent_spg=None, goalie_match=None, opp_ga=None),), '2026-11-09').iloc[0]
        self.assertEqual(row['Sim Status'], 'Season shots fallback')
        self.assertTrue(0 < row['Sim Goal %'] < 100)

    def test_trial_validation(self):
        for value in (0, -1, 100001, 10.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_sim((record(),), '2026-11-09', value)

    def test_simulator_ui_rerun_download_and_changed_data(self):
        start = SOURCE.index('        st.divider()\n        st.subheader("🎲 10,000-Run')
        end = SOURCE.index('        with st.expander("📈 Shot Opportunity Watch', start)
        ui = textwrap.dedent(SOURCE[start:end])
        styles = '\n\n'.join(ast.get_source_segment(SOURCE, n) for n in TREE.body
                               if isinstance(n, ast.FunctionDef) and n.name == 'style_board_score')
        header = '''import streamlit as st
import pandas as pd
import numpy as np
import hashlib
from datetime import date
selected_date = date(2026, 11, 9)
volume = st.number_input("Test volume", value=3.)
skaters_df = pd.DataFrame([{"Player_ID": 1, "Player": "Test Player", "Team": "BUF",
"Overall Rank": 2, "Team Rank": 1, "Hammer": "🔨", "Goals": 12, "Shots": 120,
"GP": 40, "S/GP": volume, "L5 S/GP": volume, "Opp GA/GP": 3., "Goalie Match": 50.,
"Goal Match": 70., "Goal Threat": 75., "Final Anytime": 80.,
"Lineup Status": "Projected", "Shot Trend": .5}])
'''
        at = AppTest.from_string(header + FUNCTION_SOURCE + '\n' + styles + '\n' + ui).run()
        self.assertEqual(len(at.exception), 0)
        at.button[0].click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.dataframe), 1)
        self.assertIn('Sim Rank', at.dataframe[0].value.columns)
        self.assertEqual(at.dataframe[0].value.iloc[0]['Overall Rank'], 2)
        at.run()
        self.assertEqual(len(at.dataframe), 1)
        self.assertIn('Download simulation results', at.get('download_button')[0].label)
        at.number_input[0].set_value(4.).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.dataframe), 0, 'Changed inputs must invalidate old results')


if __name__ == '__main__':
    unittest.main()
