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

    for attempt in range(5):
        try:
            response = requests.get(url, timeout=15)

            if response.status_code == 429:
                wait_time = 3 * (attempt + 1)
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException:
            if attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            return {}

    return {}


@st.cache_data(ttl=3600)
def get_recent_shots(player_id, season_id, before_date):
    """Use completed regular-season games before the slate, across seasons."""
    logs = []
    seasons = [season_id]
    prior_start = int(season_id[:4]) - 1
    seasons.append(f"{prior_start}{prior_start + 1}")
    for season in seasons:
        url = f"https://api-web.nhle.com/v1/player/{player_id}/game-log/{season}/2"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            season_logs = payload.get("gameLog", [])
            logs.extend(
                row for row in season_logs
                if str(row.get("gameDate", "")) < str(before_date)
                and row.get("shots") is not None
            )
        except (requests.RequestException, ValueError, TypeError):
            continue
        if len(logs) >= 10:
            break
    logs.sort(key=lambda row: str(row.get("gameDate", "")), reverse=True)
    if not logs:
        return None
    shots = [float(row["shots"]) for row in logs[:10]]
    l5 = shots[:5]
    return {
        "L5 S/GP": round(sum(l5) / 5, 2) if len(l5) == 5 else None,
        "L10 S/GP": round(sum(shots) / 10, 2) if len(shots) == 10 else None,
        "Shot Trend": round(sum(l5) / 5 - sum(shots) / 10, 2) if len(shots) == 10 else None,
        "Shot Games": len(shots),
    }


@st.cache_data(ttl=1800)
def get_team_stats(team):
    url = f"https://api.nhle.com/stats/rest/en/team/summary?cayenneExp=teamAbbrev=%22{team}%22"

    for attempt in range(5):
        try:
            response = requests.get(url, timeout=15)

            if response.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException:
            if attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            return {}

    return {}

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
except requests.RequestException as e:
    st.error(f"Could not load NHL schedule: {e}")
                

