import re
import sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import plotly.express as px
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import plotly.graph_objects as go

st.set_page_config(page_title="SIP PM Scheduler (Week-based)", page_icon="🛠️", layout="wide")
st.title("🧩 SIP PM Scheduler — Week-based")
DB_PATH = "sip_pm.db"

# ====================== DB 유틸 ======================
def get_conn():
    return sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)

def run(sql, params=()):
    with get_conn() as c:
        c.execute(sql, params)
        c.commit()

def qdf(sql, params=()):
    with get_conn() as c:
        return pd.read_sql_query(sql, c, params=params)

# ====================== ISO Week 유틸 ======================
# 허용 포맷: "W2525" (YYWW -> 2025년 25주로 해석), "W2025-25", "2025W25", "2025-W25"
WEEK_PATTERNS = [
    re.compile(r"^W(?P<yy>\d{2})(?P<ww>\d{2})$"),               # W2525 -> 20+YY, WW
    re.compile(r"^W(?P<yyyy>\d{4})-?(?P<ww>\d{2})$"),           # W2025-25 or W202525
    re.compile(r"^(?P<yyyy>\d{4})-?W(?P<ww>\d{2})$"),           # 2025-W25 or 2025W25
]

def parse_week_code(s: str):
    if s is None:
        return None
    s = str(s).strip().upper()
    if not s:
        return None
    for pat in WEEK_PATTERNS:
        m = pat.match(s)
        if m:
            if "yy" in m.groupdict():
                yy = int(m.group("yy"))
                yyyy = 2000 + yy if yy < 70 else 1900 + yy
                ww = int(m.group("ww"))
                return yyyy, ww
            yyyy = int(m.group("yyyy"))
            ww = int(m.group("ww"))
            return yyyy, ww
    return None

def week_code(yyyy:int, ww:int) -> str:
    return f"W{yyyy}-{ww:02d}"

def monday_of_iso_week(yyyy:int, ww:int) -> date:
    # ISO 주차 월요일 계산
    return date.fromisocalendar(yyyy, ww, 1)

def sunday_of_iso_week(yyyy:int, ww:int) -> date:
    return date.fromisocalendar(yyyy, ww, 7)

def add_weeks(yyyy:int, ww:int, delta_weeks:int):
    d = monday_of_iso_week(yyyy, ww) + timedelta(weeks=delta_weeks)
    iso = d.isocalendar()  # (year, week, weekday)
    return iso.year, iso.week

def lead_from_week_to_week(s_year:int, s_week:int, e_year:int, e_week:int) -> int:
    smon = monday_of_iso_week(s_year, s_week)
    emon = monday_of_iso_week(e_year, e_week)
    diff_weeks = (emon - smon).days // 7
    # 포함 구간 기준: start 주부터 end 주까지 갯수
    return max(1, diff_weeks + 1)

def end_week_from_start_and_lead(s_year:int, s_week:int, lead_weeks:int):
    # start 주 포함, lead_weeks 주 span -> 끝 주는 start + (lead-1)주
    return add_weeks(s_year, s_week, max(1, int(lead_weeks)) - 1)

def week_or_default(val, default_year_week):
    parsed = parse_week_code(val) if val else None
    return parsed if parsed else default_year_week

# ====================== 방탄 캐스팅 ======================
def to_int_safe(x, default=None):
    try:
        sx = str(x).strip()
        # 숫자만 남기기
        sx = re.sub(r"[^\d\-+]", "", sx)
        return int(sx)
    except Exception:
        return default

# ====================== 스키마 ======================
SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS car (
  car_id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_name TEXT UNIQUE NOT NULL,
  platform TEXT,
  sop TEXT
);

CREATE TABLE IF NOT EXISTS part (
  part_id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id INTEGER NOT NULL REFERENCES car(car_id) ON DELETE CASCADE,
  axle TEXT CHECK(axle IN ('Front','Rear')) NOT NULL,
  part_name TEXT NOT NULL,
  UNIQUE(car_id, axle, part_name)
);

