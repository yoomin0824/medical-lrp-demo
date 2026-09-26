import streamlit as st
import pandas as pd
import numpy as np
import random
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="인천 소아과 의료 취약지 최적 배치", page_icon="🏥", layout="wide")

st.markdown("""
<style>
    .main { background-color: #f7fafc; }
    .header-banner {
        background: linear-gradient(90deg, #1b68cf, #4a90d9);
        padding: 32px 40px; border-radius: 16px; margin-bottom: 24px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .header-banner h1 { color: white; margin: 0; font-size: 28px; }
    .header-banner p { color: #dbeafe; margin: 8px 0 0 0; font-size: 15px; }
    .metric-card {
        background: white; border-radius: 12px; padding: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center;
        border-top: 4px solid #1b68cf;
    }
    .metric-card .num { font-size: 32px; font-weight: 700; color: #1b68cf; }
    .metric-card .label { font-size: 14px; color: #64748b; margin-top: 4px; }
    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e2e8f0; }
    div.stButton > button {
        background-color: #1b68cf; color: white; border-radius: 8px;
        border: none; padding: 10px 0; font-weight: 600; width: 100%;
    }
    div.stButton > button:hover { background-color: #144e9c; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="header-banner">
    <h1>🏥 인천광역시 소아과 의료 취약지 최적 배치 데모</h1>
    <p>예산과 자원 조건을 입력하면, LRP 최적화로 신규 병원·진료연장·이동의료 배치를 계산합니다</p>
</div>
""", unsafe_allow_html=True)

@st.cache_data
def load_data():
    gdf = pd.read_csv("gdf_export.csv")
    hosp = pd.read_csv("hosp_export.csv")
    candidates = pd.read_csv("candidates_export.csv")
    return gdf, hosp, candidates

gdf, hosp, candidates = load_data()

RADIUS_KM = 5
NEW_HOSPITAL_CAPACITY = 40
EXTENSION_HOURS = 20
MOBILE_WEEKLY_HOURS = 8
COST_PER_NEW_HOSPITAL = 100
COST_PER_EXTENSION = 20
COST_PER_VEHICLE = 30

