import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import streamlit as st

# Load the dataset
df = pd.read_csv("spartanburg_tax_sale_properties.csv")

# Streamlit UI
st.title("📍 Spartanburg Tax Sale Properties Map")
st.markdown("Explore tax sale properties by bid amount and owner name.")

# Filters
min_bid, max_bid = st.slider("Select Bid Amount Range", 0, int(df["Bid Amount"].max()), (0, 10000))
filtered_df = df[(df["Bid Amount"] >= min_bid) & (df["Bid Amount"] <= max_bid)]

owner_filter = st.text_input("Search by Owner Name", "")
if owner_filter:
    filtered_df = filtered_df[filtered_df["Owner Name"].str.contains(owner_filter, case=False)]

# Color function
def get_color(amount):
    if amount < 1000:
        return "green"
    elif amount < 5000:
        return "orange"
    else:
        return "red"

# Create map
m = folium.Map(location=[34.95, -81.93], zoom_start=10)
marker_cluster = MarkerCluster().add_to(m)

for _, row in filtered_df.iterrows():
    popup = folium.Popup(
        f"<strong>Owner:</strong> {row['Owner Name']}<br>"
        f"<strong>Address:</strong> {row['Address']}<br>"
        f"<strong>Bid Amount:</strong> ${row['Bid Amount']:,.2f}",
        max_width=300
    )
    folium.CircleMarker(
        location=(row["Latitude"], row["Longitude"]),
        radius=6,
        color=get_color(row["Bid Amount"]),
        fill=True,
        fill_opacity=0.8,
        popup=popup
    ).add_to(marker_cluster)

# Display map
st_data = st_folium(m, width=800, height=600)
