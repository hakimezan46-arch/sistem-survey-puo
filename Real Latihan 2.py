import streamlit as st
import pandas as pd
import numpy as np
import math
import os
import json
from pyproj import Transformer
import folium
from streamlit_folium import st_folium
from folium.plugins import MiniMap, Fullscreen

# --- 1. SETTING HALAMAN ---
st.set_page_config(page_title="Sistem Survey Lot Pro", page_icon="🗺️", layout="wide")

# --- 2. SISTEM DATABASE FAIL (KESELAMATAN) ---
PASSWORD_FILE = "user_config.json"

def load_password():
    if os.path.exists(PASSWORD_FILE):
        try:
            with open(PASSWORD_FILE, "r") as f:
                data = json.load(f)
                return data.get("password", "admin123")
        except:
            return "admin123"
    return "admin123"

def save_password(new_pw):
    with open(PASSWORD_FILE, "w") as f:
        json.dump({"password": new_pw}, f)

if "current_password" not in st.session_state:
    st.session_state.current_password = load_password()

# --- 3. DATABASE PENGGUNA ---
USER_DB = {
    "1": "MUHAMMAD HAKIM BIN LIZON",
    "2": "KIIRTNANAA A/P MUTHUKUMAR",
    "3": "ADAM HAKIMI BIN SALEHUDDIN"
}

# --- 4. UTILITY FUNCTIONS (CACHED FOR PERFORMANCE) ---
def decimal_to_dms(deg):
    """Tukar darjah ke Format Darjah Minit Saat (DMS)"""
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m/60) * 3600
    return f"{d}° {m}' {s:.0f}\""

@st.cache_data
def process_survey_data(df, epsg_input):
    """Kira luas, perimeter, jarak, bearing dan koordinat WGS84."""
    try:
        transformer = Transformer.from_crs(f"EPSG:{epsg_input}", "EPSG:4326", always_xy=True)
        
        # Ekstrak data
        x, y = df['E'].values, df['N'].values
        stn_labels = df['STN'].astype(str).values
        num_stn = len(df)
        
        # Kira Luas & Perimeter (Shoelace formula)
        area = 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
        
        # Simpan hasil pengiraan dalam list
        processed_data = []
        poly_coords = []
        perimeter = 0
        
        for i in range(num_stn):
            p1_e, p1_n = x[i], y[i]
            p2_e, p2_n = x[(i + 1) % num_stn], y[(i + 1) % num_stn]
            
            # Koordinat Lat/Lon (WGS84)
            lon1, lat1 = transformer.transform(p1_e, p1_n)
            poly_coords.append([lat1, lon1])
            
            # Kira Jarak & Bearing ke stesen seterusnya
            dist = math.sqrt((p2_e - p1_e)**2 + (p2_n - p1_n)**2)
            perimeter += dist
            
            bearing_rad = math.atan2(p2_e - p1_e, p2_n - p1_n)
            bearing_deg = math.degrees(bearing_rad) % 360
            
            # Kira sudut teks untuk paparan peta
            angle_deg = -math.degrees(math.atan2(p2_n - p1_n, p2_e - p1_e))
            if angle_deg > 90: angle_deg -= 180
            elif angle_deg < -90: angle_deg += 180
            
            processed_data.append({
                "Dari": stn_labels[i],
                "Ke": stn_labels[(i + 1) % num_stn],
                "Easting (E)": p1_e,
                "Northing (N)": p1_n,
                "Latitud": lat1,
                "Longitud": lon1,
                "Jarak (m)": round(dist, 3),
                "Bearing (DMS)": decimal_to_dms(bearing_deg),
                "Teks_Angle": angle_deg # Untuk paparan peta sahaja
            })
            
        df_processed = pd.DataFrame(processed_data)
        centroid_lon, centroid_lat = np.mean([p[1] for p in poly_coords]), np.mean([p[0] for p in poly_coords])
        
        return df_processed, area, perimeter, poly_coords, centroid_lat, centroid_lon
    
    except Exception as e:
        return None, None, None, None, None, str(e)

def convert_to_geojson(df_processed, area, perimeter):
    """Menukar data survey kepada format GeoJSON untuk QGIS."""
    features = []
    poly_coordinates = []
    num_rows = len(df_processed)
    
    for i, row in df_processed.iterrows():
        lon, lat = row['Longitud'], row['Latitud']
        poly_coordinates.append([lon, lat])
        
        # 1. Point Features (Stesen) - Now includes Bearing & Jarak
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "Stesen": row['Dari'], 
                "E": row['Easting (E)'], 
                "N": row['Northing (N)'],
                "Ke_Stesen": row['Ke'],
                "Bearing": row['Bearing (DMS)'],
                "Jarak_m": row['Jarak (m)']
            }
        })

        # 2. NEW: LineString Features (Sempadan) - Best for QGIS labeling
        next_row = df_processed.iloc[(i + 1) % num_rows]
        next_lon, next_lat = next_row['Longitud'], next_row['Latitud']
        
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString", 
                "coordinates": [[lon, lat], [next_lon, next_lat]]
            },
            "properties": {
                "Jenis": "Garisan Sempadan",
                "Dari": row['Dari'],
                "Ke": row['Ke'],
                "Bearing": row['Bearing (DMS)'],
                "Jarak_m": row['Jarak (m)']
            }
        })
    
    # 3. Polygon Feature (Lot)
    poly_coordinates.append(poly_coordinates[0]) # Tutup poligon
    features.append({
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [poly_coordinates]},
        "properties": {"Nama": "Lot Survey", "Luas_m2": area, "Perimeter_m": perimeter}
    })
    
    return json.dumps({"type": "FeatureCollection", "features": features}, indent=4)
