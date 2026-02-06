import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import json
import sqlite3
import os
import io

# --- PAGE CONFIG ---
st.set_page_config(page_title="作業マニア", page_icon="⏱️", layout="wide")

# --- DATABASE SETUP ---
DB_NAME = "data.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Logs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS work_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            category TEXT,
            sub_category TEXT,
            duration_min REAL,
            memo TEXT,
            source TEXT,
            event_id TEXT UNIQUE
        )
    ''')
    
    # Categories Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            color TEXT,
            keywords TEXT
        )
    ''')
    
    # Sub Categories Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sub_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT,
            name TEXT,
            FOREIGN KEY (category_name) REFERENCES categories (name) ON DELETE CASCADE
        )
    ''')
    
    # Initial Data if empty
    cursor.execute('SELECT COUNT(*) FROM categories')
    if cursor.fetchone()[0] == 0:
        default_cats = [
            ("社内", "#E25D33", "社内, 準備", "社内"),
            ("全社関連", "#4351AF", "全社会議, HR関連", "全社, 会議"),
            ("社外", "#397E49", "社外, 準備", "社外, 商談"),
            ("研修", "#5EB47E", "MENTA, ツール説明", "研修, 勉強"),
            ("問い合わせ関連作業", "#EEC14C", "担当者, biz@", "問い合わせ"),
            ("受講者メール等個別対応", "#832DA4", "メール, 個別対応", "メール"),
            ("対面訪問", "#C3291C", "移動, 打ち合わせ", "訪問, 移動"),
            ("レポート送付", "#616161", "月次, イレギュラー", "レポート"),
            ("初動関連", "#D88277", "見積・申請, その他", "見積, 申請"),
            ("デフォルト", "#4599DF", "基盤メール返信, 基盤bot, 基盤レポート, Looker, 基盤コレタ", "")
        ]
        for name, color, subs, keywords in default_cats:
            cursor.execute('INSERT INTO categories (name, color, keywords) VALUES (?, ?, ?)', (name, color, keywords))
            for sub in subs.split(", "):
                cursor.execute('INSERT INTO sub_categories (category_name, name) VALUES (?, ?)', (name, sub))
                
    conn.commit()
    conn.close()

init_db()

# --- CUSTOM CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Noto+Sans+JP', sans-serif;
    }
    
    .stApp {
        background-color: #F8F9FA;
    }
    
    .timer-container {
        font-size: 5rem;
        font-weight: 700;
        text-align: center;
        color: #333;
        margin: 1rem 0;
        font-variant-numeric: tabular-nums;
    }
    
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stProgress > div > div > div > div {
        background-color: #4B7DC3;
    }
    
    .dashboard-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---

def format_time(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def load_categories():
    conn = get_db_connection()
    df_cats = pd.read_sql_query('SELECT * FROM categories', conn)
    df_subs = pd.read_sql_query('SELECT * FROM sub_categories', conn)
    conn.close()
    
    categories = []
    for _, cat in df_cats.iterrows():
        categories.append({
            "name": cat["name"],
            "color": cat["color"],
            "keywords": [k.strip() for k in str(cat["keywords"]).split(",") if k.strip()],
            "subs": df_subs[df_subs["category_name"] == cat["name"]]["name"].tolist()
        })
    return categories

def save_log(entry):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO work_logs (timestamp, category, sub_category, duration_min, memo, source, event_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (entry["Date"], entry["Category"], entry["SubCategory"], entry["Duration"], entry["Memo"], entry["Source"], entry.get("EventID")))
    conn.commit()
    conn.close()

def load_logs():
    conn = get_db_connection()
    df = pd.read_sql_query('SELECT * FROM work_logs ORDER BY timestamp DESC', conn)
    conn.close()
    return df

def save_category_setting(name, color, subs, keywords):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE categories SET color = ?, keywords = ? WHERE name = ?', (color, keywords, name))
    cursor.execute('DELETE FROM sub_categories WHERE category_name = ?', (name,))
    for sub in subs:
        cursor.execute('INSERT INTO sub_categories (category_name, name) VALUES (?, ?)', (name, sub))
    conn.commit()
    conn.close()

# --- SESSION STATE INITIALIZATION ---
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.timer_running = False
    st.session_state.start_time = None
    st.session_state.current_category = None
    st.session_state.current_sub_category = None
    st.session_state.elapsed_seconds = 0
    st.session_state.data_loaded = False

# --- UI COMPONENTS ---

def sidebar():
    with st.sidebar:
        st.image("https://img.icons8.com/clouds/100/000000/stopwatch.png", width=100)
        st.title("作業マニア")
        st.info("🏠 ローカルDB運用中")
        
        st.divider()
        st.write("Ver 2.0.0 (SQLite Edition)")

def record_tab():
    st.title("🚀 作業記録")
    categories = load_categories()
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
        st.subheader("⏱️ タイマー")
        
        if st.session_state.timer_running:
            elapsed = time.time() - st.session_state.start_time
            st.session_state.elapsed_seconds = elapsed
        
        st.markdown(f'<div class="timer-container">{format_time(int(st.session_state.elapsed_seconds))}</div>', unsafe_allow_html=True)
        
        if st.session_state.timer_running:
            st.progress(min(int(st.session_state.elapsed_seconds % 60) / 60, 1.0))
            st.caption(f"計測中: {st.session_state.current_category} / {st.session_state.current_sub_category}")
            if st.button("⏹️ 終了して保存", type="primary", use_container_width=True):
                st.session_state.timer_running = False
                st.session_state.needs_save = True
        else:
            st.info("カテゴリーを選択して計測を開始してください。")
        st.markdown('</div>', unsafe_allow_html=True)

        if hasattr(st.session_state, 'needs_save') and st.session_state.needs_save:
            with st.form("save_form"):
                memo = st.text_input("内容（メモ）", placeholder="何を行いましたか？")
                if st.form_submit_button("保存"):
                    entry = {
                        "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Category": st.session_state.current_category,
                        "SubCategory": st.session_state.current_sub_category,
                        "Duration": round(st.session_state.elapsed_seconds / 60, 2),
                        "Memo": memo,
                        "Source": "Manual"
                    }
                    save_log(entry)
                    st.success("保存しました。")
                    st.session_state.elapsed_seconds = 0
                    st.session_state.needs_save = False
                    st.rerun()

    with col2:
        st.subheader("カテゴリー")
        cols = st.columns(2)
        for idx, cat in enumerate(categories):
            with cols[idx % 2]:
                if st.button(f"● {cat['name']}", key=f"cat_{idx}", use_container_width=True):
                    st.session_state.selected_cat_idx = idx
        
        if 'selected_cat_idx' in st.session_state:
            selected_cat = categories[st.session_state.selected_cat_idx]
            st.divider()
            st.markdown(f"### {selected_cat['name']} の小カテゴリー")
            sub_cols = st.columns(3)
            for s_idx, sub in enumerate(selected_cat['subs']):
                with sub_cols[s_idx % 3]:
                    if st.button(sub, key=f"sub_{s_idx}", use_container_width=True):
                        if not st.session_state.timer_running:
                            st.session_state.timer_running = True
                            st.session_state.start_time = time.time()
                            st.session_state.current_category = selected_cat['name']
                            st.session_state.current_sub_category = sub
                            st.rerun()

def analysis_tab():
    st.title("📊 稼働分析")
    
    df = load_logs()
    categories = load_categories()
    
    if df.empty:
        st.info("データがありません。作業を記録してください。")
        return
        
    color_map = {cat['name']: cat['color'] for cat in categories}
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("カテゴリー別時間配分")
        cat_counts = df.groupby('category')['duration_min'].sum().reset_index()
        fig_pie = px.pie(
            cat_counts, values='duration_min', names='category', 
            hole=.3, color='category', color_discrete_map=color_map
        )
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with col2:
        st.subheader("日次稼働推移")
        df['Date_only'] = pd.to_datetime(df['timestamp']).dt.date
        daily_cat = df.groupby(['Date_only', 'category'])['duration_min'].sum().reset_index()
        
        fig_bar = px.bar(
            daily_cat, x='Date_only', y='duration_min', color='category', 
            barmode='stack', color_discrete_map=color_map
        )
        fig_bar.update_layout(xaxis_title="日付", yaxis_title="作業時間 (分)")
        st.plotly_chart(fig_bar, use_container_width=True)
    
    st.divider()
    st.subheader("データ書き出し")
    
    # CSV Export
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 全データをCSVとしてダウンロード",
        data=csv,
        file_name=f'work_logs_{datetime.now().strftime("%Y%m%d")}.csv',
        mime='text/csv',
    )
    
    st.divider()
    st.subheader("作業履歴 (最新20件)")
    st.dataframe(df.head(20), use_container_width=True)

def settings_tab():
    st.title("⚙️ 設定")
    categories = load_categories()
    
    st.markdown("カテゴリーの名前や色を編集できます。データは即座にデータベースへ反映されます。")

    for i, cat in enumerate(categories):
        with st.expander(f"{cat['name']} ({cat['color']})"):
            c1, c2 = st.columns(2)
            with c1:
                new_color = st.color_picker("カラー", value=cat['color'], key=f"edit_color_{i}")
                # We won't allow renaming the ID directly easily to avoid foreign key issues in this simple UI
                st.caption(f"大カテゴリー名: {cat['name']}")
            with c2:
                new_subs_text = st.text_area("小カテゴリー (カンマ区切り)", value=", ".join(cat['subs']), key=f"edit_subs_{i}")
                new_keys_text = st.text_input("同期キーワード (カンマ区切り)", value=", ".join(cat['keywords']), key=f"edit_keys_{i}")
            
            if st.button("このカテゴリーを更新", key=f"update_db_{i}"):
                new_subs = [s.strip() for s in new_subs_text.split(",") if s.strip()]
                save_category_setting(cat['name'], new_color, new_subs, new_keys_text)
                st.success(f"{cat['name']} を更新しました。")
                st.rerun()

# --- MAIN APP ---

def main():
    sidebar()
    
    tab1, tab2, tab3 = st.tabs(["🚀 記録", "📊 分析", "⚙️ 設定"])
    
    with tab1:
        record_tab()
    with tab2:
        analysis_tab()
    with tab3:
        settings_tab()

    if st.session_state.timer_running:
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    main()
