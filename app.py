import streamlit as st
import pandas as pd
import requests
import time
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
def get_goalie_stats(team):
    url = (
        "https://api.nhle.com/stats/rest/en/goalie/summary"
        f"?cayenneExp=teamAbbrevs=\"{team}\""
    )

    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json()

try:
    schedule_data = get_nhl_schedule()

    games = []

    for week in schedule_data.get("gameWeek", []):   
        game_date = week.get("date", "")
        
        for game in week.get("games", []):
            away = game.get("awayTeam", {}).get("abbrev", "TBD")
            home = game.get("homeTeam", {}).get("abbrev", "TBD")

            games.append({
                "Game_ID": game.get("id"),
                "Date": game_date,
                "Away": away,
                "Home": home,
                "Status": game.get("gameState", "")
            })
            
                

    if games:
        schedule_df = pd.DataFrame(games)

        available_dates = sorted(schedule_df["Date"].unique())

        selected_date = st.selectbox(
            "📅 Select Game Date",
            available_dates
        )

        daily_schedule = schedule_df[
            schedule_df["Date"] == selected_date
        ].copy()

        st.subheader(f"🏒 NHL Schedule — {selected_date}")
        st.dataframe(
            daily_schedule,
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

                   # Goalie matchup data
    goalie_map = {}

    for team in slate_teams:
        goalie_stats = get_goalie_stats(team)
        goalie_data = goalie_stats.get("data", [])

        if goalie_data:
            goalie_row = goalie_data[0]
            goalie_map[team] = {
               "Goalie": goalie_row.get("goalieFullName", "Unknown"), 
                "SV%": goalie_row.get("savePct", 0),
                "GAA": goalie_row.get("goalsAgainstAverage", 0)
            }
        else:
            goalie_map[team] = {
                "Goalie": "Unknown",
                "SV%": 0,
                "GAA": 0
            } 
        
    game_data_map = {}       

    for team in slate_teams:
             game_id = game_id_map.get(team)

             if game_id:
                 game_data_map[team] = get_game_data(game_id)
             else:
                 game_data_map[team] = {}   
    skaters = []      

    for team in slate_teams:
            roster = get_team_roster(team)
            
            for position_group in ["forwards", "defensemen"]:
                for player in roster.get(position_group, []):
                    first_name = player.get("firstName", {}).get("default", "")
                    last_name = player.get("lastName", {}).get("default", "")
                    position = player.get("positionCode", "")
                    player_id = player.get("id")
                    player_stats = get_player_stats(player_id)

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
                    # Pull opponent goalie from the selected game's gamecenter data
                    if game_data:
                        away_team = game_data.get("awayTeam", {}).get("abbrev", "")
                        home_team = game_data.get("homeTeam", {}).get("abbrev", "")

                        if team == away_team:
                            opponent_side = game_data.get("homeTeam", {})
                        else:
                            opponent_side = game_data.get("awayTeam", {})
                    # Use the opponent team's current goalie data
                    if opponent in goalie_map:
                    opp_goalie = goalie_map[opponent]
                    opp_goalie_name = opp_goalie.get("Goalie", "Unknown")     

                    goalie_sv = opp_goalie.get("SV%") or 0
                    goalie_gaa = opp_goalie.get("GAA") or 0
                    if goalie_sv > 0 and goalie_gaa > 0:
                        sv_weakness = max(0, min((0.920 - goalie_sv) / 0.050, 1.0)) * 50
                        gaa_weakness = max(0, min(goalie_gaa / 4.0, 1.0)) * 50
                        goalie_match = round(sv_weakness + gaa_weakness, 1)
                    else:
                        goalie_match = 0
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
                        "Opp Goalie": opp_goalie_name,
                        "Goal Threat": goal_threat,
                        "Goal Match": goal_match,
                        "Goalie Match": goalie_match,
                        "Final Anytime": final_anytime,
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
        skaters_df = skaters_df.sort_values(
            by=["Team", "Goal Threat"],
            ascending=[True, False]
        ).reset_index(drop=True)
        if "Rank" in skaters_df.columns:
            skaters_df = skaters_df.drop(columns=["Rank"])
        skaters_df.insert(
            0,
            "Team Rank",
            skaters_df.groupby("Team").cumcount() + 1
        )

        st.subheader("🏒 Today's Skaters")
        st.dataframe(
            skaters_df,
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
