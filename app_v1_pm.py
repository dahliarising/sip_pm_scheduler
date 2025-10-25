# app_v1_pm.py

import streamlit as st
import pandas as pd
import plotly.express as px
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

# ✅ 페이지 설정 (맨 위에 와야 함)
st.set_page_config(
    page_title="SIP Scheduler v3 Responsive",
    layout="wide",
    page_icon="🧠",
)

# ✅ 제목 및 설명
st.title("SIP Scheduler v3")
st.caption("Suspension Intelligence Platform - Program Management Scheduler")

# --- Sidebar ---
st.sidebar.header("Configuration")
selected_view = st.sidebar.radio("Select View", ["Overview", "Timeline", "Raw Data"])

# --- Data Loading Section ---
@st.cache_data
def load_data():
    # 예시 데이터 (너 실제 DataFrame으로 교체 가능)
    data = {
        "Program": ["XM3", "SM6", "QM6", "Koleos", "Talisman"],
        "Phase": ["Design", "Validation", "Mass Production", "Design", "Prototype"],
        "Start": ["2025-01-10", "2025-02-15", "2025-03-01", "2025-01-20", "2025-03-10"],
        "End": ["2025-03-15", "2025-04-30", "2025-06-01", "2025-03-10", "2025-05-20"],
        "Owner": ["J. Kim", "S. Lee", "H. Park", "M. Choi", "Y. Han"],
    }
    df = pd.DataFrame(data)
    df["Start"] = pd.to_datetime(df["Start"])
    df["End"] = pd.to_datetime(df["End"])
    return df

df = load_data()

# --- Main Content ---
if selected_view == "Overview":
    st.subheader("📊 Project Schedule Overview")
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_pagination(paginationAutoPageSize=True)
    gb.configure_selection("single")
    gridOptions = gb.build()

    AgGrid(
        df,
        gridOptions=gridOptions,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        theme="balham",
        height=350,
    )

elif selected_view == "Timeline":
    st.subheader("📅 Gantt Chart")
    fig = px.timeline(df, x_start="Start", x_end="End", y="Program", color="Phase", text="Owner")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

elif selected_view == "Raw Data":
    st.subheader("📋 Raw Data")
    st.dataframe(df)

# --- Footer ---
st.markdown("---")
st.markdown(
    "<small>© 2025 Suspension Intelligence Platform | Built with ❤️ using Streamlit</small>",
    unsafe_allow_html=True,
)
