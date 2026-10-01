import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime
from zoneinfo import ZoneInfo
st.set_page_config(
    page_title="NHL Anytime Goal Model",
    page_icon="🏒",
    layout="wide"
)

st.title("🏒 NHL Anytime Goal Scorer Model")
st.caption("Goal Threat • Goal Match • Goalie Match • Final Anytime")

st.success("NHL Anytime Goal Model is running.")

@st.cache_data(ttl=300)
def get_nhl_schedule():
    url = "https://api-web.nhle.com/v1/schedule/now"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json()
@st.cache_data(ttl=1800)
def get_team_roster(team):
    url = f"https://api-web.nhle.com/v1/roster/{team}/current"

    for attempt in range(3):
        response = requests.get(url, timeout=15)

        if response.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue

        response.raise_for_status()
        return response.json()

    return {}
@st.cache_data(ttl=300)
def get_game_data(game_id):
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"

    for attempt in range(3):
        response = requests.get(url, timeout=15)

        if response.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue

        response.raise_for_status()
        return response.json()

    return {}
@st.cache_data(ttl=1800)
def get_player_stats(player_id):
    url = f"https://api-web.nhle.com/v1/player/{player_id}/landing"

    for attempt in range(3):
        response = requests.get(url, timeout=15)

        if response.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue

        response.raise_for_status()
        return response.json()

    return {}     

    

@st.cache_data(ttl=1800)
def get_team_stats(team):
    url = f"https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=teamAbbrev=%22{team}%22"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=1800)
def get_goalie_stats(player_id):
    current_season = "20262027"

    url = (
"https://api.nhle.com/stats/rest/en/goalie/summary"
    f"?cayenneExp=seasonId={current_season}%20and%20playerId={player_id}"
)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()

        goalies = data.get("data", [])

        return data

    except requests.RequestException:
        return {"data": []}
