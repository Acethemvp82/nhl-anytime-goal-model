import streamlit as st
import pandas as pd
import requests
import base64
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
    sample = logs[:10]
    shots = [float(row["shots"]) for row in sample]
    l5 = shots[:5]
    # Goals are a separate research signal. Never treat missing goal
    # fields as zero or infer them from points.
    goal_l5 = [float(row["goals"]) for row in sample[:5]
               if row.get("goals") is not None]
    goal_l10 = [float(row["goals"]) for row in sample
                if row.get("goals") is not None]
    return {
        "L5 S/GP": round(sum(l5) / 5, 2) if len(l5) == 5 else None,
        "L10 S/GP": round(sum(shots) / 10, 2) if len(shots) == 10 else None,
        "Shot Trend": round(sum(l5) / 5 - sum(shots) / 10, 2) if len(shots) == 10 else None,
        "Shot Games": len(shots),
        "L5 Goals": int(sum(goal_l5)) if len(goal_l5) == 5 else None,
        "L10 Goals": int(sum(goal_l10)) if len(goal_l10) == 10 else None,
        "L5 G/GP": round(sum(goal_l5) / 5, 2) if len(goal_l5) == 5 else None,
        "L10 G/GP": round(sum(goal_l10) / 10, 2) if len(goal_l10) == 10 else None,
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

@st.cache_data(ttl=21600)
def get_chance_research(season_start):
    """Optional MoneyPuck season-level research, never a scoring input."""
    from io import BytesIO
    url = (
        "https://moneypuck.com/moneypuck/playerData/"
        f"seasonSummary/{season_start}/regular/skaters.csv"
    )
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        data = pd.read_csv(BytesIO(response.content), low_memory=False)
    except (requests.RequestException, ValueError, pd.errors.ParserError):
        return pd.DataFrame(), "Feed unavailable"
    id_col = next((c for c in ("playerId", "playerID", "player_id")
                   if c in data.columns), None)
    if id_col is None or "situation" not in data.columns:
        return pd.DataFrame(), "Missing player ID or situation field"
    # Power-play deployment comes from 5on4 rows, separate from
    # all-situations scoring totals. MoneyPuck icetime is in seconds.
    pp_rows = data[
        data["situation"].astype(str).str.lower().isin(["5on4", "powerplay"])
    ].copy()
    if not pp_rows.empty and "icetime" in pp_rows.columns:
        pp_rows["Player_ID"] = pd.to_numeric(
            pp_rows[id_col], errors="coerce"
        )
        pp_rows["MP PP TOI Min"] = (
            pd.to_numeric(pp_rows["icetime"], errors="coerce") / 60
        )
        pp_rows = pp_rows.dropna(subset=["Player_ID"])
        pp_rows["Player_ID"] = pp_rows["Player_ID"].astype(int)
        pp_rows = pp_rows.groupby("Player_ID", as_index=False)[
            "MP PP TOI Min"
        ].sum()
    else:
        pp_rows = pd.DataFrame(columns=["Player_ID", "MP PP TOI Min"])
    data = data[data["situation"].astype(str).str.lower() == "all"].copy()
    if data.empty:
        return pd.DataFrame(), "No all-situations rows"
    data["Player_ID"] = pd.to_numeric(data[id_col], errors="coerce")
    data = data.dropna(subset=["Player_ID"])
    data["Player_ID"] = data["Player_ID"].astype(int)
    # These are MoneyPuck's own field names; if absent, leave values blank.
    mapping = {
        "I_F_highDangerShots": "MP High Danger",
        "I_F_shotAttempts": "MP Shot Attempts",
        "I_F_xGoals": "MP xGoals",
        "icetime": "MP Ice Time",
        "games_played": "MP GP",
    }
    for source, dest in mapping.items():
        data[dest] = (
            pd.to_numeric(data[source], errors="coerce")
            if source in data.columns else float("nan")
        )
    cols = ["Player_ID"] + list(mapping.values())
    data = data[cols].drop_duplicates("Player_ID")
    data = data.merge(pp_rows, on="Player_ID", how="left", validate="one_to_one")
    return data, "Season totals (includes games after selected date if viewing history)"


@st.cache_data(ttl=21600)
def get_nhl_season_game_dates(season_start, selected_date):
    """Map five-digit regular-season IDs to NHL dates and teams."""
    from datetime import date, timedelta
    start = date(int(season_start), 10, 1)
    end = date.fromisoformat(selected_date)
    mapping = {}
    if end < start:
        return mapping
    cursor = start
    while cursor <= end:
        try:
            response = requests.get(
                f"https://api-web.nhle.com/v1/schedule/{cursor.isoformat()}",
                timeout=15,
            )
            response.raise_for_status()
            for day in response.json().get("gameWeek", []):
                game_date = str(day.get("date", ""))
                for game in day.get("games", []):
                    game_id = game.get("id")
                    if game_id and game_date:
                        # MoneyPuck uses the trailing five digits of NHL
                        # regular-season game IDs (e.g. 20001).
                        suffix = str(game_id)[-5:]
                        mapping[suffix] = {
                            "date": game_date,
                            "home": str(game.get("homeTeam", {}).get("abbrev", "")).upper(),
                            "away": str(game.get("awayTeam", {}).get("abbrev", "")).upper(),
                        }
        except (requests.RequestException, ValueError, TypeError):
            pass
        cursor += timedelta(days=7)
    return mapping


@st.cache_data(ttl=21600)
def get_defense_by_position(season_start, selected_date):
    """Pre-slate MoneyPuck shot xG allowed by opponent and shooter position.

    Only publishes results when every required shot and player field exists.
    """
    from io import BytesIO
    from zipfile import ZipFile, BadZipFile
    base = "https://peter-tanner.com/moneypuck/downloads"
    try:
        raw = requests.get(f"{base}/shots_{season_start}.zip", timeout=40)
        raw.raise_for_status()
        with ZipFile(BytesIO(raw.content)) as archive:
            member = next((n for n in archive.namelist()
                           if n.lower().endswith(".csv")), None)
            if member is None:
                return pd.DataFrame(), "Shot ZIP has no CSV"
            # Inspect the actual CSV header before selecting columns.
            # MoneyPuck exports can vary in capitalization and naming.
            header = pd.read_csv(archive.open(member), nrows=0).columns.tolist()
            aliases = {
                "shooterPlayerId": ["shooterPlayerId", "shooterPlayerID",
                                    "shooterPlayer_id"],
                "teamCode": ["teamCode", "team", "shootingTeamCode"],
                "homeTeamCode": ["homeTeamCode", "homeTeam"],
                "awayTeamCode": ["awayTeamCode", "awayTeam"],
                "gameDate": ["gameDate", "game_date", "game_date_utc", "date", "gameDateUTC"],
                "shotGoalProbability": ["shotGoalProbability", "xGoal"],
                "isPlayoffGame": ["isPlayoffGame"],
            }
            rename = {}
            for canonical, candidates in aliases.items():
                found = next((c for c in candidates if c in header), None)
                if found is not None:
                    rename[found] = canonical
            required = set(aliases) - {"isPlayoffGame"}
            game_id_field = next(
                (c for c in ("game_id", "gameId", "gameID") if c in header),
                None,
            )
            date_from_game_id = (
                "gameDate" not in rename.values() and game_id_field is not None
            )
            if date_from_game_id:
                rename[game_id_field] = "Source Game ID"
            missing = sorted(
                (required - set(rename.values())) -
                ({"gameDate"} if date_from_game_id else set())
            )
            if missing:
                return pd.DataFrame(), (
                    "Missing shot fields: " + ", ".join(missing) +
                    " | Available: " + ", ".join(header[:35])
                )
            shots = pd.read_csv(
                archive.open(member), low_memory=False,
                usecols=list(rename),
            ).rename(columns=rename)
            if date_from_game_id:
                # NHL IDs are NOT dates. Resolve each ID using official
                # NHL schedules; unmapped games are excluded, never guessed.
                id_to_date = get_nhl_season_game_dates(
                    season_start, selected_date
                )
                ids = pd.to_numeric(
                    shots["Source Game ID"], errors="coerce"
                ).astype("Int64").astype(str)
                matches = ids.map(id_to_date)
                shots["gameDate"] = matches.map(
                    lambda match: match.get("date") if isinstance(match, dict) else None
                )
                # Validate both teams against the official schedule. An ID
                # collision or mismatched season must not yield fake matchups.
                official_home = matches.map(
                    lambda match: match.get("home") if isinstance(match, dict) else None
                )
                official_away = matches.map(
                    lambda match: match.get("away") if isinstance(match, dict) else None
                )
                valid_teams = (
                    shots["homeTeamCode"].astype(str).str.upper().eq(official_home)
                    & shots["awayTeamCode"].astype(str).str.upper().eq(official_away)
                )
                shots = shots.loc[valid_teams].copy()
                if shots.empty:
                    return pd.DataFrame(), (
                        "No game IDs matched official NHL dates AND both teams. "
                        "Check MoneyPuck season/game ID format."
                    )
        players_response = requests.get(
            "https://moneypuck.com/moneypuck/playerData/"
            f"seasonSummary/{season_start}/regular/skaters.csv",
            timeout=25,
        )
        players_response.raise_for_status()
        players = pd.read_csv(BytesIO(players_response.content), low_memory=False)
    except (requests.RequestException, ValueError, BadZipFile,
            pd.errors.ParserError, OSError) as exc:
        return pd.DataFrame(), f"Source unavailable ({type(exc).__name__})"
    needed = {"shooterPlayerId", "teamCode", "homeTeamCode",
              "awayTeamCode", "gameDate", "shotGoalProbability"}
    if not needed.issubset(shots.columns):
        return pd.DataFrame(), "Shot data missing: " + ", ".join(
            sorted(needed - set(shots.columns))
        )
    if not {"playerId", "position", "situation"}.issubset(players.columns):
        return pd.DataFrame(), "Player position lookup missing required columns"
    if "isPlayoffGame" in shots.columns:
        shots = shots[
            pd.to_numeric(shots["isPlayoffGame"], errors="coerce") == 0
        ]
    # Explicit date cutoffs prevent future-game leakage.
    dates = pd.to_datetime(shots["gameDate"], errors="coerce")
    shots = shots.loc[dates.notna() & (
        dates < pd.Timestamp(selected_date)
    )].copy()
    if shots.empty:
        return pd.DataFrame(), "No pre-slate shots available"
    lookup = players[
        players["situation"].astype(str).str.lower() == "all"
    ][["playerId", "position"]].copy()
    lookup["shooterPlayerId"] = pd.to_numeric(
        lookup["playerId"], errors="coerce"
    )
    lookup = lookup.dropna(subset=["shooterPlayerId"]).drop_duplicates(
        "shooterPlayerId"
    )
    shots["shooterPlayerId"] = pd.to_numeric(
        shots["shooterPlayerId"], errors="coerce"
    )
    shots = shots.merge(
        lookup[["shooterPlayerId", "position"]],
        on="shooterPlayerId", how="left", validate="many_to_one"
    )
    shots["Position"] = shots["position"].astype(str).str.upper().replace({
        "L": "LW", "R": "RW",
    })
    shots = shots[shots["Position"].isin(["C", "LW", "RW"])].copy()
    # The shot's teamCode identifies the SHOOTING side; the other
    # team in the fixture is the defense that conceded the attempt.
    for c in ("teamCode", "homeTeamCode", "awayTeamCode"):
        shots[c] = shots[c].astype(str).str.upper().str.strip()
    home_shot = shots["teamCode"] == shots["homeTeamCode"]
    away_shot = shots["teamCode"] == shots["awayTeamCode"]
    shots = shots[home_shot | away_shot].copy()
    if shots.empty:
        return pd.DataFrame(), "No attributable shot opponents"
    shots["Opponent"] = shots["awayTeamCode"].where(
        shots["teamCode"] == shots["homeTeamCode"],
        shots["homeTeamCode"],
    )
    shots["Shot xG"] = pd.to_numeric(
        shots["shotGoalProbability"], errors="coerce"
    )
    shots = shots.dropna(subset=["Shot xG"])
    # Count actual games represented per defense, not player appearances.
    # A unique home/away/date fixture is sufficient for one regular season.
    shots["Fixture"] = (
        shots["gameDate"].astype(str) + "|" +
        shots["homeTeamCode"] + "|" + shots["awayTeamCode"]
    )
    games = shots.groupby("Opponent")["Fixture"].nunique()
    grouped = shots.groupby(["Opponent", "Position"]).agg(
        **{"Pos Shots Against": ("Shot xG", "size"),
           "Pos xGA": ("Shot xG", "sum")}
    ).reset_index()
    grouped["Def Games"] = grouped["Opponent"].map(games)
    grouped = grouped[grouped["Def Games"] >= 5].copy()
    grouped["Pos Shots/GP"] = (
        grouped["Pos Shots Against"] / grouped["Def Games"]
    ).round(2)
    grouped["Pos xGA/GP"] = (
        grouped["Pos xGA"] / grouped["Def Games"]
    ).round(3)
    return grouped, "Pre-slate MoneyPuck shots; minimum 5 defensive games"


@st.cache_data(ttl=1800)
def get_goalie_stats(player_id, season_id):
    """NHL goalie summary for one player/season, or an empty result."""
    url = "https://api.nhle.com/stats/rest/en/goalie/summary"
    params = {
        "cayenneExp": f"seasonId={season_id} and playerId={player_id} and gameTypeId=2",
        "limit": 100,
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return {"data": []}


def goalie_season_numbers(player_id, selected_date):
    """Use current-season stats, then previous season if unavailable."""
    season_start = int(selected_date[:4]) - (int(selected_date[5:7]) < 7)
    for start in (season_start, season_start - 1):
        season = int(f"{start}{start + 1}")
        rows = get_goalie_stats(player_id, season).get("data", [])
        if not rows:
            continue
        row = rows[0]
        games = int(row.get("gamesPlayed") or 0)
        save_pct = row.get("savePct")
        if games <= 0 or save_pct is None:
            continue
        save_pct = float(save_pct)
        # NHL stats may encode SV% as 0.900 or 90.0.
        if save_pct > 1:
            save_pct /= 100
        if not 0.5 <= save_pct <= 1:
            continue
        return {
            "SV%": save_pct,
            "GAA": float(row.get("goalsAgainstAverage") or 0),
            "GP": games,
            "Source": "Current season SV%" if start == season_start else "Prior season SV%",
        }
    return None

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
    # GameCenter starters take priority. Before lineups appear, select the
    # most-used roster goalie as an explicitly UNCONFIRMED proxy.
    goalie_map = {}
    for team in slate_teams:
        goalie_map[team] = {
            "Goalie": "Unknown", "Player_ID": None, "SV%": 0,
            "GAA": 0, "Status": "Unknown", "Source": "Neutral fallback (no SV%)"
        }
        game_data = game_data_map.get(team, {})
        by_game = game_data.get("playerByGameStats") or {}
        side = "awayTeam" if team == game_data.get("awayTeam", {}).get("abbrev") else "homeTeam"
        game_goalies = by_game.get(side, {}).get("goalies", [])
        starter = next((g for g in game_goalies if g.get("starter") is True), None)
        if starter:
            candidates = [starter]
            status = "GameCenter starter"
        elif game_goalies:
            candidates = game_goalies
            status = "GameCenter listed (unconfirmed)"
        else:
            roster = get_team_roster(team)
            candidates = roster.get("goalies", [])
            status = "Roster proxy (unconfirmed)"

        evaluated = []
        for goalie in candidates:
            goalie_id = goalie.get("playerId") or goalie.get("id")
            if not goalie_id:
                continue
            stats = goalie_season_numbers(goalie_id, selected_date)
            if stats:
                evaluated.append((stats["GP"], goalie, goalie_id, stats))
        if not evaluated:
            continue
        # Choose the goalie with the largest relevant-season sample, never
        # call a roster proxy a confirmed starter.
        _, goalie, goalie_id, stats = max(evaluated, key=lambda item: item[0])
        name = goalie.get("name", {})
        name = name.get("default", "") if isinstance(name, dict) else str(name or "")
        if not name:
            first, last = goalie.get("firstName", {}), goalie.get("lastName", {})
            first = first.get("default", "") if isinstance(first, dict) else str(first or "")
            last = last.get("default", "") if isinstance(last, dict) else str(last or "")
            name = f"{first} {last}".strip()
        goalie_map[team] = {
            "Goalie": name or "Unknown", "Player_ID": goalie_id,
            "SV%": stats["SV%"], "GAA": stats["GAA"],
            "Status": status, "Source": stats["Source"],
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
        # When GameCenter has no dressed lineup, show the roster but flag it
        # as unconfirmed; never silently discard potential starters.
        if not dressed_ids:
            st.caption(
                f"{team}: dressed lineup not yet published; roster candidates "
                "are shown as unconfirmed."
            )
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
    
                # Research-only power-play usage indicators from the same NHL
                # player landing response. Missing fields stay missing.
                pp_goals = season_stats.get("powerPlayGoals")
                pp_points = season_stats.get("powerPlayPoints")
                pp_goals_per_game = (
                    round(float(pp_goals) / games_played, 3)
                    if pp_goals is not None and games_played else None
                )
                pp_points_per_game = (
                    round(float(pp_points) / games_played, 3)
                    if pp_points is not None and games_played else None
                )
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
                    raw_goalie_match = sv_weakness * 100
                    # Shrink uncertain goalie estimates toward neutral (50).
                    # The goalie is a proxy until GameCenter identifies a starter.
                    goalie_status = opp_goalie.get("Status", "Unknown")
                    goalie_source = opp_goalie.get("Source", "")
                    if goalie_status != "GameCenter starter":
                        goalie_reliability = 0.35
                    elif goalie_source == "Prior season SV%":
                        goalie_reliability = 0.60
                    else:
                        goalie_reliability = 1.0
                    goalie_match = round(
                        50 + (raw_goalie_match - 50) * goalie_reliability, 1
                    )
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
                    "Goalie Data": opp_goalie.get("Source", "Neutral fallback (no SV%)"),
                    "Lineup Status": "Dressed (GameCenter)" if dressed_ids else "Roster Candidate",
                    "Position": position,
                    "GP": games_played,
                    "G/GP": goals_per_game,
                    "Shots": shots,
                    "S/GP": shots_per_game,
                    "PP Goals": pp_goals,
                    "PP Points": pp_points,
                    "PP G/GP": pp_goals_per_game,
                    "PP P/GP": pp_points_per_game,
                    "L5 S/GP": recent_shots.get("L5 S/GP"),
                    "L10 S/GP": recent_shots.get("L10 S/GP"),
                    "Shot Trend": recent_shots.get("Shot Trend"),
                    "Shot Games": recent_shots.get("Shot Games", 0),
                    "L5 Goals": recent_shots.get("L5 Goals"),
                    "L10 Goals": recent_shots.get("L10 Goals"),
                    "L5 G/GP": recent_shots.get("L5 G/GP"),
                    "L10 G/GP": recent_shots.get("L10 G/GP"),
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
        def lineup_coverage(row):
            if row["Skaters"] == 0:
                return "MISSING"
            if row["Lineup Status"] == "Roster Candidate":
                return "UNCONFIRMED ROSTER"
            if row["Skaters"] == 18:
                return "18 DRESSED"
            return "VERIFY GAMECENTER COUNT"

        coverage["Coverage"] = coverage.apply(lineup_coverage, axis=1)
        missing = coverage.loc[coverage["Skaters"] == 0, "Team"].tolist()
        if missing:
            st.error("Scheduled teams missing from rankings: " + ", ".join(missing))
        with st.expander("🔎 Slate Coverage / Lineup Audit", expanded=bool(missing)):
            st.caption("Roster Candidate means the full roster is shown until GameCenter provides dressed skaters. Dressed (GameCenter) means the game feed identifies the skaters; it is not an independently verified lineup announcement.")
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
            "Goal Threat", "Goal Match", "Final Anytime", "Bet Tier",
            "Goalie Match", "L5 S/GP", "Shot Trend", "Lineup Status",
        ]
        advanced_columns = [
            "Overall Rank", "Team Rank", "Player", "Team", "Opponent",
            "Game Time", "Goals", "GP", "G/GP", "Shots", "S/GP", "L5 S/GP", "L10 S/GP", "Shot Trend", "Shot Games",
            "Opp GA/GP", "Position", "Player_ID", "Goalie Status", "Goalie Data",
            "L5 Goals", "L10 Goals", "L5 G/GP", "L10 G/GP",
            "PP Goals", "PP Points", "PP G/GP", "PP P/GP",
            "Goal Threat", "Goal Match", "Goalie Match", "Final Anytime",
            "Bet Tier", "Opp Goalie", "Lineup Status",
        ]
        season_start_research = int(selected_date[:4]) - (
            int(selected_date[5:7]) < 7
        )
        chance_data, chance_status = get_chance_research(season_start_research)
        research_df = skaters_df.copy()
        if not chance_data.empty:
            research_df = research_df.merge(
                chance_data, on="Player_ID", how="left", validate="many_to_one"
            )
        for col in ("MP High Danger", "MP Shot Attempts", "MP xGoals",
                    "MP Ice Time", "MP GP", "MP PP TOI Min"):
            if col not in research_df:
                research_df[col] = float("nan")
        # Use rates only where the feed supplies an actual game count.
        mp_gp = pd.to_numeric(research_df["MP GP"], errors="coerce")
        research_df["MP HD/GP"] = (
            research_df["MP High Danger"] / mp_gp.where(mp_gp > 0)
        ).round(2)
        research_df["MP Attempts/GP"] = (
            research_df["MP Shot Attempts"] / mp_gp.where(mp_gp > 0)
        ).round(2)
        research_df["MP xG/GP"] = (
            research_df["MP xGoals"] / mp_gp.where(mp_gp > 0)
        ).round(3)
        research_df["MP PP TOI/GP"] = (
            research_df["MP PP TOI Min"] / mp_gp.where(mp_gp > 0)
        ).round(2)
        # Experimental comparison uses only independently observed rates.
        # It is intentionally not a calibrated goal probability.
        signals = ["MP HD/GP", "MP xG/GP", "MP Attempts/GP",
                   "MP PP TOI/GP"]
        valid = mp_gp.ge(5)
        for signal in signals:
            valid &= pd.to_numeric(
                research_df[signal], errors="coerce"
            ).notna()
        research_df["Research Eligible"] = valid
        research_df["Opportunity Score"] = float("nan")
        research_df["Experimental Score"] = float("nan")
        if valid.sum() >= 10:
            # Percentile ranks limit extreme early-season outliers.
            # Fixed equal weights are provisional and require backtesting.
            component = pd.concat([
                research_df.loc[valid, signal].rank(pct=True) * 100
                for signal in signals
            ], axis=1)
            opportunity = component.mean(axis=1)
            research_df.loc[valid, "Opportunity Score"] = opportunity.round(1)
            research_df.loc[valid, "Experimental Score"] = (
                0.80 * research_df.loc[valid, "Final Anytime"] +
                0.20 * opportunity
            ).round(1)
        research_df["Experimental Rank"] = pd.NA
        research_df["Experimental Team Rank"] = pd.NA
        eligible_idx = research_df.loc[
            research_df["Experimental Score"].notna()
        ].sort_values(
            ["Experimental Score", "Final Anytime"],
            ascending=False
        ).index
        if len(eligible_idx):
            research_df.loc[eligible_idx, "Experimental Rank"] = (
                range(1, len(eligible_idx) + 1)
            )
            research_df.loc[eligible_idx, "Experimental Team Rank"] = (
                research_df.loc[eligible_idx].groupby("Team").cumcount().to_numpy() + 1
            )
        with st.expander("🧪 Experimental Rankings — comparison only"):
            st.caption(
                "Experimental Score = 80% existing Final Anytime + 20% "
                "equal-weight percentile average of high-danger attempts, "
                "xGoals, shot attempts and 5-on-4 TOI per game. "
                "Minimum five MoneyPuck games and all four signals required. "
                "Players without coverage are unranked, not assigned zero. "
                "This is NOT a calibrated probability, proven betting edge, "
                "or a replacement for existing rankings."
            )
            st.caption(
                f"Research coverage: {int(valid.sum())}/{len(research_df)} "
                "skaters eligible. Seasonal MoneyPuck data can contain "
                "future information for historical selected dates; "
                "do not use this comparison as a historical backtest."
            )
            if not len(eligible_idx):
                st.warning("Insufficient research data for experimental rankings.")
            else:
                st.dataframe(
                    research_df.loc[eligible_idx, [
                        "Experimental Rank", "Experimental Team Rank",
                        "Player", "Team", "Opponent", "Team Rank",
                        "Final Anytime", "Opportunity Score",
                        "Experimental Score", "MP HD/GP", "MP xG/GP",
                        "MP PP TOI/GP",
                    ]].head(100),
                    hide_index=True, use_container_width=True,
                )
                st.caption(
                    "Compare Experimental Team Rank with original Team Rank. "
                    "Actual goal outcomes must be tested using strictly "
                    "pregame snapshots before any model weight changes."
                )

        with st.expander("🛡️ Defense vs Position — research only"):
            st.caption(
                "Shot-level MoneyPuck xG and unblocked attempts conceded "
                "to opposing C, LW and RW. Pre-slate date cutoff; "
                "at least five defensive games required. This is NOT "
                "a goalscorer probability or a calibrated positional rank."
            )
            if st.button("Load position defense research", key="load_pos_def"):
                with st.spinner("Loading shot-level position matchups..."):
                    position_data, position_status = get_defense_by_position(
                        season_start_research, selected_date
                    )
                st.caption("Feed: " + position_status)
                if position_data.empty:
                    st.warning(
                        "No verified positional defense rows available. "
                        "Original rankings remain unaffected."
                    )
                else:
                    positions = research_df["Position"].astype(str).str.upper().replace({
                        "L": "LW", "R": "RW",
                    })
                    matchups = research_df.assign(Position=positions).merge(
                        position_data, on=["Opponent", "Position"],
                        how="left", validate="many_to_one"
                    )
                    st.dataframe(
                        matchups[[
                            "Player", "Team", "Opponent", "Position",
                            "Team Rank", "Final Anytime", "Def Games",
                            "Pos Shots/GP", "Pos xGA/GP",
                        ]].style.format({
                            "Team Rank": "{:.0f}",
                            "Final Anytime": "{:.1f}",
                            "Def Games": "{:.0f}",
                            "Pos Shots/GP": "{:.2f}",
                            "Pos xGA/GP": "{:.3f}",
                        }, na_rep="—"),
                        use_container_width=True, hide_index=True,
                    )
                    # A separate on-demand positional experiment; the
                    # existing Experimental Score and main board are unchanged.
                    eligible_pos = (
                        matchups["Experimental Score"].notna()
                        & matchups["Pos xGA/GP"].notna()
                        & matchups["Pos Shots/GP"].notna()
                        & matchups["Def Games"].ge(5)
                    )
                    if eligible_pos.sum() >= 10:
                        experiment = matchups.loc[eligible_pos].copy()
                        # Positional rates are group-level context, not
                        # individual goal probabilities. Rank only complete
                        # observations within the selected slate.
                        experiment["Position Matchup Score"] = (
                            0.70 * experiment["Pos xGA/GP"].rank(pct=True) * 100
                            + 0.30 * experiment["Pos Shots/GP"].rank(pct=True) * 100
                        ).round(1)
                        experiment["Position Adjusted Score"] = (
                            0.85 * experiment["Experimental Score"]
                            + 0.15 * experiment["Position Matchup Score"]
                        ).round(1)
                        experiment = experiment.sort_values(
                            ["Position Adjusted Score", "Experimental Score"],
                            ascending=False,
                        ).copy()
                        experiment["Position Overall Rank"] = range(
                            1, len(experiment) + 1
                        )
                        experiment["Position Team Rank"] = (
                            experiment.groupby("Team").cumcount() + 1
                        )
                        st.markdown("**🧪 Position-adjusted experimental rankings**")
                        st.caption(
                            "Research only: 85% existing Experimental Score + "
                            "15% positional matchup percentile (70% opponent "
                            "position xGA/GP, 30% opponent position shots/GP). "
                            "Only players with complete data are ranked. "
                            "This is NOT validated, a goal probability, or "
                            "a replacement for the original Team Rank."
                        )
                        st.dataframe(
                            experiment[[
                                "Position Overall Rank", "Position Team Rank",
                                "Player", "Team", "Opponent", "Team Rank",
                                "Experimental Score", "Position Matchup Score",
                                "Position Adjusted Score", "Pos xGA/GP",
                            ]].head(100).style.format({
                                "Team Rank": "{:.0f}",
                                "Experimental Score": "{:.1f}",
                                "Position Matchup Score": "{:.1f}",
                                "Position Adjusted Score": "{:.1f}",
                                "Pos xGA/GP": "{:.3f}",
                            }, na_rep="—"),
                            use_container_width=True, hide_index=True,
                        )
                        st.caption(
                            "For a fair performance comparison, collect "
                            "pregame snapshots and actual goal outcomes. "
                            "Historical season-level opportunity data may "
                            "contain future games and must not be backtested "
                            "as though it were pregame."
                        )
                    else:
                        st.info(
                            "Insufficient complete coverage for position-adjusted "
                            "experimental rankings (minimum 10 players)."
                        )
                    st.caption(
                        "Source: MoneyPuck shot ZIP and skater position lookup. "
                        "Unmatched positions remain blank. Shot counts exclude "
                        "blocked attempts. Research is not yet part of "
                        "Experimental Score or Final Anytime."
                    )

        with st.expander("🧪 Scoring Opportunity Research — no ranking changes"):
            st.caption(
                "Recent goals use the same pre-slate NHL game logs as recent shots. "
                "Power-play goals and points come from NHL player season statistics "
                "where available. These are production measures, NOT "
                "power-play ice time or high-danger chance counts. Missing data "
                "remains blank. No research metric affects Goal Threat, Goal "
                "Match, Final Anytime, Bet Tier, or Team Rank."
            )
            research_cols = [
                "Overall Rank", "Team Rank", "Player", "Team", "GP",
                "S/GP", "L5 S/GP", "L5 Goals", "L10 Goals",
                "L5 G/GP", "L10 G/GP", "PP Goals", "PP Points",
                "PP G/GP", "PP P/GP", "Final Anytime",
            ]
            st.dataframe(
                skaters_df[research_cols].style.format({
                    "S/GP": "{:.2f}", "L5 S/GP": "{:.2f}",
                    "L5 Goals": "{:.0f}", "L10 Goals": "{:.0f}",
                    "PP Goals": "{:.0f}", "PP Points": "{:.0f}",
                    "L5 G/GP": "{:.2f}", "L10 G/GP": "{:.2f}",
                    "PP G/GP": "{:.3f}", "PP P/GP": "{:.3f}",
                    "Final Anytime": "{:.1f}",
                }, na_rep="—"),
                use_container_width=True, hide_index=True,
            )
            st.caption(
                "MoneyPuck research feed: " + chance_status +
                ". Source: moneypuck.com/data.htm (non-commercial research; "
                "credit MoneyPuck). These season-level figures may include "
                "games AFTER a historical selected date, so they are never "
                "used in rankings or pregame backtests."
            )
            st.caption(
                "High-danger attempts, shot attempts and expected goals are "
                "distinct statistics; they are not guaranteed to use the same "
                "definitions as Prop Finder. Empty values mean unavailable data."
            )
            st.dataframe(
                research_df[[
                    "Overall Rank", "Team Rank", "Player", "Team",
                    "MP GP", "MP HD/GP", "MP Attempts/GP", "MP xG/GP",
                    "MP PP TOI/GP", "Final Anytime",
                ]].style.format({
                    "MP GP": "{:.0f}",
                    "Final Anytime": "{:.1f}",
                    "MP HD/GP": "{:.2f}",
                    "MP Attempts/GP": "{:.2f}",
                    "MP xG/GP": "{:.3f}",
                    "MP PP TOI/GP": "{:.2f}",
                }, na_rep="—"),
                hide_index=True, use_container_width=True,
            )
            st.caption(
                "Power-play TOI/GP is season 5-on-4 minutes divided by "
                "season games played, not a recent-game or projected figure. "
                "Opponent defense by position is available separately "
                "on demand in Defense vs Position research. "
                "No changes to the model formula."
            )

        st.subheader("🎯 Top 5 Goal Scorer Shortlist")
        st.caption(
            "Top five players by the existing Final Anytime ranking. "
            "These are model candidates, not guaranteed scorers or calibrated probabilities. "
            "Sample Check flags early-season volatility; it does not change the score."
        )
        shortlist = skaters_df.head(5).copy()
        shortlist["Lineup Check"] = shortlist["Lineup Status"].apply(
            lambda status: "⚠️ Roster candidate"
            if status == "Roster Candidate" else "GameCenter dressed"
        )
        shortlist["Goalie Check"] = shortlist["Goalie Data"].apply(
            lambda source: "⚠️ Neutral fallback"
            if source.startswith("Neutral fallback") else source
        )
        # Early-season rates can be unstable; flag limited samples rather
        # than silently presenting high scores as well-established signals.
        shortlist["Sample Check"] = shortlist["GP"].apply(
            lambda gp: "⚠️ <10 GP" if pd.notna(gp) and gp < 10
            else ("Limited: 10–19 GP" if pd.notna(gp) and gp < 20
                  else "20+ GP")
        )
        st.dataframe(
            shortlist[[
                "Overall Rank", "Player", "Team", "Goal Threat",
                "Goal Match", "Final Anytime", "Bet Tier",
                "Lineup Check", "Goalie Check", "Sample Check",
            ]].style.format({
                "Goal Threat": "{:.1f}",
                "Goal Match": "{:.1f}",
                "Final Anytime": "{:.1f}",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.subheader("🏒 Today's Goal Board")
        st.caption(
            "Rankings and scoring signals first; shot volume and lineup checks next. "
            "Goalie details and L10 shot averages are under Advanced Stats."
        )
        # Recent-shot feed health is informational and never changes rankings.
        shot_available = int(skaters_df["Shot Trend"].notna().sum())
        shot_total = len(skaters_df)
        st.caption(
            f"Full 10-game shot samples (including prior season if needed): {shot_available}/{shot_total} skaters. "
            "Missing values are shown as — and are not treated as zero."
        )
        if shot_available < shot_total:
            st.caption(
                "Missing shot values mean insufficient accessible game history "
                "or unavailable player logs; they are not zero-shot games."
            )
        if shot_available == 0:
            st.warning(
                "Recent shot logs are unavailable for this slate. "
                "Existing model rankings are unaffected."
            )

        # Normalize missing shot values for clean numeric formatting.
        for shot_col in ("L5 S/GP", "L10 S/GP", "Shot Trend"):
            skaters_df[shot_col] = pd.to_numeric(
                skaters_df[shot_col], errors="coerce"
            )
        st.dataframe(
            skaters_df[main_columns].style
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
            st.caption("Includes L10 shots/game, opponent goalie, goalie-data source, and season statistics.")
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
        # Persistent pregame snapshots live in GitHub, not Streamlit's ephemeral disk.
        # Set GITHUB_TOKEN in Streamlit Secrets with repository Contents read/write
        # access. Once a snapshot exists it is never overwritten by reruns.
        snapshot_path = f"pregame_snapshots/{selected_date}.csv"
        snapshot_api = (
            "https://api.github.com/repos/Acethemvp82/"
            f"nhl-anytime-goal-model/contents/{snapshot_path}"
        )
        github_token = st.secrets.get("GITHUB_TOKEN", "")
        snapshot_headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        } if github_token else {}
        stored_snapshot = None
        snapshot_status = "Manual CSV only (GITHUB_TOKEN not configured)"
        if github_token:
            try:
                existing = requests.get(snapshot_api, headers=snapshot_headers, timeout=12)
                if existing.status_code == 200:
                    stored_snapshot = pd.read_csv(
                        __import__("io").BytesIO(
                            base64.b64decode(existing.json()["content"])
                        )
                    )
                    snapshot_status = "Saved pregame snapshot loaded"
                elif existing.status_code == 404:
                    # Do not save if any scheduled game has already started.
                    # Schedule statuses are more reliable than device time zones.
                    pregame_states = {"FUT", "PRE"}
                    all_pregame = bool(len(daily_schedule)) and all(
                        str(state).upper() in pregame_states
                        for state in daily_schedule["Status"]
                    )
                    if all_pregame:
                        payload = {
                            "message": f"Freeze NHL pregame rankings for {selected_date}",
                            "content": base64.b64encode(
                                snapshot_df.to_csv(index=False).encode("utf-8")
                            ).decode("ascii"),
                        }
                        created = requests.put(
                            snapshot_api, headers=snapshot_headers,
                            json=payload, timeout=15,
                        )
                        if created.status_code == 201:
                            stored_snapshot = snapshot_df.copy()
                            snapshot_status = "Pregame snapshot saved automatically"
                        else:
                            snapshot_status = (
                                f"Automatic save unavailable (HTTP {created.status_code})"
                            )
                    else:
                        snapshot_status = "No frozen snapshot: slate already started"
                else:
                    snapshot_status = (
                        f"Snapshot lookup unavailable (HTTP {existing.status_code})"
                    )
            except (requests.RequestException, ValueError, KeyError) as exc:
                snapshot_status = f"Snapshot service unavailable: {type(exc).__name__}"
        st.caption(f"Automatic tracking: {snapshot_status}. Snapshots are never overwritten.")
        st.caption(
            "Automatic saving requires GITHUB_TOKEN in Streamlit Secrets and "
            "the app to run before the first game starts. Manual CSV remains available."
        )
        if stored_snapshot is not None:
            st.subheader("🎯 Frozen Pregame Performance")
            try:
                completed = {}
                for gid in pd.to_numeric(
                    stored_snapshot["Game_ID"], errors="coerce"
                ).dropna().astype(int).unique():
                    box = get_game_data(int(gid))
                    if str(box.get("gameState", "")).upper() not in ("OFF", "FINAL"):
                        continue
                    by_game = box.get("playerByGameStats") or {}
                    if not by_game:
                        continue
                    goals = {}
                    for side in ("awayTeam", "homeTeam"):
                        for group in ("forwards", "defense"):
                            for p in by_game.get(side, {}).get(group, []):
                                if p.get("playerId") is not None:
                                    goals[int(p["playerId"])] = int(p.get("goals") or 0)
                    completed[int(gid)] = goals
                frozen = stored_snapshot.copy()
                frozen["Game_ID"] = pd.to_numeric(frozen["Game_ID"], errors="coerce")
                frozen["Player_ID"] = pd.to_numeric(frozen["Player_ID"], errors="coerce")
                frozen = frozen.dropna(subset=["Game_ID", "Player_ID"])
                frozen = frozen[frozen["Game_ID"].isin(completed)].copy()
                if frozen.empty:
                    st.info("Frozen rankings saved; waiting for completed games.")
                else:
                    frozen["Actual Goals"] = frozen.apply(
                        lambda row: completed[int(row["Game_ID"])].get(
                            int(row["Player_ID"]), 0
                        ), axis=1
                    )
                    frozen["Scored"] = frozen["Actual Goals"] > 0
                    for label, mask in (
                        ("Overall Top 5", frozen["Overall Rank"] <= 5),
                        ("Top 3 per team", frozen["Team Rank"] <= 3),
                    ):
                        group = frozen[mask]
                        if len(group):
                            st.write(
                                f"{label}: {int(group['Scored'].sum())}/"
                                f"{len(group)} scored ({group['Scored'].mean():.1%})"
                            )
                    st.dataframe(
                        frozen[[
                            "Player", "Team", "Overall Rank", "Team Rank",
                            "Goal Threat", "Goal Match", "Final Anytime",
                            "Bet Tier", "Actual Goals", "Scored"
                        ]].sort_values("Overall Rank"),
                        use_container_width=True, hide_index=True,
                    )
            except (KeyError, ValueError, TypeError) as exc:
                st.warning(f"Frozen snapshot could not be scored: {exc}")

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
       

  