CREATE TABLE IF NOT EXISTS activity (
  act_id INTEGER PRIMARY KEY AUTOINCREMENT,
  part_id INTEGER NOT NULL REFERENCES part(part_id) ON DELETE CASCADE,
  category TEXT,
  name TEXT NOT NULL,
  owner TEXT,
  start_week TEXT,
  end_week TEXT,
  lead_weeks INTEGER NOT NULL DEFAULT 1,
  progress INTEGER NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'Planned',
  seq INTEGER,
  is_milestone INTEGER DEFAULT 0
);
"""

DETAILED_ACTIVITIES = [
    ("설계", "3D 설계 착수", 2),
    ("설계", "하드포인트 협의", 1),
    ("해석", "강도/강성 해석 1차", 2),
    ("해석", "Compliance 해석", 1),
    ("해석", "NVH 해석", 1),
    ("금형", "시제품 금형 발주", 3),
    ("시제품", "Prototype 제작", 2),
    ("시험", "Static 시험", 1),
    ("시험", "Fatigue 시험", 2),
    ("시험", "NVH 시험", 1),
    ("품질 문서", "DFMEA/DR 문서 작성", 1),
    ("승인", "Design Release (DRR)", 1),
    ("양산 준비", "금형 Kick-off", 2),
    ("양산 준비", "금형 완료 & 시사출", 3),
    ("승인", "PSW 제출", 1),
    ("시험", "PPAP 시험", 1),
    ("양산 전환", "SOP 대응", 1),
]

def init_db():
    with get_conn() as c:
        c.executescript(SCHEMA)
    if qdf("SELECT COUNT(*) n FROM car").iloc[0, 0] == 0:
        run("INSERT INTO car(car_name, platform, sop) VALUES (?,?,?)", ("SM6", "CMF-D", "2026-03-01"))
        car_id = qdf("SELECT car_id FROM car WHERE car_name=?", ("SM6",)).iloc[0, 0]
        for axle in ("Front", "Rear"):
            for part_name in ("Lower Arm", "Knuckle", "Subframe"):
                run("INSERT INTO part(car_id, axle, part_name) VALUES (?,?,?)", (car_id, axle, part_name))
        parts = qdf("SELECT part_id FROM part WHERE car_id=?", (car_id,))
        # 기준: 오늘 날짜의 ISO 연/주
        today_iso = date.today().isocalendar()
        base_year, base_week = today_iso.year, today_iso.week
        for pid in parts.part_id:
            seq = 1
            for cat, nm, lw in DETAILED_ACTIVITIES:
                # 순차로 주차 증가
                sy, sw = add_weeks(base_year, base_week, seq - 1)
                ey, ew = end_week_from_start_and_lead(sy, sw, lw)
                run(
                    """INSERT INTO activity(part_id, category, name, owner, start_week, end_week, lead_weeks, progress, status, seq)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (int(pid), cat, nm, "", week_code(sy, sw), week_code(ey, ew), int(lw), 0, "Planned", seq),
                )
                seq += 1

init_db()

def ensure_milestone_column():
    with get_conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(activity);").fetchall()]
        if "is_milestone" not in cols:
            c.execute("ALTER TABLE activity ADD COLUMN is_milestone INTEGER DEFAULT 0;")
            c.commit()

ensure_milestone_column()