games = []
try:
    schedule_data = get_nhl_schedule()
    
    for week in schedule_data.get("gameWeek", []):   
        game_date = week.get("date", "")
        
        for game in week.get("games", []):
            away = game.get("awayTeam", {}).get("abbrev", "TBD")
            home = game.get("homeTeam", {}).get("abbrev", "TBD")
            start_time_utc = game.get("startTimeUTC", "")
            if start_time_utc:
                start_dt = pd.to_datetime(start_time_utc, utc=True).tz_convert(ZoneInfo("America/New_York"))
                start_time = start_dt.strftime("%-I:%M %p")
            else:
                start_time = "TBD"
            games.append({
                "Game_ID": game.get("id"),
                "Date": game_date,
                "Away": away,
                "Home": home,
                "Time": start_time,
                "Status": game.get("gameState", "")
            })
            
                

    if games:
        schedule_df = pd.DataFrame(games)

        available_dates = sorted(schedule_df["Date"].unique())
        today_str = datetime.now().strftime("%Y-%m-%d")

    default_index = (
        available_dates.index(today_str)
        if today_str in available_dates
        else len(available_dates) - 1
    )
    selected_date = st.selectbox(
    "📅 Select Game Date",
    available_dates,
    index=default_index
        )

    daily_schedule = schedule_df[
            schedule_df["Date"] == selected_date
        ].copy()

    st.subheader(f"🏒 NHL Schedule — {selected_date}")
    st.dataframe(
            daily_schedule.drop(columns=["Game_ID"]),
            use_container_width=True,
            hide_index=True
        )
    slate_teams = sorted(
    set(daily_schedule["Away"].tolist() + daily_schedule["Home"].tolist())
    )
    opponent_map = {}
    game_id_map = {}
    for _, game in daily_schedule.iterrows():
            away_team = game["Away"]
            home_team = game["Home"]
            game_id_map[away_team] = game["Game_ID"]
            game_id_map[home_team] = game["Game_ID"]
            opponent_map[away_team] = home_team
            opponent_map[home_team] = away_team
            # Opponent goals-against per game
    opp_ga_map = {}

    for team in slate_teams:
            team_stats = get_team_stats(team)
            data = team_stats.get("data", [])

            if data:
                opp_ga_map[team] = round(data[0].get("goalsAgainstPerGame", 0), 2)
            else:
                opp_ga_map[team] = 0
    game_data_map = {}

    for team in slate_teams:
        game_id = game_id_map.get(team)

        if game_id:
            game_data_map[team] = get_game_data(game_id)
        else:
            game_data_map[team] = {}     
    # Goalie matchup data from GameCenter
    goalie_map = {}

    for team in slate_teams:
        goalie_map[team] = {
            "Goalie": "Unknown",
            "Player_ID": None,
            "SV%": 0,
            "GAA": 0
        }

        game_data = game_data_map.get(team, {})
        player_stats = game_data.get("playerByGameStats", {})

        if player_stats:
            away_team = game_data.get("awayTeam", {}).get("abbrev", "")
            side = "awayTeam" if team == away_team else "homeTeam"
            team_game_stats = player_stats.get(side, {})
            goalies = team_game_stats.get("goalies", [])

            if goalies:
                goalie = goalies[0]
                goalie_id = goalie.get("playerId")
                goalie_stats = get_goalie_stats(goalie_id)
                
                stats_rows = goalie_stats.get("data", [])

                if stats_rows:
                    season_goalie = stats_rows[0]
                    goalie_sv = season_goalie.get("savePct", 0) or 0
                    goalie_gaa = season_goalie.get("goalsAgainstAverage", 0) or 0
                else:
                    goalie_sv = 0
                    goalie_gaa = 0

                goalie_map[team] = {
                    "Goalie": goalie.get("name", {}).get("default", "Unknown"),
                    "Player_ID": goalie_id,
                    "SV%": goalie_sv,
                    "GAA": goalie_gaa
                }
    skaters = []      

    for team in slate_teams:
        roster = get_team_roster(team)
        game_data = game_data_map.get(team, {})
        st.write(team, roster.keys() if roster else "EMPTY ROSTER")
        # Get the skaters actually dressed for this game when available
        dressed_ids = set()

        player_stats = game_data.get("playerByGameStats", {})

        if player_stats:
            away_team = game_data.get("awayTeam", {}).get("abbrev", "")
            side = "awayTeam" if team == away_team else "homeTeam"
            team_game_stats = player_stats.get(side, {})

            for group in ["forwards", "defense"]:
                for dressed_player in team_game_stats.get(group, []):
                    player_id = dressed_player.get("playerId")
                    if player_id:
                        dressed_ids.add(player_id)   
            
        for position_group in ["forwards", "defensemen"]:
            for player in roster.get(position_group, []):
                first_name = player.get("firstName", {}).get("default", "")
                last_name = player.get("lastName", {}).get("default", "")
            position = player.get("positionCode", "")
            player_id = player.get("id")
            # If dressed skaters are available, skip scratches/non-starters
            if dressed_ids and player_id not in dressed_ids:
                continue
                player_stats = get_player_stats(player_id)
                st.write("PLAYER TEST:", first_name, last_name, bool(player_stats))
                if not player_stats:
                    st.warning(f"No player stats returned for {first_name} {last_name} ({player_id})")
                    featured = player_stats.get("featuredStats", {})
                    season_stats = featured.get("regularSeason", {}).get("subSeason", {})

                    games_played = season_stats.get("gamesPlayed") or 0
                    goals = season_stats.get("goals") or 0
                    shots = season_stats.get("shots") or 0

                    if games_played == 0:
                        career_stats = featured.get("regularSeason", {}).get("career", {})
                        games_played = career_stats.get("gamesPlayed") or 0
                        goals = career_stats.get("goals") or 0
                        shots = career_stats.get("shots") or 0

                    goals_per_game = round(goals / games_played, 3) if games_played else 0
                    shots_per_game = round(shots / games_played, 2) if games_played else 0
                    opponent = opponent_map.get(team, "TBD")
                    opponent_stats = get_team_stats(opponent)

                    opponent_data = opponent_stats.get("data", [])

                    if opponent_data:
                        opponent_row = opponent_data[0]
                        opp_goals_against = opponent_row.get("goalsAgainst", 0)
                        opp_games_played = opponent_row.get("gamesPlayed", 0)

                        opp_ga_per_game = (
                            round(opp_goals_against / opp_games_played, 2)
                            if opp_games_played else 0
                        )
                    else:
                        opp_ga_per_game = 0

                    goal_rate_score = min(goals_per_game / 0.60, 1.0) * 50
                    shot_rate_score = min(shots_per_game / 4.0, 1.0) * 50

                    goal_threat = round(goal_rate_score + shot_rate_score, 1)
                    matchup_score = min(opp_ga_per_game / 4.0, 1.0) * 100

                    goal_match = round(
                        (goal_threat * 0.70) +
                        (matchup_score * 0.30),
                        1
                    )
                    opponent = opponent_map.get(team, "TBD")
                    opp_goalie = goalie_map.get(opponent, {"SV%": 0, "GAA": 0})
                    opp_goalie_name = opp_goalie.get("Goalie", "Unknown")
                    game_data = game_data_map.get(team, {})
                    game_id = game_id_map.get(team)
                  # Identify opponent goalie from this game's data
                    opp_goalie_name = "Unknown"
                    if game_data:
                     away_team = game_data.get("awayTeam", {}).get("abbrev", "")
                    home_team = game_data.get("homeTeam", {}).get("abbrev", "")
                
                    if team == away_team:
                        opponent_side = game_data.get("homeTeam", {})
                    else:
                        opponent_side = game_data.get("awayTeam", {})
                
                    # Use current-season goalie stats when available
                    if opponent in goalie_map:
                        opp_goalie = goalie_map[opponent]
                        opp_goalie_name = opp_goalie.get("Goalie", "Unknown")
                    else:
                        opp_goalie = {"SV%": 0, "GAA": 0}

                    goalie_sv = opp_goalie.get("SV%", 0) or 0
                    goalie_gaa = opp_goalie.get("GAA", 0) or 0

                    if goalie_sv > 0:
                        sv_weakness = max(0, min((0.920 - goalie_sv) / 0.050, 1.0)) * 100
                        goalie_match = round(sv_weakness, 1)
                    else:
                        goalie_match = 50
                    final_anytime = round(
                        (goal_match * 0.75) +
                        (goalie_match * 0.25),
                        1
                    )
                    
                    skaters.append({
                        "Player": f"{first_name} {last_name}".strip(),
                        "Team": team,
                        "Opponent": opponent_map.get(team, "TBD"),
                        "Opp GA/GP": opp_ga_map.get(opponent_map.get(team, ""), 0),
                        "Goal Threat": goal_threat,
                        "Goal Match": goal_match,
                        "Final Anytime": final_anytime,
                        "Goalie Match": goalie_match,
                        "Opp Goalie": opp_goalie_name,
                        "Position": position,
                        "GP": games_played,
                        "Goals": goals,
                        "G/GP": goals_per_game,
                        "Shots": shots,
                        "S/GP": shots_per_game,
                        "Player_ID": player_id
                    })
                        
           
                        
                        
                    
                         
                         

    if skaters:
        skaters_df = pd.DataFrame(skaters)

        # Rank players by the model's strongest scoring signal
        skaters_df = skaters_df.sort_values(
            by=["Final Anytime", "Goal Match", "Goal Threat"],
            ascending=[False, False, False]
        ).reset_index(drop=True)

        for col in ["Rank", "Overall Rank", "Team Rank"]:
            if col in skaters_df.columns:
                skaters_df = skaters_df.drop(columns=[col])

        skaters_df.insert(
            0,
            "Overall Rank",
            range(1, len(skaters_df) + 1)
        )
    
        skaters_df.insert(
            1,
            "Team Rank",
            skaters_df.groupby("Team").cumcount() + 1
        )
        def color_final_anytime(val):
            if val >= 70:
                return "background-color: #00c853; color: white; font-weight: bold"
            elif val >= 60:
                 return "background-color: #64dd17; color: black; font-weight: bold"
            elif val >= 50:
                return "background-color: #ffd600; color: black; font-weight: bold"
            elif val >= 40:
                return "background-color: #ff9100; color: black; font-weight: bold"
            else:
                return ""
        def color_goal_threat(val):
            if val >= 70:
                return "background-color: #00c853; color: white; font-weight: bold"
            elif val >= 60:
                return "background-color: #64dd17; color: black; font-weight: bold"
            elif val >= 50:
                return "background-color: #ffd600; color: black; font-weight: bold"
            elif val >= 40:
                return "background-color: #ff9100; color: black; font-weight: bold"
            else:
                return ""
        
        
        def color_goal_match(val):
            if val >= 70:
                return "background-color: #00c853; color: white; font-weight: bold"
            elif val >= 60:
                return "background-color: #64dd17; color: black; font-weight: bold"
            elif val >= 50:
                return "background-color: #ffd600; color: black; font-weight: bold"
            elif val >= 40:
                return "background-color: #ff9100; color: black; font-weight: bold"
            else:
                return ""
        def color_goalie_match(val):
            if val >= 70:
                return "background-color: #00c853; color: white; font-weight: bold"
            elif val >= 60:
                return "background-color: #64dd17; color: black; font-weight: bold"
            elif val >= 50:
                return "background-color: #ffd600; color: black; font-weight: bold"
            elif val >= 40:
                return "background-color: #ff9100; color: black; font-weight: bold"
            else:
                return ""    
        
        def anytime_tier(val):
            if val >= 70:
                return "🔥 ELITE"
            elif val >= 60:
                return "🟢 STRONG"
            elif val >= 50:
                return "🟡 GOOD"
            elif val >= 40:
                return "🟠 LEAN"
            else:
                return "PASS"

        skaters_df["Bet Tier"] = skaters_df["Final Anytime"].apply(anytime_tier)
        for col in ["Opp GA/GP", "Goal Threat", "Goal Match", "Goalie Match", "Final Anytime"]:
            if col in skaters_df.columns:
                skaters_df[col] = skaters_df[col].round(1)
        display_df = skaters_df.drop(columns=["Opponent"], errors="ignore")
        cols = list(display_df.columns)
        cols.remove("Bet Tier")
        final_idx = cols.index("Final Anytime")
        cols.insert(final_idx + 1, "Bet Tier")
        display_df = display_df[cols]
        st.subheader("🏒 Today's Skaters")
        st.dataframe(
        display_df.style
          .map(
              color_goal_threat,
              subset=["Goal Threat"]
         )
         .map(
             color_goal_match,
             subset=["Goal Match"]
         )
        .map(
            color_goalie_match,
            subset=["Goalie Match"]
        )
            
         .map(
             color_final_anytime,
             subset=["Final Anytime"]
         )
         .format({
             "Opp GA/GP": "{:.2f}",
             "Goal Threat": "{:.1f}",
             "Goal Match": "{:.1f}",
             "Goalie Match": "{:.1f}",
             "Final Anytime": "{:.1f}",
         }),
            
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("No NHL games found.")

except Exception as e:
    st.error(f"Could not load NHL schedule: {e}")
           

    if games:
        schedule_df = pd.DataFrame(games)
        st.subheader("🏒 NHL Schedule")
        st.dataframe(schedule_df, use_container_width=True, hide_index=True)
    else:
        st.warning("No NHL games found.")

except Exception as e:
    st.error(f"Could not load NHL schedule: {e}")
