"""Device-Inventory page (placeholder).

Becomes the Phase-1 sanity dashboard over insights.devices_unified once the ETL
extractors and device matcher have populated it.
"""

import streamlit as st

st.set_page_config(page_title="Device Inventory · krai-insights", page_icon="🖨️", layout="wide")
st.title("🖨️ Device Inventory")
st.info(
    "Placeholder. This page will list `insights.devices_unified` (manufacturer, "
    "model, customer, match type & confidence) after the extractors + device "
    "matcher land. Target: >10,000 devices, >90% match rate."
)