if games:
    schedule_df = pd.DataFrame(games)

    available_dates = sorted(schedule_df["Date"].unique())
    today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

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
    game_time_map = {}
    for _, game in daily_schedule.iterrows():
            away_team = game["Away"]
            home_team = game["Home"]
            game_id_map[away_team] = game["Game_ID"]
            game_id_map[home_team] = game["Game_ID"]
            game_time_map[away_team] = game["Time"]
            game_time_map[home_team] = game["Time"]
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
            "GAA": 0,
            "Status": "Unknown"
        }

        game_data = game_data_map.get(team, {})
        player_stats = game_data.get("playerByGameStats", {})

        if player_stats:
            away_team = game_data.get("awayTeam", {}).get("abbrev", "")
            side = "awayTeam" if team == away_team else "homeTeam"
            team_game_stats = player_stats.get(side, {})
            goalies = team_game_stats.get("goalies", [])

            if goalies:
                # GameCenter often lists goalies before it flags a starter.
                # Display the first listed goalie as UNCONFIRMED, never as confirmed.
                goalie = next((g for g in goalies if g.get("starter") is True), None)
                goalie_status = "Confirmed" if goalie else "Listed (unconfirmed)"
                if goalie is None:
                    goalie = goalies[0]
                goalie_id = goalie.get("playerId")
                goalie_stats = get_goalie_stats(goalie_id) if goalie_id else {"data": []}
                
                stats_rows = goalie_stats.get("data", [])

                if stats_rows:
                    season_goalie = stats_rows[0]
                    goalie_sv = season_goalie.get("savePct", 0) or 0
                    goalie_gaa = season_goalie.get("goalsAgainstAverage", 0) or 0
                else:
                    goalie_sv = 0
                    goalie_gaa = 0

                goalie_name = goalie.get("name", {})
                if isinstance(goalie_name, dict):
                    goalie_name = goalie_name.get("default", "")
                if not goalie_name:
                    first = goalie.get("firstName", {})
                    last = goalie.get("lastName", {})
                    first = first.get("default", "") if isinstance(first, dict) else first
                    last = last.get("default", "") if isinstance(last, dict) else last
                    goalie_name = f"{first} {last}".strip()
                goalie_map[team] = {
                    "Goalie": goalie_name or "Unknown",
                    "Player_ID": goalie_id,
                    "SV%": goalie_sv,
                    "GAA": goalie_gaa,
                    "Status": goalie_status
                }
    skaters = []      

    for team in slate_teams:
        roster = get_team_roster(team)
        game_data = game_data_map.get(team, {})
        
        # Get the actual dressed skaters from the GameCenter boxscore
        dressed_ids = set()

        player_by_game = game_data.get("playerByGameStats") or {}

        away_team = game_data.get("awayTeam", {}).get("abbrev", "")
        home_team = game_data.get("homeTeam", {}).get("abbrev", "")

        if team == away_team:
            team_game_stats = player_by_game.get("awayTeam", {})
        elif team == home_team:
            team_game_stats = player_by_game.get("homeTeam", {})
        else:
            team_game_stats = {}

        for group in ("forwards", "defense"):
            for dressed_player in team_game_stats.get(group, []):
                player_id = dressed_player.get("playerId")
                if player_id is not None:
                    dressed_ids.add(player_id)
          
            
        roster_players = roster.get("forwards", []) + roster.get("defensemen", [])
        roster_ids = {p.get("id") for p in roster_players}
        # Supplement an incomplete roster with dressed skaters from GameCenter.
        for group in ("forwards", "defense"):
            for dressed_player in team_game_stats.get(group, []):
                pid = dressed_player.get("playerId")
                if pid is None or pid in roster_ids:
                    continue
                first = dressed_player.get("firstName", {})
                last = dressed_player.get("lastName", {})
                first = first.get("default", "") if isinstance(first, dict) else str(first or "")
                last = last.get("default", "") if isinstance(last, dict) else str(last or "")
                roster_players.append({
                    "id": pid,
                    "firstName": {"default": first},
                    "lastName": {"default": last},
                    "positionCode": dressed_player.get("position", ""),
                })
                roster_ids.add(pid)
        if not roster_players:
            st.warning(
                f"{team} is scheduled but roster and GameCenter skaters are unavailable."
            )

        for player in roster_players:
                position = player.get("positionCode", "")
                player_id = player.get("id")
                player_stats = get_player_stats(player_id)
                # Exclude today's games to avoid post-puck-drop data leakage.
                season_start = int(selected_date[:4])
                if int(selected_date[5:7]) < 7:
                    season_start -= 1
                season_id = f"{season_start}{season_start + 1}"
                recent_shots = get_recent_shots(player_id, season_id, selected_date) or {}

                # GameCenter entries may omit firstName/lastName, but include
                # name.default; player landing also supplies fullName.
                def readable_name(value):
                    if isinstance(value, dict):
                        return str(value.get("default") or "").strip()
                    return str(value or "").strip()
                first_name = readable_name(player.get("firstName"))
                last_name = readable_name(player.get("lastName"))
                full_name = f"{first_name} {last_name}".strip()
                if not full_name:
                    full_name = readable_name(player.get("name"))
                if not full_name:
                    full_name = readable_name(player_stats.get("fullName"))
                if not full_name:
                    full_name = (
                        f"{readable_name(player_stats.get('firstName'))} "
                        f"{readable_name(player_stats.get('lastName'))}"
                    ).strip()
                if not full_name:
                    full_name = f"Player ID {player_id}"
               
        
                # Only use dressed skaters when GameCenter provides them
                if dressed_ids and player_id not in dressed_ids:
                    continue

    
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
                    sv_weakness = max(0, min((0.920 - goalie_sv) / 0.050, 1.0))
                    goalie_match = round(sv_weakness * 100, 1)
                else:
                    goalie_match = 50
    
                final_anytime = round(
                    (goal_match * 0.75) +
                    (goalie_match * 0.25),
                    1
                )
    
                skaters.append({
                    "Player": full_name.strip(),
                    "Team": team,
                    "Opponent": opponent_map.get(team, "TBD"),
                    "Game Time": game_time_map.get(team, "TBD"),
                    "Opp GA/GP": opp_ga_map.get(opponent_map.get(team, ""), 0),
                    "Goal Threat": goal_threat,
                    "Goal Match": goal_match,
                    "Final Anytime": final_anytime,
                    "Goals": goals,
                    "Goalie Match": goalie_match,
                    "Opp Goalie": opp_goalie_name,
                    "Goalie Status": opp_goalie.get("Status", "Unknown"),
                    "Lineup Status": "GameCenter" if dressed_ids else "Unconfirmed",
                    "Position": position,
                    "GP": games_played,
                    "G/GP": goals_per_game,
                    "Shots": shots,
                    "S/GP": shots_per_game,
                    "L5 S/GP": recent_shots.get("L5 S/GP"),
                    "L10 S/GP": recent_shots.get("L10 S/GP"),
                    "Shot Trend": recent_shots.get("Shot Trend"),
                    "Shot Games": recent_shots.get("Shot Games", 0),
                    "Player_ID": player_id
                })          
           
                        
                        
                    
                         
                         

    if skaters:
        skaters_df = pd.DataFrame(skaters)
        # Audit all scheduled teams before displaying rankings.
        coverage = pd.DataFrame({"Team": slate_teams})
        counts = skaters_df.groupby("Team")["Player_ID"].nunique().rename("Skaters")
        coverage = coverage.join(counts, on="Team")
        coverage["Skaters"] = coverage["Skaters"].fillna(0).astype(int)
        coverage["Lineup Status"] = coverage["Team"].map(
            skaters_df.groupby("Team")["Lineup Status"].first()
        ).fillna("Missing")
        coverage["Game Time"] = coverage["Team"].map(game_time_map)
        coverage["Coverage"] = coverage["Skaters"].apply(
            lambda count: "MISSING" if count == 0 else
            "18 SKATERS" if count == 18 else "CHECK COUNT"
        )
        missing = coverage.loc[coverage["Skaters"] == 0, "Team"].tolist()
        if missing:
            st.error("Scheduled teams missing from rankings: " + ", ".join(missing))
        with st.expander("🔎 Slate Coverage / Lineup Audit", expanded=bool(missing)):
            st.caption("18 skaters is the usual game-day count, not proof of a confirmed lineup.")
            st.dataframe(coverage, hide_index=True, use_container_width=True)


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
            if val >= 80:
                return "🔥 ELITE"
            elif val >= 70:
                return "🟢 STRONG"
            elif val >= 60:
                return "🟡 GOOD"
            elif val >= 50:
                return "🟠 LEAN"
            else:
                return "PASS"

        skaters_df["Bet Tier"] = skaters_df["Final Anytime"].apply(anytime_tier)
        for col in ["Opp GA/GP", "Goal Threat", "Goal Match", "Goalie Match", "Final Anytime"]:
            if col in skaters_df.columns:
                skaters_df[col] = skaters_df[col].round(1)
        main_columns = [
            "Overall Rank", "Team Rank", "Player", "Team", "Game Time",
            "Goal Threat", "L5 S/GP", "L10 S/GP", "Shot Trend", "Goal Match", "Goalie Match", "Final Anytime",
            "Bet Tier", "Opp Goalie", "Lineup Status",
        ]
        advanced_columns = [
            "Overall Rank", "Team Rank", "Player", "Team", "Opponent",
            "Game Time", "Goals", "GP", "G/GP", "Shots", "S/GP", "L5 S/GP", "L10 S/GP", "Shot Trend", "Shot Games",
            "Opp GA/GP", "Position", "Player_ID", "Goalie Status",
            "Goal Threat", "Goal Match", "Goalie Match", "Final Anytime",
            "Bet Tier", "Opp Goalie", "Lineup Status",
        ]
        st.subheader("🏒 Today's Goal Board")
        st.caption("Key scoring signals and rankings. Full player details are under Advanced Stats.")
        # Recent-shot feed health is informational and never changes rankings.
        shot_available = int(skaters_df["Shot Trend"].notna().sum())
        shot_total = len(skaters_df)
        st.caption(
            f"Full 10-game shot samples (including prior season if needed): {shot_available}/{shot_total} skaters. "
            "Missing values are shown as — and are not treated as zero."
        )
        if shot_available == 0:
            st.warning(
                "Recent shot logs are unavailable for this slate. "
                "Existing model rankings are unaffected."
            )

        st.dataframe(
            skaters_df[main_columns].replace({None: float("nan")}).style
            .map(color_goal_threat, subset=["Goal Threat"])
            .map(color_goal_match, subset=["Goal Match"])
            .map(color_goalie_match, subset=["Goalie Match"])
            .map(color_final_anytime, subset=["Final Anytime"])
            .format({
                "Goal Threat": "{:.1f}",
                "L5 S/GP": "{:.0f}",
                "L10 S/GP": "{:.0f}",
                "Shot Trend": "{:+.0f}",
                "Goal Match": "{:.1f}",
                "Goalie Match": "{:.1f}",
                "Final Anytime": "{:.1f}",
            }),
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("📈 Shot Opportunity Watch — informational"):
            st.caption(
                "Shot Trend = L5 shots/game minus L10 shots/game (prior season included when needed). "
                "Positive means higher recent volume, not a guaranteed goal."
            )
            watch = skaters_df.dropna(subset=["Shot Trend"]).copy()
            if watch.empty:
                st.info("No recent shot trends available yet.")
            else:
                watch["Shot Signal"] = watch["Shot Trend"].apply(
                    lambda trend: (
                        "RISING" if trend >= 1.0 else
                        "UP" if trend >= 0.4 else
                        "FALLING" if trend <= -1.0 else
                        "DOWN" if trend <= -0.4 else
                        "STEADY"
                    )
                )
                watch = watch.sort_values("Shot Trend", ascending=False)
                st.caption(
                    "RISING: +1.0 or more shots/game; UP: +0.4 to +0.99; "
                    "STEADY: between -0.4 and +0.4; DOWN: -0.4 to -0.99; "
                    "FALLING: -1.0 or less. Descriptive thresholds only."
                )
                st.dataframe(
                    watch[[
                        "Player", "Team", "Team Rank", "L5 S/GP",
                        "L10 S/GP", "Shot Trend", "Shot Signal", "Final Anytime", "Bet Tier"
                    ]].head(20),
                    use_container_width=True,
                    hide_index=True,
                )
        with st.expander("📊 Advanced Stats — Full Player Data"):
            st.dataframe(
                skaters_df[advanced_columns],
                use_container_width=True,
                hide_index=True,
            )
        # Automatic same-day goal tracker, analogous to the MLB HR Tracker.
        st.divider()
        st.subheader("🏒 Live Goal Tracker")
        st.caption("Automatically matches GameCenter goal scorers with the current model board. Rankings are live, not frozen pregame snapshots.")
        scored_rows = []
        game_states = {}
        for game_id in sorted(set(game_id_map.values())):
            if not game_id:
                continue
            boxscore = get_game_data(game_id)
            game_states[game_id] = boxscore.get("gameState", "Unknown")
            by_game = boxscore.get("playerByGameStats") or {}
            for side in ("awayTeam", "homeTeam"):
                team_abbrev = boxscore.get(side, {}).get("abbrev", "")
                for group in ("forwards", "defense"):
                    for skater in by_game.get(side, {}).get(group, []):
                        goals_scored = int(skater.get("goals") or 0)
                        if goals_scored > 0:
                            scored_rows.append({
                                "Game_ID": game_id,
                                "Player_ID": skater.get("playerId"),
                                "Team": team_abbrev,
                                "Actual Goals": goals_scored,
                            })
        if scored_rows:
            actual = pd.DataFrame(scored_rows).drop_duplicates(
                subset=["Game_ID", "Player_ID"]
            )
            live_tracker = actual.merge(
                skaters_df, on=["Player_ID", "Team"], how="left",
                indicator=True
            )
            live_tracker["Model Match"] = live_tracker["_merge"].map({
                "both": "✅ In Model", "left_only": "❌ Not In Model"
            }).astype(str)
            live_tracker["Player"] = live_tracker["Player"].fillna("Not on current board")
            tracker_columns = [
                "Player", "Team", "Actual Goals", "Overall Rank", "Team Rank",
                "Goal Threat", "L5 S/GP", "L10 S/GP", "Shot Trend",
                "Goal Match", "Final Anytime", "Bet Tier",
                "Goalie Match", "Model Match"
            ]
            st.dataframe(
                live_tracker[tracker_columns].sort_values(
                    ["Actual Goals", "Overall Rank"], ascending=[False, True]
                ), use_container_width=True, hide_index=True
            )
            st.caption("Live results update with GameCenter's 5-minute cache. Scores and rankings may change during games.")
        else:
            st.info("No goal scorers available in the selected slate's GameCenter boxscores yet.")

        # Automatic tracker, modeled on the MLB HR Tracker.
        # These are CURRENT rankings, not a frozen pregame snapshot.
        st.divider()
        st.subheader("🏒 Automatic Goal Tracker")
        st.caption(
            "Actual goal scorers from completed games on the selected slate, "
            "matched to the currently calculated model rankings. "
            "For true pregame performance, use the saved snapshot tracker below."
        )
        scorer_rows = []
        pending_games = []
        for _, scheduled_game in daily_schedule.iterrows():
            gid = scheduled_game["Game_ID"]
            game_result = get_game_data(gid)
            state = str(game_result.get("gameState", "")).upper()
            by_game = game_result.get("playerByGameStats") or {}
            if state not in ("OFF", "FINAL") or not by_game:
                pending_games.append(
                    f"{scheduled_game['Away']} vs {scheduled_game['Home']}"
                )
                continue
            for side, team_code in (
                ("awayTeam", scheduled_game["Away"]),
                ("homeTeam", scheduled_game["Home"]),
            ):
                for group in ("forwards", "defense"):
                    for skater in by_game.get(side, {}).get(group, []):
                        goals_scored = int(skater.get("goals") or 0)
                        player_id = skater.get("playerId")
                        if goals_scored > 0 and player_id is not None:
                            scorer_rows.append({
                                "Player_ID": int(player_id),
                                "Team": team_code,
                                "Actual Goals": goals_scored,
                            })
        if pending_games:
            st.info(
                f"{len(pending_games)} game(s) not final or missing boxscore data. "
                "Tracker results will appear as games finish."
            )
        if scorer_rows:
            actual_df = pd.DataFrame(scorer_rows)
            actual_df = actual_df.groupby(
                ["Player_ID", "Team"], as_index=False
            )["Actual Goals"].sum()
            model_columns = [
                "Player_ID", "Team", "Player", "Overall Rank", "Team Rank",
                "Goal Threat", "L5 S/GP", "L10 S/GP", "Shot Trend",
                "Goal Match", "Final Anytime", "Bet Tier",
                "Goalie Match", "Lineup Status",
            ]
            tracker_df = actual_df.merge(
                skaters_df[model_columns],
                on=["Player_ID", "Team"],
                how="left",
            )
            tracker_df["Model Match"] = tracker_df["Overall Rank"].apply(
                lambda rank: "In Model" if pd.notna(rank) else "Not In Model"
            )
            tracker_df["Player"] = tracker_df["Player"].fillna(
                tracker_df["Player_ID"].map(lambda pid: f"Player ID {pid}")
            )
            tracker_df = tracker_df.sort_values(
                ["Actual Goals", "Overall Rank"], ascending=[False, True]
            )
            st.metric("Goals by tracked scorers", int(tracker_df["Actual Goals"].sum()))
            st.metric(
                "Scorers in current model",
                int(tracker_df["Overall Rank"].notna().sum()),
            )
            st.dataframe(
                tracker_df[[
                    "Player", "Team", "Actual Goals", "Team Rank",
                    "Overall Rank", "Goal Threat", "L5 S/GP", "L10 S/GP",
                    "Shot Trend", "Goal Match", "Final Anytime",
                    "Bet Tier", "Goalie Match", "Model Match",
                ]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No goal scorers from completed games on this slate yet.")

        # A CSV snapshot preserves the pregame rankings independently of Streamlit reruns.
        st.divider()
        st.subheader("📊 Goal Results / Model Tracking")
        st.caption("Download a pregame snapshot BEFORE puck drop. Upload that same file after the games finish to score the frozen predictions.")
        tracking_cols = [
            "Date", "Game_ID", "Player_ID", "Player", "Team", "Opponent",
            "Overall Rank", "Team Rank", "Goal Threat", "Goal Match",
            "Final Anytime", "Bet Tier", "Goalie Match", "Opp Goalie",
            "Goalie Status", "Lineup Status"
        ]
        snapshot_df = skaters_df.copy()
        snapshot_df["Date"] = selected_date
        snapshot_df["Game_ID"] = snapshot_df["Team"].map(game_id_map)
        snapshot_df = snapshot_df[tracking_cols]
        st.download_button(
            "💾 Save Pregame Rankings (CSV)",
            data=snapshot_df.to_csv(index=False).encode("utf-8"),
            file_name=f"nhl_pregame_{selected_date}.csv",
            mime="text/csv",
            help="Save before games start; downloading again later may capture updated rankings.",
        )

        uploaded_snapshot = st.file_uploader(
            "Upload a saved pregame rankings CSV to check actual goals",
            type=["csv"],
            key="nhl_goal_tracking_upload",
        )
        if uploaded_snapshot is not None:
            try:
                saved = pd.read_csv(uploaded_snapshot)
                required = {"Date", "Game_ID", "Player_ID", "Player", "Team",
                            "Overall Rank", "Team Rank", "Bet Tier", "Goal Threat",
                            "Goal Match", "Final Anytime", "Goalie Match"}
                missing = required - set(saved.columns)
                if missing:
                    st.error("Snapshot is missing columns: " + ", ".join(sorted(missing)))
                else:
                    saved["Game_ID"] = pd.to_numeric(saved["Game_ID"], errors="coerce")
                    saved["Player_ID"] = pd.to_numeric(saved["Player_ID"], errors="coerce")
                    if saved["Game_ID"].isna().any() or saved["Player_ID"].isna().any():
                        st.error("Snapshot contains missing or invalid game/player IDs.")
                    else:
                        saved["Game_ID"] = saved["Game_ID"].astype(int)
                        saved["Player_ID"] = saved["Player_ID"].astype(int)
                        game_goals = {}
                        incomplete = []
                        for gid in saved["Game_ID"].unique():
                            result = get_game_data(int(gid))
                            state = str(result.get("gameState", "")).upper()
                            by_game = result.get("playerByGameStats") or {}
                            if state not in ("OFF", "FINAL") or not by_game:
                                incomplete.append(str(gid))
                                continue
                            goals_by_id = {}
                            for side in ("awayTeam", "homeTeam"):
                                for group in ("forwards", "defense"):
                                    for skater in by_game.get(side, {}).get(group, []):
                                        pid = skater.get("playerId")
                                        if pid is not None:
                                            goals_by_id[int(pid)] = int(skater.get("goals") or 0)
                            game_goals[int(gid)] = goals_by_id
                        if incomplete:
                            st.warning(
                                "Results not final for game IDs: " + ", ".join(incomplete)
                                + ". Only completed games are included below."
                            )
                        checked = saved[saved["Game_ID"].isin(game_goals)].copy()
                        if checked.empty:
                            st.info("No completed games with available boxscore stats yet.")
                        else:
                            checked["Actual Goals"] = checked.apply(
                                lambda row: game_goals[row["Game_ID"]].get(row["Player_ID"], 0),
                                axis=1,
                            )
                            checked["Scored"] = checked["Actual Goals"] > 0
                            st.metric("Tracked players", len(checked))
                            st.metric("Goal scorers in snapshot", int(checked["Scored"].sum()))
                            top_five = checked[checked["Team Rank"] <= 5]
                            elite = checked[checked["Bet Tier"].astype(str).str.contains("ELITE", na=False)]
                            strong = checked[checked["Bet Tier"].astype(str).str.contains("STRONG", na=False)]
                            st.write(
                                f"Top-5 hit rate: {top_five['Scored'].mean():.1%} "
                                f"({int(top_five['Scored'].sum())}/{len(top_five)})"
                                if len(top_five) else "Top-5 hit rate: N/A"
                            )
                            st.write(
                                f"Elite hit rate: {elite['Scored'].mean():.1%} "
                                f"({int(elite['Scored'].sum())}/{len(elite)})"
                                if len(elite) else "Elite hit rate: N/A"
                            )
                            st.write(
                                f"Strong hit rate: {strong['Scored'].mean():.1%} "
                                f"({int(strong['Scored'].sum())}/{len(strong)})"
                                if len(strong) else "Strong hit rate: N/A"
                            )
                            result_cols = [
                                "Date", "Player", "Team", "Team Rank", "Overall Rank",
                                "Goal Threat", "Goal Match", "Final Anytime", "Bet Tier",
                                "Goalie Match", "Actual Goals", "Scored"
                            ]
                            st.dataframe(
                                checked[result_cols].sort_values(
                                    ["Actual Goals", "Overall Rank"], ascending=[False, True]
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )
                            st.download_button(
                                "📥 Download Scored Results",
                                checked.to_csv(index=False).encode("utf-8"),
                                file_name="nhl_scored_results.csv",
                                mime="text/csv",
                            )
            except (ValueError, KeyError, pd.errors.ParserError) as exc:
                st.error(f"Could not process the snapshot: {exc}")
    else:
        st.warning("No NHL games found.")
       

  
