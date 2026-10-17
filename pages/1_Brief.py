"""Engineering Brief intake page."""

import streamlit as st

from core.brief_ui import render_brief_workflow

st.set_page_config(page_title="Engineering Brief · ForgeX", page_icon="📝", layout="wide")
render_brief_workflow()
