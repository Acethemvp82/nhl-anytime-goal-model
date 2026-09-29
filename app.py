import streamlit as st
import pandas as pd
import requests
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

        skaters = []

        for team in slate_teams:
            roster = get_team_roster(team)

            for position_group in ["forwards", "defensemen"]:
                for player in roster.get(position_group, []):
                    first_name = player.get("firstName", {}).get("default", "")
                    last_name = player.get("lastName", {}).get("default", "")
                    position = player.get("positionCode", "")

                    skaters.append({
                        "Player": f"{first_name} {last_name}".strip(),
                        "Team": team,
                        "Position": position
                    })

        if skaters:
            skaters_df = pd.DataFrame(skaters)

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
