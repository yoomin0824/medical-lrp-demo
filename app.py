import streamlit as st
import folium
import random
from streamlit_folium import st_folium

st.title("의료 취약지 최적 배치 데모")

budget   = st.sidebar.slider("예산 (억원)", 0, 100, 30)
n_new    = st.sidebar.number_input("신규 병원 수", 0, 10, 2)
n_extend = st.sidebar.number_input("진료 연장 가능 병원 수", 0, 10, 1)
n_veh    = st.sidebar.number_input("이동의료차 대수", 0, 5, 1)

def dummy_optimize(budget, n_new, n_extend, n_veh):
    base_lat, base_lon = 37.45, 126.70
    new_hospitals = [
        [base_lat + random.uniform(-0.1, 0.1), base_lon + random.uniform(-0.1, 0.1)]
        for _ in range(int(n_new))
    ]
    mobile_routes = [
        [[base_lat + random.uniform(-0.1, 0.1), base_lon + random.uniform(-0.1, 0.1)] for _ in range(3)]
        for _ in range(int(n_veh))
    ]
    return {"new_hospitals": new_hospitals, "mobile_routes": mobile_routes}

if st.sidebar.button("최적 배치 실행"):
    result = dummy_optimize(budget, n_new, n_extend, n_veh)
    m = folium.Map(location=[37.45, 126.70], zoom_start=11)
    for site in result["new_hospitals"]:
        folium.Marker(site, icon=folium.Icon(color="red"), popup="신규 병원 추천지").add_to(m)
    for route in result["mobile_routes"]:
        folium.PolyLine(route, color="blue").add_to(m)
    st_folium(m, width=700)
else:
    st.info("왼쪽에서 값을 입력하고 '최적 배치 실행' 버튼을 눌러보세요.")