# ====================== 데이터 로딩 ======================
def ensure_part_activities(pid: int):
    df = qdf("SELECT COUNT(*) n FROM activity WHERE part_id=?", (pid,))
    if df.iloc[0, 0] == 0:
        today_iso = date.today().isocalendar()
        base_year, base_week = today_iso.year, today_iso.week
        seq = 1
        for cat, nm, lw in DETAILED_ACTIVITIES:
            sy, sw = add_weeks(base_year, base_week, seq - 1)
            ey, ew = end_week_from_start_and_lead(sy, sw, lw)
            run(
                """INSERT INTO activity(part_id, category, name, owner, start_week, end_week, lead_weeks, progress, status, seq)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, cat, nm, "", week_code(sy, sw), week_code(ey, ew), int(lw), 0, "Planned", seq),
            )
            seq += 1

def load_activities(pid: int):
    ensure_part_activities(pid)
    df = qdf("SELECT * FROM activity WHERE part_id=? ORDER BY seq", (pid,))
    # 빈 값 보이지 않게 기본 포맷으로 표기
    df["start_week"] = df["start_week"].fillna("")
    df["end_week"] = df["end_week"].fillna("")
    # 표시 컬럼 순서
    disp = ["act_id","seq","category","name","owner","start_week","lead_weeks","end_week","progress","status","is_milestone"]
    return df[disp]

# ====================== 사이드바: 차종/부품 CRUD ======================
st.sidebar.header("🎛 차종/부품 관리")

# 차종
with st.sidebar.expander("🚗 차종 관리", expanded=True):
    cars = qdf("SELECT * FROM car ORDER BY car_name")
    car_names = cars["car_name"].tolist()
    sel_car = st.selectbox("차종 선택", car_names) if car_names else st.text_input("차종 없음. 새로 추가하세요", "")
    cur_car_id = int(cars.loc[cars.car_name == sel_car, "car_id"].iloc[0]) if car_names else None

    new_car_name = st.text_input("차종명", value=sel_car if car_names else "")
    new_platform = st.text_input("플랫폼", value=cars.loc[cars.car_name == sel_car, "platform"].iloc[0] if car_names else "")
    new_sop = st.text_input("SOP(YYYY-MM-DD)", value=cars.loc[cars.car_name == sel_car, "sop"].iloc[0] if car_names else "")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("➕ 차종 추가"):
            nm = new_car_name.strip() or "NEW_CAR"
            run("INSERT INTO car(car_name, platform, sop) VALUES (?,?,?)", (nm, new_platform, new_sop))
            st.rerun()
    with c2:
        if st.button("💾 차종 저장", disabled=cur_car_id is None):
            run("UPDATE car SET car_name=?, platform=?, sop=? WHERE car_id=?", (new_car_name.strip() or sel_car, new_platform, new_sop, cur_car_id))
            st.rerun()
    with c3:
        if st.button("🗑️ 차종 삭제", disabled=cur_car_id is None):
            run("DELETE FROM car WHERE car_id=?", (cur_car_id,))
            st.rerun()

# 부품
with st.sidebar.expander("🔧 부품 관리", expanded=True):
    # 최신 차종 다시 조회
    cars = qdf("SELECT * FROM car ORDER BY car_name")
    sel_car = new_car_name.strip() if new_car_name and (new_car_name.strip() in cars["car_name"].values) else sel_car
    car_id = int(cars.loc[cars.car_name == sel_car, "car_id"].iloc[0])

    axle = st.radio("축(Axle)", ["Front","Rear"], horizontal=True, key="axle_radio")
    parts = qdf("SELECT * FROM part WHERE car_id=? AND axle=? ORDER BY part_name", (car_id, axle))
    part_names = parts["part_name"].tolist()
    sel_part = st.selectbox("부품 선택", part_names) if part_names else "<없음>"
    cur_part_id = int(parts.loc[parts.part_name == sel_part, "part_id"].iloc[0]) if sel_part in part_names else None

    edit_part_name = st.text_input("부품명", value=sel_part if sel_part in part_names else "")

    p1, p2, p3 = st.columns(3)
    with p1:
        if st.button("➕ 부품 추가"):
            nm = (edit_part_name.strip() or "New Part")
            run("INSERT INTO part(car_id, axle, part_name) VALUES (?,?,?)", (car_id, axle, nm))
            pid = int(qdf("SELECT part_id FROM part WHERE car_id=? AND axle=? AND part_name=?", (car_id, axle, nm)).iloc[0,0])
            ensure_part_activities(pid)
            st.rerun()
    with p2:
        if st.button("💾 부품 저장", disabled=cur_part_id is None):
            nm = (edit_part_name.strip() or sel_part)
            run("UPDATE part SET part_name=?, axle=? WHERE part_id=?", (nm, axle, cur_part_id))
            st.rerun()
    with p3:
        if st.button("🗑️ 부품 삭제", disabled=cur_part_id is None):
            run("DELETE FROM part WHERE part_id=?", (cur_part_id,))
            st.rerun()

# ====================== 메인 컨텍스트 ======================
cars = qdf("SELECT * FROM car ORDER BY car_name")
if cars.empty:
    st.warning("차종이 없습니다. 사이드바에서 추가하세요.")
    st.stop()

car_id = int(cars.loc[cars.car_name == sel_car, "car_id"].iloc[0])
axle = st.session_state.get("axle_radio","Front")
parts = qdf("SELECT * FROM part WHERE car_id=? AND axle=? ORDER BY part_name", (car_id, axle))
if parts.empty:
    st.warning("부품이 없습니다. 사이드바에서 추가하세요.")
    st.stop()
if sel_part not in parts["part_name"].values:
    sel_part = parts["part_name"].iloc[0]
part_id = int(parts.loc[parts.part_name == sel_part, "part_id"].iloc[0])

st.subheader(f"📋 {sel_car} / {axle} / {sel_part} — 상세 액티비티 (Week-based)")

# ====================== 액티비티 Grid ======================
acts = load_activities(part_id)
gb = GridOptionsBuilder.from_dataframe(acts)
gb.configure_default_column(editable=True, resizable=True)
gb.configure_column("act_id", editable=False)
gb.configure_column("is_milestone", header_name="⭐ Milestone", editable=True, cellEditor='agSelectCellEditor',
                    cellEditorParams={'values': [0,1]})
gb.configure_selection("single")
grid = AgGrid(
    acts,
    gridOptions=gb.build(),
    theme="balham",
    height=440,
    update_mode=GridUpdateMode.VALUE_CHANGED | GridUpdateMode.SELECTION_CHANGED,
)
edited_df = grid["data"]
sel_rows = pd.DataFrame(grid["selected_rows"])
sel_act_id = int(sel_rows.iloc[0]["act_id"]) if not sel_rows.empty else None

# ====================== 액션 버튼 ======================
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("➕ 액티비티 추가"):
        # 기본은 현재 주차부터 1주짜리
        iso = date.today().isocalendar()
        sy, sw = iso.year, iso.week
        ey, ew = end_week_from_start_and_lead(sy, sw, 1)
        run(
            """INSERT INTO activity(part_id, category, name, owner, start_week, end_week, lead_weeks, progress, status, seq)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (part_id, "설계", "신규 액티비티", "", week_code(sy, sw), week_code(ey, ew), 1, 0, "Planned",
             int(pd.to_numeric(acts["seq"], errors="coerce").max() or 0) + 1),
        )
        st.rerun()