def haversine_matrix(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

oa_lat = gdf['lat'].values.reshape(1,-1)
oa_lon = gdf['lon'].values.reshape(1,-1)
demand = gdf['child_pop'].values

hosp_lat = hosp['위도'].values.reshape(-1,1)
hosp_lon = hosp['경도'].values.reshape(-1,1)
within_radius = haversine_matrix(hosp_lat, hosp_lon, oa_lat, oa_lon) <= RADIUS_KM

cand_lat = candidates['lat'].values.reshape(-1,1)
cand_lon = candidates['lon'].values.reshape(-1,1)
cand_within_radius = haversine_matrix(cand_lat, cand_lon, oa_lat, oa_lon) <= RADIUS_KM

N_CANDIDATES = len(candidates)
N_HOSPITALS = len(hosp)
candidate_oa_codes = candidates["TOT_OA_CD"].tolist()
oa_index = {code: i for i, code in enumerate(gdf["TOT_OA_CD"])}

def recompute_accessibility(new_sites, extend):
    cap = hosp['weekly_hours'].values + np.array(extend) * EXTENSION_HOURS
    dsum = within_radius @ demand
    ratio = np.divide(cap, dsum, out=np.zeros_like(cap, dtype=float), where=dsum > 0)
    acc = within_radius.T @ ratio
    ncap = np.array(new_sites, dtype=float) * NEW_HOSPITAL_CAPACITY
    ndsum = cand_within_radius @ demand
    nratio = np.divide(ncap, ndsum, out=np.zeros_like(ncap, dtype=float), where=ndsum > 0)
    acc += cand_within_radius.T @ nratio
    return acc

def apply_routes_bonus(acc, routes):
    acc = acc.copy()
    for route in routes:
        if len(route) == 0: continue
        cap_per_stop = MOBILE_WEEKLY_HOURS / len(route)
        for stop in route:
            idx = oa_index[candidate_oa_codes[stop]]
            d = demand[idx]
            acc[idx] += (cap_per_stop / d) if d > 0 else 0
    return acc

baseline_acc = recompute_accessibility([0]*N_CANDIDATES, [0]*N_HOSPITALS)
threshold = np.quantile(baseline_acc, 0.3)
vulnerable_idx = [i for i in range(len(gdf)) if baseline_acc[i] <= threshold and demand[i] > 0]

MAX_ROUTE_RADIUS_KM = 30
def haversine_point(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

def make_route_near(start_idx, max_stops):
    start_lat = candidates.iloc[start_idx]["lat"]
    start_lon = candidates.iloc[start_idx]["lon"]
    nearby = [i for i in range(N_CANDIDATES)
              if haversine_point(start_lat, start_lon, candidates.iloc[i]["lat"], candidates.iloc[i]["lon"]) <= MAX_ROUTE_RADIUS_KM]
    n_stops = min(max_stops, len(nearby))
    return random.sample(nearby, n_stops) if n_stops > 0 else [start_idx]

def make_random_solution(max_new, max_extend, n_vehicles):
    new_sites = [1 if random.random() < 0.15 else 0 for _ in range(N_CANDIDATES)]
    extend = [1 if random.random() < 0.15 else 0 for _ in range(N_HOSPITALS)]
    routes = []
    for _ in range(n_vehicles):
        start = random.randrange(N_CANDIDATES)
        routes.append(make_route_near(start, random.randint(1,4)))
    return {"new_sites": new_sites, "extend": extend, "routes": routes}

def repair(sol, budget, max_new, max_extend):
    chosen_new = [i for i,v in enumerate(sol["new_sites"]) if v==1]
    while len(chosen_new) > max_new:
        d = random.choice(chosen_new); sol["new_sites"][d]=0; chosen_new.remove(d)
    chosen_ext = [i for i,v in enumerate(sol["extend"]) if v==1]
    while len(chosen_ext) > max_extend:
        d = random.choice(chosen_ext); sol["extend"][d]=0; chosen_ext.remove(d)
    cost = len(chosen_new)*COST_PER_NEW_HOSPITAL + len(chosen_ext)*COST_PER_EXTENSION + len(sol["routes"])*COST_PER_VEHICLE
    while cost > budget and len(chosen_new) > 0:
        d = random.choice(chosen_new); sol["new_sites"][d]=0; chosen_new.remove(d); cost -= COST_PER_NEW_HOSPITAL
    while cost > budget and len(chosen_ext) > 0:
        d = random.choice(chosen_ext); sol["extend"][d]=0; chosen_ext.remove(d); cost -= COST_PER_EXTENSION
    return sol

def evaluate(sol, budget, max_new, max_extend):
    sol = repair(sol, budget, max_new, max_extend)
    acc = apply_routes_bonus(recompute_accessibility(sol["new_sites"], sol["extend"]), sol["routes"])
    return sum(acc[i] - baseline_acc[i] for i in vulnerable_idx)

def mutate(sol):
    r1, r2 = 1/max(len(sol["new_sites"]),1), 1/max(len(sol["extend"]),1)
    sol["new_sites"] = [1-v if random.random()<r1 else v for v in sol["new_sites"]]
    sol["extend"] = [1-v if random.random()<r2 else v for v in sol["extend"]]
    return sol

def crossover(p1, p2):
    c1 = random.randint(1, len(p1["new_sites"])-1)
    c2 = random.randint(1, len(p1["extend"])-1)
    return {"new_sites": p1["new_sites"][:c1]+p2["new_sites"][c1:],
            "extend": p1["extend"][:c2]+p2["extend"][c2:],
            "routes": random.choice([p1["routes"], p2["routes"]])}

def run_ga(budget, max_new, max_extend, n_vehicles, pop_size=30, n_gen=25):
    pop = [make_random_solution(max_new, max_extend, n_vehicles) for _ in range(pop_size)]
    for _ in range(n_gen):
        fits = [evaluate(s, budget, max_new, max_extend) for s in pop]
        best = pop[fits.index(max(fits))]
        new_pop = [best]
        while len(new_pop) < pop_size:
            p1 = pop[random.choice(sorted(range(pop_size), key=lambda i: fits[i])[-3:])]
            p2 = pop[random.choice(sorted(range(pop_size), key=lambda i: fits[i])[-3:])]
            new_pop.append(mutate(crossover(p1, p2)))
        pop = new_pop
    fits = [evaluate(s, budget, max_new, max_extend) for s in pop]
    return pop[fits.index(max(fits))]

with st.sidebar:
    st.markdown("### ⚙️ 배치 조건 설정")
    budget = st.slider("💰 예산 (억원)", 500, 12000, 3000, step=500)
    n_new = st.number_input("🏥 신규 병원 수 (최대)", 0, N_CANDIDATES, 5)
    n_extend = st.number_input("🕐 진료 연장 가능 병원 수 (최대)", 0, N_HOSPITALS, 10)
    n_veh = st.number_input("🚑 이동의료차 대수", 0, 5, 2)
    run_btn = st.button("최적 배치 실행")

if "result" not in st.session_state:
    st.session_state["result"] = None

if run_btn:
    with st.spinner("최적 배치를 계산하는 중입니다... (20~40초 소요)"):
        st.session_state["result"] = run_ga(budget, n_new, n_extend, n_veh)

if st.session_state["result"] is not None:
    sol = st.session_state["result"]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="metric-card"><div class="num">{sum(sol["new_sites"])}</div><div class="label">🏥 신규 병원</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><div class="num">{sum(sol["extend"])}</div><div class="label">🕐 연장진료 병원</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><div class="num">{len(sol["routes"])}</div><div class="label">🚑 이동의료 경로</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    m = folium.Map(location=[37.45, 126.7], zoom_start=10, tiles="CartoDB positron")
    for i, v in enumerate(sol["new_sites"]):
        if v == 1:
            row = candidates.iloc[i]
            folium.Marker([row["lat"], row["lon"]], icon=folium.Icon(color="red", icon="plus-sign"), popup="신규 병원").add_to(m)
    for route in sol["routes"]:
        pts = [[candidates.iloc[s]["lat"], candidates.iloc[s]["lon"]] for s in route]
        if len(pts) > 1:
            folium.PolyLine(pts, color="#1b68cf", weight=3).add_to(m)
        for p in pts:
            folium.CircleMarker(p, radius=5, color="#1b68cf", fill=True, fill_opacity=0.8, popup="이동의료 방문지").add_to(m)
    st_folium(m, width=1100, height=500)
else:
    st.info("👈 왼쪽에서 조건을 입력하고 **'최적 배치 실행'** 버튼을 눌러보세요.")
