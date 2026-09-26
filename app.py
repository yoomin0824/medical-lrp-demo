import streamlit as st
import pandas as pd
import numpy as np
import random
import folium
from streamlit_folium import st_folium

st.title("의료 취약지 최적 배치 데모 (인천 소아과)")

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
MAX_ROUTE_RADIUS_KM = 30  # 이동의료차 한 경로 안 정류장들은 이 거리 이내로 제한

def haversine_matrix(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

def haversine_point(lat1, lon1, lat2, lon2):
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

budget = st.sidebar.slider("예산 (억원)", 500, 12000, 3000, step=500)
n_new = st.sidebar.number_input("신규 병원 수 (최대)", 0, N_CANDIDATES, 5)
n_extend = st.sidebar.number_input("진료 연장 가능 병원 수 (최대)", 0, N_HOSPITALS, 10)
n_veh = st.sidebar.number_input("이동의료차 대수", 0, 5, 2)

if "result" not in st.session_state:
    st.session_state["result"] = None

if st.sidebar.button("최적 배치 실행"):
    with st.spinner("계산 중... (20~40초 소요)"):
        st.session_state["result"] = run_ga(budget, n_new, n_extend, n_veh)

if st.session_state["result"] is not None:
    sol = st.session_state["result"]
    m = folium.Map(location=[37.45, 126.7], zoom_start=10)
    for i, v in enumerate(sol["new_sites"]):
        if v == 1:
            row = candidates.iloc[i]
            folium.Marker([row["lat"], row["lon"]], icon=folium.Icon(color="red"), popup="신규 병원").add_to(m)
    for route in sol["routes"]:
        pts = [[candidates.iloc[s]["lat"], candidates.iloc[s]["lon"]] for s in route]
        if len(pts) > 1:
            folium.PolyLine(pts, color="blue").add_to(m)
        for p in pts:
            folium.CircleMarker(p, radius=4, color="blue", fill=True, popup="이동의료 방문지").add_to(m)
    st.write(f"신규 병원 {sum(sol['new_sites'])}곳, 연장진료 {sum(sol['extend'])}곳, 이동경로 {len(sol['routes'])}개")
    st_folium(m, width=700, key="result_map")
else:
    st.info("왼쪽에서 값을 입력하고 '최적 배치 실행' 버튼을 눌러보세요.")