with c1:
    if st.button("💎 마일스톤 추가"):
        iso = date.today().isocalendar()
        sy, sw = iso.year, iso.week
        run(
            """INSERT INTO activity(part_id, category, name, owner, start_week, end_week, lead_weeks, progress, status, seq, is_milestone)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (part_id, "마일스톤", "신규 마일스톤", "", week_code(sy, sw), week_code(sy, sw), 0, 0, "Planned",
             int(pd.to_numeric(acts["seq"], errors="coerce").max() or 0) + 1),
        )
        st.rerun()

with c2:
    if st.button("🗑️ 선택 삭제", disabled=sel_act_id is None):
        run("DELETE FROM activity WHERE act_id=?", (sel_act_id,))
        st.rerun()

with c3:
    if st.button("💾 변경 저장"):
        rows = []
        for r in edited_df.itertuples():
            # 안전 파싱
            seq_val = int(pd.to_numeric(getattr(r, "seq"), errors="coerce") or 0)
            lead_val = int(pd.to_numeric(getattr(r, "lead_weeks"), errors="coerce") or 0)
            lead_val = lead_val if lead_val > 0 else None

            sw_raw = getattr(r, "start_week")
            ew_raw = getattr(r, "end_week")

            # 기본 주차: 시작 주가 없을 경우 오늘 주
            today_iso = date.today().isocalendar()
            base_year_week = (today_iso.year, today_iso.week)

            s_pair = week_or_default(sw_raw, base_year_week)
            e_pair = parse_week_code(ew_raw) if ew_raw else None

            # ---- 양방향 계산 로직 ----
            if s_pair and lead_val and not e_pair:
                # start + lead -> end
                ey, ew = end_week_from_start_and_lead(s_pair[0], s_pair[1], lead_val)
                e_pair = (ey, ew)
            elif s_pair and e_pair and not lead_val:
                # start + end -> lead
                lead_val = lead_from_week_to_week(s_pair[0], s_pair[1], e_pair[0], e_pair[1])
            elif s_pair and e_pair and lead_val:
                # 일관성 유지: lead 기준으로 end 재보정
                ey, ew = end_week_from_start_and_lead(s_pair[0], s_pair[1], lead_val)
                e_pair = (ey, ew)
            else:
                # 최소 보정: start만 있는 경우 lead=1, end=start
                if s_pair and not e_pair and not lead_val:
                    lead_val = 1
                    e_pair = s_pair

            # 최종 문자열
            start_week_str = week_code(s_pair[0], s_pair[1]) if s_pair else ""
            end_week_str = week_code(e_pair[0], e_pair[1]) if e_pair else ""

            rows.append(
                (
                    getattr(r, "category") or "",
                    getattr(r, "name") or "",
                    getattr(r, "owner") or "",
                    start_week_str,
                    end_week_str,
                    int(lead_val or 1),
                    int(pd.to_numeric(getattr(r, "progress"), errors="coerce") or 0),
                    getattr(r, "status") or "Planned",
                    seq_val,
                    int(getattr(r, "act_id")),
                )
            )

        with get_conn() as c:
            c.executemany(
                """UPDATE activity
                   SET category=?, name=?, owner=?, start_week=?, end_week=?, lead_weeks=?, progress=?, status=?, seq=?
                   WHERE act_id=?""",
                rows,
            )
            c.commit()
        st.success("변경사항 저장 + 양방향 계산 완료 ✅")
        st.session_state["acts_cache"] = load_activities(part_id)

# ====================== 간트 차트 (주차 → 날짜 환산) ======================
st.subheader("📅 간트 차트 (Week-based)")

gdf = load_activities(part_id).copy()

def weeks_to_dates_row(row):
    s_pair = parse_week_code(row["start_week"])
    e_pair = parse_week_code(row["end_week"])
    if not s_pair:
        return pd.Series({"Start": pd.NaT, "Finish": pd.NaT})
    smon = monday_of_iso_week(s_pair[0], s_pair[1])
    if not e_pair:
        e_pair = s_pair
    esun = sunday_of_iso_week(e_pair[0], e_pair[1])
    return pd.Series({"Start": pd.to_datetime(smon), "Finish": pd.to_datetime(esun)})

dates_df = gdf.apply(weeks_to_dates_row, axis=1)
gdf = pd.concat([gdf, dates_df], axis=1)

import plotly.graph_objects as go

# === 일반 액티비티용 기본 간트 ===
# 마일스톤(♦) 아닌 행만 막대로 표시
bars_df = gdf[gdf.get("is_milestone", 0) != 1].copy()
milestones_df = gdf[gdf.get("is_milestone", 0) == 1].copy()

fig = px.timeline(
    bars_df,
    x_start="Start",
    x_end="Finish",
    y="name",
    color="category",
    hover_data=["start_week", "end_week", "lead_weeks", "progress", "status"]
)

fig.update_traces(opacity=0.8)  # 막대는 약간 투명하게
fig.update_yaxes(autorange="reversed")

# === 마일스톤 전용 다이아몬드 표시 ===
if not milestones_df.empty:
    milestones_df["Start"] = milestones_df["Start"].fillna(milestones_df["Finish"])
    milestones_df["Finish"] = milestones_df["Start"]

    x_vals = milestones_df["Start"]
    y_vals = milestones_df["name"]

    # 모양 선택 (symbol 목록: https://plotly.com/python/marker-style/)
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        mode="markers+text",
        text=["⬢" for _ in range(len(x_vals))],  # 유니코드 육각형 마커
        textposition="top center",
        marker=dict(
            symbol="diamond-tall",  # 더 날렵한 다이아몬드
            size=22,
            color="#ff0066",
            line=dict(color="white", width=1.5),
            opacity=1.0
        ),
        name="Milestone",
        hovertext=[f"{nm}" for nm in milestones_df["name"]],
        hoverinfo="text"
    ))

# === 전체 스타일 ===
fig.update_layout(
    height=600,
    xaxis=dict(
        tickformat="%Y-%m-%d",
        title="Date",
        showgrid=True,
        gridcolor="rgba(200,200,200,0.3)"
    ),
    yaxis=dict(title="Activity", showgrid=False),
    title=f"{sel_car} / {axle} / {sel_part} — Week-based Gantt (Milestones)",
    legend_title="Category",
    plot_bgcolor="rgba(250,250,250,1)",
    paper_bgcolor="rgba(255,255,255,1)",
)

st.plotly_chart(fig, use_container_width=True)