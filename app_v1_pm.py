import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

DB_PATH = "sip_schedule.db"

# --- DB helper ---
def get_conn():
    return sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)

def run(q, p=()):
    with get_conn() as conn:
        conn.execute(q, p)
        conn.commit()

def qdf(q, p=()):
    with get_conn() as conn:
        return pd.read_sql_query(q, conn, params=p)

# --- Schema ---
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS car_model(
  car_id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_name TEXT UNIQUE,
  platform TEXT,
  launch_date DATE
);
CREATE TABLE IF NOT EXISTS wbs_item(
  wbs_id INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id INTEGER,
  car_id INTEGER,
  axle TEXT,
  name TEXT,
  type TEXT CHECK(type IN ('summary', 'task', 'milestone')),
  sort_key INTEGER
);
CREATE TABLE IF NOT EXISTS activity(
  act_id INTEGER PRIMARY KEY AUTOINCREMENT,
  wbs_id INTEGER,
  activity_name TEXT,
  category TEXT,
  start_date DATE,
  end_date DATE,
  leadtime_week INTEGER,
  progress INTEGER DEFAULT 0,
  status TEXT DEFAULT 'Planned',
  seq INTEGER
);
"""

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
    if qdf("SELECT * FROM car_model").empty:
        run("INSERT INTO car_model (car_name, platform, launch_date) VALUES (?,?,?)",
            ("SM6", "CMF-D", "2026-03-01"))
    car_id = qdf("SELECT car_id FROM car_model LIMIT 1").iloc[0, 0]
    if qdf("SELECT * FROM wbs_item").empty:
        data = [
            (None, car_id, "Front", "Front Axle", "summary", 1),
            (1, car_id, "Front", "Lower Arm", "summary", 1),
            (2, car_id, "Front", "설계 (Design)", "summary", 1),
            (3, car_id, "Front", "3D 모델링", "task", 1),
            (3, car_id, "Front", "도면 작성", "task", 2),
            (2, car_id, "Front", "해석 완료 게이트", "milestone", 3),
        ]
        for p in data:
            run("INSERT INTO wbs_item (parent_id, car_id, axle, name, type, sort_key) VALUES (?,?,?,?,?,?)", p)
    if qdf("SELECT * FROM activity").empty:
        wbs_tasks = qdf("SELECT * FROM wbs_item WHERE type='task'")
        base_date = datetime.today().date()
        for i, row in enumerate(wbs_tasks.itertuples(), 1):
            s = base_date + timedelta(weeks=i)
            e = s + timedelta(weeks=1) - timedelta(days=1)
            run("""INSERT INTO activity 
                   (wbs_id, activity_name, category, start_date, end_date, leadtime_week, seq)
                   VALUES (?,?,?,?,?,?,?)""",
                (row.wbs_id, row.name, "Design", s.isoformat(), e.isoformat(), 1, i))

def recalc_activity_dates(wbs_id: int):
    df = qdf("SELECT act_id, start_date, leadtime_week FROM activity WHERE wbs_id=?", (wbs_id,))
    updates = []
    for r in df.itertuples():
        s = pd.to_datetime(r.start_date).date()
        e = s + timedelta(weeks=int(r.leadtime_week)) - timedelta(days=1)
        updates.append((e.isoformat(), r.act_id))
    with get_conn() as conn:
        conn.executemany("UPDATE activity SET end_date=? WHERE act_id=?", updates)
        conn.commit()

# --- JS로 뷰포트 감지 ---
st.markdown(
    """
    <script>
    const sendViewport = () => {
      const width = window.innerWidth;
      const streamlitDoc = window.parent.document;
      Streamlit.setComponentValue(width);
    };
    window.addEventListener('load', sendViewport);
    window.addEventListener('resize', sendViewport);
    </script>
    """,
    unsafe_allow_html=True
)

if "viewport_width" not in st.session_state:
    st.session_state["viewport_width"] = 1200  # default desktop

viewport_width = st.session_state["viewport_width"]
is_mobile = viewport_width < 800

# --- UI Layout ---
st.set_page_config(page_title="SIP Scheduler v3 Responsive", layout="wide")
st.title("📱 SIP Scheduler v3 — Responsive Mode")
st.caption("자동으로 화면 크기를 감지해 모바일 / PC 레이아웃을 전환합니다.")

init_db()

cars = qdf("SELECT * FROM car_model ORDER BY car_name")
car = st.selectbox("차종 선택", cars["car_name"])
car_id = int(cars.loc[cars.car_name == car, "car_id"].iloc[0])
axle = st.radio("Axle", ["Front", "Rear"], horizontal=not is_mobile)

wbs_df = qdf("SELECT * FROM wbs_item WHERE car_id=? AND axle=? ORDER BY parent_id, sort_key", (car_id, axle))
if wbs_df.empty:
    st.warning("⚠️ 선택된 Axle에 WBS 데이터가 없습니다.")
    st.stop()

sel_wbs = st.selectbox("📂 WBS 선택", wbs_df["name"])
sel_id = int(wbs_df.loc[wbs_df.name == sel_wbs, "wbs_id"].iloc[0])

# --- 모바일/PC 별 UI 차이 ---
if is_mobile:
    st.info("📱 모바일 모드로 자동 전환되었습니다.")
    tabs = st.tabs(["액티비티", "간트차트"])
    with tabs[0]:
        acts = qdf("""SELECT activity_name, start_date, end_date, leadtime_week, progress 
                      FROM activity WHERE wbs_id=? ORDER BY seq""", (sel_id,))
        st.dataframe(acts, use_container_width=True, height=300)
    with tabs[1]:
        gantt_df = qdf("""SELECT a.activity_name, a.category, a.start_date, a.end_date, w.type
                          FROM activity a JOIN wbs_item w ON a.wbs_id=w.wbs_id
                          WHERE w.car_id=? AND w.axle=? ORDER BY w.sort_key""", (car_id, axle))
        if not gantt_df.empty:
            gantt_df["Start"] = pd.to_datetime(gantt_df["start_date"])
            gantt_df["Finish"] = pd.to_datetime(gantt_df["end_date"])
            fig = px.timeline(gantt_df, x_start="Start", x_end="Finish", y="activity_name",
                              color="category", height=400)
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
else:
    st.info("💻 데스크톱 모드로 표시 중입니다.")
    left, right = st.columns([1, 2])
    with left:
        acts = qdf("""SELECT act_id, activity_name, start_date, end_date, leadtime_week, progress
                      FROM activity WHERE wbs_id=? ORDER BY seq""", (sel_id,))
        gb = GridOptionsBuilder.from_dataframe(acts)
        gb.configure_default_column(editable=True)
        gb.configure_column("leadtime_week", header="Leadtime (week)")
        grid = AgGrid(acts, gridOptions=gb.build(), update_mode=GridUpdateMode.VALUE_CHANGED, height=300)
        if st.button("💾 저장"):
            edited = grid["data"]
            rows = []
            for r in edited.itertuples():
                s = pd.to_datetime(r.start_date).date()
                e = s + timedelta(weeks=int(r.leadtime_week)) - timedelta(days=1)
                rows.append((s.isoformat(), e.isoformat(), int(r.leadtime_week), int(r.act_id)))
            with get_conn() as conn:
                conn.executemany("UPDATE activity SET start_date=?, end_date=?, leadtime_week=? WHERE act_id=?", rows)
                conn.commit()
            recalc_activity_dates(sel_id)
            st.success("✅ 저장 및 종료일 갱신 완료")
    with right:
        gantt_df = qdf("""SELECT a.activity_name, a.category, a.start_date, a.end_date, w.type
                          FROM activity a JOIN wbs_item w ON a.wbs_id=w.wbs_id
                          WHERE w.car_id=? AND w.axle=? ORDER BY w.sort_key""", (car_id, axle))
        if not gantt_df.empty:
            gantt_df["Start"] = pd.to_datetime(gantt_df["start_date"])
            gantt_df["Finish"] = pd.to_datetime(gantt_df["end_date"])
            fig = px.timeline(gantt_df, x_start="Start", x_end="Finish", y="activity_name",
                              color="category", height=550)
            fig.update_yaxes(autorange="reversed")
            fig.update_xaxes(dtick="M1", tickformat="%b %d")
            st.plotly_chart(fig, use_container_width=True)
