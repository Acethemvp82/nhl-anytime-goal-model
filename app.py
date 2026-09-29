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
        st.subheader("🏒 NHL Schedule")
        st.dataframe(schedule_df, use_container_width=True, hide_index=True)
    else:
        st.warning("No NHL games found.")

except Exception as e:
    st.error(f"Could not load NHL schedule: {e}")
