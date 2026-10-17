"""ForgeX Streamlit home page."""

import streamlit as st

st.set_page_config(page_title="ForgeX", page_icon="🛠️", layout="wide")
st.title("ForgeX")
st.write(
    "Turn a plain-language mechanical product idea into a structured Engineering Brief "
    "that you can review and confirm."
)

st.subheader("Engineering Brief intake")
st.write(
    "Describe a servo-driven gripper or simple structural bracket. ForgeX extracts the "
    "details you provide, asks for missing information, and keeps the confirmed brief "
    "in your current session."
)
st.caption(
    "Offline demo mode is available without an API key. ForgeX does not provide FEA "
    "or safety certification."
)
st.page_link("pages/1_Brief.py", label="Start Engineering Brief", icon="📝")