# --- 5. SISTEM LOG MASUK & DIALOG ---
@st.dialog("🔑 Kemaskini Kata Laluan")
def change_password_dialog(is_forgot=False):
    if is_forgot:
        st.info("Sila sahkan ID untuk menetapkan semula kata laluan.")
        check_id = st.text_input("Sahkan ID Pengguna:", key="verify_id")
    
    new_pw = st.text_input("Kata Laluan Baharu:", type="password", key="new_pw_input")
    conf_pw = st.text_input("Sahkan Kata Laluan Baharu:", type="password", key="conf_pw_input")
    
    if st.button("Simpan Kata Laluan", use_container_width=True):
        if is_forgot and check_id not in USER_DB:
            st.error("❌ ID Pengguna tidak sah!")
        elif new_pw == "" or conf_pw == "":
            st.warning("Sila isi semua ruangan!")
        elif new_pw == conf_pw:
            save_password(new_pw)
            st.session_state.current_password = new_pw
            st.success("✅ Kata laluan disimpan!")
            st.rerun()
        else:
            st.error("❌ Kata laluan tidak sepadan!")

def check_password():
    if "password_correct" not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🔐 Sistem Survey Lot PUO</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            st.info("💡 Tip: Guna ID '1' dan kata laluan 'admin123'")
            input_id = st.text_input("👤 Masukkan ID:")
            password = st.text_input("🔑 Masukkan Kata Laluan:", type="password")
            
            if st.button("Log Masuk", use_container_width=True):
                stored_pw = load_password()
                if input_id in USER_DB and password == stored_pw:
                    st.session_state.password_correct = True
                    st.session_state.user_full_name = USER_DB[input_id]
                    st.rerun()
                else:
                    st.error("❌ ID atau Kata laluan salah!")
            
            if st.button("❓ Lupa Kata Laluan?", use_container_width=True):
                change_password_dialog(is_forgot=True)
        return False
    return True

# --- 6. MAIN APP FLOW ---
if check_password():
    # --- HEADER ---
    st.markdown(f"""
        <div style="background-color:#f8f9fa; padding:15px; border-radius:10px; border-left: 6px solid #007BFF; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <h1 style='margin:0; color:#1f1f1f;'>SISTEM SURVEY LOT</h1>
                <p style='color:gray; font-size:16px; margin:0;'>Politeknik Ungku Omar | Jabatan Kejuruteraan Awam</p>
            </div>
            <div style="text-align: right;">
                <p style="margin:0; font-weight: bold;">👤 Surveyor: {st.session_state.user_full_name}</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.write("") # Spacer

    # --- SIDEBAR CONTROLS ---
    st.sidebar.header("📂 Muat Naik Data")
    epsg_input = st.sidebar.text_input("🌍 Kod EPSG Sistem Koordinat:", value="4390", help="Contoh: 4390 (Kertau / Perak)")
    uploaded_data = st.sidebar.file_uploader("Muat naik fail CSV (STN, E, N)", type="csv")
    
    st.sidebar.divider()
    
    # NEW TOGGLES ADDED HERE
    st.sidebar.header("⚙️ Kawalan Visual Peta")
    map_type = st.sidebar.radio("Jenis Paparan Peta:", ["Satelit (Google)", "Peta Jalan (OSM)"])
    
    col_t1, col_t2 = st.sidebar.columns(2)
    with col_t1:
        show_station_labels = st.checkbox("Label Stesen", value=True)
    with col_t2:
        show_bearing_dist = st.checkbox("Bearing & Jarak", value=True)

    stn_marker_size = st.sidebar.slider("Saiz Marker Stesen", 10, 40, 22)
    bd_text_size = st.sidebar.slider("Saiz Teks Bearing/Jarak", 8, 20, 12)
    poly_color = st.sidebar.color_picker("Warna Garisan/Poligon", "#0055FF")
    
    st.sidebar.divider()
    if st.sidebar.button("🚪 Log Keluar", use_container_width=True):
        del st.session_state["password_correct"]
        st.rerun()

    # --- MAIN CONTENT AREA ---
    if uploaded_data is None:
        st.info("👆 Sila muat naik fail CSV di panel sebelah kiri untuk memulakan.")
        sample_csv = "STN,E,N\n1,300.0,400.0\n2,350.0,400.0\n3,350.0,450.0\n4,300.0,450.0"
        st.download_button("📥 Muat Turun Contoh Format CSV", data=sample_csv, file_name="contoh_survey.csv", mime="text/csv")
        
    else:
        try:
            df_raw = pd.read_csv(uploaded_data)
            
            if not {'E', 'N', 'STN'}.issubset(df_raw.columns):
                st.error("❌ Ralat Format: Sila pastikan CSV anda mempunyai lajur 'STN', 'E', dan 'N'.")
            else:
                df_processed, area, perimeter, poly_coords, center_lat, center_lon = process_survey_data(df_raw, epsg_input)
                
                if df_processed is None:
                    st.error(f"❌ Ralat pengiraan koordinat: {center_lon}")
                else:
                    tab1, tab2 = st.tabs(["🗺️ Peta Interaktif", "📊 Jadual & Analisis Data"])
                    
                    with tab1:
                        col_m1, col_m2, col_m3 = st.columns(3)
                        col_m1.metric("Luas Lot", f"{area:,.3f} m²")
                        col_m2.metric("Perimeter Keseluruhan", f"{perimeter:,.3f} m")
                        col_m3.metric("Jumlah Stesen", len(df_processed))
                        
                        # EXTREME ZOOM FIX: max_zoom set to 30
                        m = folium.Map(location=[center_lat, center_lon], zoom_start=19, max_zoom=30)
                        
                        # Base Map Toggles applied here
                        if map_type == "Satelit (Google)":
                            # max_native_zoom allows deep digital zoom on satellite imagery
                            folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Google Satelit', max_zoom=30, max_native_zoom=21).add_to(m)
                        else:
                            folium.TileLayer('openstreetmap', name='Peta Jalan (OSM)', max_zoom=30, max_native_zoom=19).add_to(m)
                            
                        Fullscreen().add_to(m)
                        MiniMap(toggle_display=True).add_to(m)
                        
                        fg_survey = folium.FeatureGroup(name="Sempadan Lot").add_to(m)
                        
                        for i, row in df_processed.iterrows():
                            # Conditional Check: Only show if checkbox is ticked
                            if show_station_labels:
                                folium.Marker(
                                    location=[row['Latitud'], row['Longitud']],
                                    popup=f"<b>STESEN {row['Dari']}</b><br>E: {row['Easting (E)']:.3f}<br>N: {row['Northing (N)']:.3f}",
                                    icon=folium.DivIcon(html=f'<div style="background:red; color:white; border-radius:50%; width:{stn_marker_size}px; height:{stn_marker_size}px; line-height:{stn_marker_size}px; text-align:center; font-size:11px; font-weight:bold; border:2px solid white; transform:translate(-50%,-50%);">{row["Dari"]}</div>')
                                ).add_to(fg_survey)
                            
                            # Conditional Check: Only show if checkbox is ticked
                            if show_bearing_dist:
                                next_row = df_processed.iloc[(i + 1) % len(df_processed)]
                                mid_lat = (row['Latitud'] + next_row['Latitud']) / 2
                                mid_lon = (row['Longitud'] + next_row['Longitud']) / 2
                                
                                folium.Marker(
                                    location=[mid_lat, mid_lon],
                                    icon=folium.DivIcon(html=f'<div style="transform: translate(-50%, -50%) rotate({row["Teks_Angle"]}deg); text-align: center; width: 150px; pointer-events: none;"><span style="color:{poly_color}; font-weight:bold; font-size:{bd_text_size}px; text-shadow: -1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff;">{row["Bearing (DMS)"]}<br>{row["Jarak (m)"]}m</span></div>')
                                ).add_to(fg_survey)
                        
                        folium.Polygon(locations=poly_coords, color=poly_color, weight=3, fill=True, fill_opacity=0.15).add_to(fg_survey)
                        folium.LayerControl().add_to(m)
                        
                        st_folium(m, width="100%", height=600)
                    
                    with tab2:
                        st.subheader("Jadual Cerapan Bearing & Jarak")
                        display_df = df_processed[['Dari', 'Ke', 'Bearing (DMS)', 'Jarak (m)', 'Easting (E)', 'Northing (N)']]
                        st.dataframe(display_df, use_container_width=True, hide_index=True)
                        
                        st.divider()
                        st.subheader("💾 Eksport Data")
                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            csv_export = display_df.to_csv(index=False).encode('utf-8')
                            st.download_button(label="📄 Muat Turun Jadual (CSV)", data=csv_export, file_name="jadual_cerapan.csv", mime="text/csv", use_container_width=True)
                        
                        with col_e2:
                            geojson_str = convert_to_geojson(df_processed, area, perimeter)
                            st.download_button(label="🌍 Eksport ke QGIS (.geojson)", data=geojson_str, file_name="survey_lot.geojson", mime="application/json", use_container_width=True)

        except Exception as e:
            st.error(f"❌ Ralat membaca fail CSV: Pastikan format betul. Detail: {e}")