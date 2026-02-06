import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import json
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os

# --- PAGE CONFIG ---
st.set_page_config(page_title="作業マニア", page_icon="⏱️", layout="wide")

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
    
    /* Header Style */
    .main-header {
        background-color: #4B7DC3;
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* Timer Display */
    .timer-container {
        font-size: 5rem;
        font-weight: 700;
        text-align: center;
        color: #333;
        margin: 1rem 0;
        font-variant-numeric: tabular-nums;
    }
    
    /* Category Button Styles */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .category-btn {
        width: 100%;
        margin-bottom: 0.5rem;
    }
    
    /* Progress Bar Theme */
    .stProgress > div > div > div > div {
        background-color: #4B7DC3;
    }
    
    /* Dashboard Cards */
    .dashboard-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTS & DEFAULTS ---
SPREADSHEET_ID = "1icojXZtz6tXwlJ7fDzdgW2Ditlx1oudq7inUyrGNL8o"

DEFAULT_CATEGORIES = [
    {"name": "社内", "color": "#E25D33", "subs": ["社内", "準備"], "keywords": ["社内"]},
    {"name": "全社関連", "color": "#4351AF", "subs": ["全社会議", "HR関連"], "keywords": ["全社", "会議"]},
    {"name": "社外", "color": "#397E49", "subs": ["社外", "準備"], "keywords": ["社外", "商談"]},
    {"name": "研修", "color": "#5EB47E", "subs": ["MENTA", "ツール説明"], "keywords": ["研修", "勉強"]},
    {"name": "問い合わせ関連作業", "color": "#EEC14C", "subs": ["担当者", "biz@"], "keywords": ["問い合わせ"]},
    {"name": "受講者メール等個別対応", "color": "#832DA4", "subs": ["メール", "個別対応"], "keywords": ["メール"]},
    {"name": "対面訪問", "color": "#C3291C", "subs": ["移動", "打ち合わせ"], "keywords": ["訪問", "移動"]},
    {"name": "レポート送付", "color": "#616161", "subs": ["月次", "イレギュラー"], "keywords": ["レポート"]},
    {"name": "初動関連", "color": "#D88277", "subs": ["見積・申請", "その他"], "keywords": ["見積", "申請"]},
    {"name": "デフォルト", "color": "#4599DF", "subs": ["基盤メール返信", "基盤bot", "基盤レポート", "Looker", "基盤コレタ"], "keywords": []}
]

# --- SESSION STATE INITIALIZATION ---
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.timer_running = False
    st.session_state.start_time = None
    st.session_state.current_category = None
    st.session_state.current_sub_category = None
    st.session_state.categories = DEFAULT_CATEGORIES
    st.session_state.logs = [] # Local cache to speed up UI
    st.session_state.elapsed_seconds = 0
    st.session_state.data_loaded = False

# --- HELPER FUNCTIONS ---

def get_google_creds():
    """Manage Google OAuth2 credentials."""
    creds = None
    # Check if token exists in session state
    if 'token' in st.session_state:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(st.session_state.token))
        except:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Load secrets for OAuth flow
            try:
                client_config = {
                    "web": {
                        "client_id": st.secrets["google"]["client_id"],
                        "client_secret": st.secrets["google"]["client_secret"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                }
                flow = InstalledAppFlow.from_client_config(
                    client_config, 
                    scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/calendar.readonly']
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                st.error(f"認証エラー: {e}")
                return None
        
        # Save token
        st.session_state.token = creds.to_json()
    
    return creds

def get_sheets_service():
    creds = get_google_creds()
    if creds:
        return gspread.authorize(creds)
    return None

def save_log_to_sheets(entry):
    """Save a single log entry to the Google Sheet."""
    try:
        client = get_sheets_service()
        if client:
            sheet = client.open_by_key(SPREADSHEET_ID).worksheet("logs")
            row = [
                entry.get("Date"), 
                entry.get("Category"), 
                entry.get("SubCategory"), 
                entry.get("Duration"), 
                entry.get("Memo"), 
                entry.get("Source"),
                entry.get("EventID", "")
            ]
            sheet.append_row(row)
            return True
    except Exception as e:
        st.error(f"Spreadsheet保存エラー: {e}")
    return False

def load_logs_from_sheets():
    try:
        client = get_sheets_service()
        if client:
            sheet = client.open_by_key(SPREADSHEET_ID).worksheet("logs")
            data = sheet.get_all_records()
            return pd.DataFrame(data)
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
    return pd.DataFrame()

def save_settings_to_sheets():
    try:
        client = get_sheets_service()
        if client:
            try:
                sheet = client.open_by_key(SPREADSHEET_ID).worksheet("settings")
            except gspread.exceptions.WorksheetNotFound:
                # Create if not exists
                gc = client.open_by_key(SPREADSHEET_ID)
                sheet = gc.add_worksheet(title="settings", rows="100", cols="20")
            
            sheet.clear()
            # Headers
            sheet.update('A1', [['CategoryName', 'Color', 'SubCategories', 'Keywords']])
            rows = []
            for cat in st.session_state.categories:
                rows.append([
                    cat['name'], 
                    cat['color'], 
                    ",".join(cat['subs']), 
                    ",".join(cat['keywords'])
                ])
            sheet.append_rows(rows)
            st.success("設定をスプレッドシートに保存しました。")
    except Exception as e:
        st.error(f"設定保存エラー: {e}")

def load_settings_from_sheets():
    try:
        client = get_sheets_service()
        if client:
            sheet = client.open_by_key(SPREADSHEET_ID).worksheet("settings")
            data = sheet.get_all_records()
            if data:
                categories = []
                for row in data:
                    categories.append({
                        "name": row['CategoryName'],
                        "color": row['Color'],
                        "subs": [s.strip() for s in str(row['SubCategories']).split(",") if s.strip()],
                        "keywords": [k.strip() for k in str(row['Keywords']).split(",") if k.strip()]
                    })
                st.session_state.categories = categories
    except Exception:
        pass

def sync_calendar():
    """Fetch events from Google Calendar and categorize them."""
    creds = get_google_creds()
    if not creds: return
    
    try:
        service = build('calendar', 'v3', credentials=creds)
        start_of_day = datetime.combine(datetime.today(), datetime.min.time()).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary', timeMin=start_of_day,
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            st.info('カレンダーに予定が見つかりませんでした。')
            return

        existing_df = load_logs_from_sheets()
        existing_event_ids = set()
        if not existing_df.empty and 'EventID' in existing_df.columns:
            existing_event_ids = set(existing_df['EventID'].astype(str).tolist())

        new_entries = []
        for event in events:
            eid = event.get('id')
            if eid in existing_event_ids: continue
                
            title = event.get('summary', '')
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            if not start or not end: continue
            
            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            duration_min = (end_dt - start_dt).total_seconds() / 60
            
            matched_cat = "デフォルト"
            matched_sub = "未分類"
            for cat in st.session_state.categories:
                for kw in cat['keywords']:
                    if kw and kw.lower() in title.lower():
                        matched_cat = cat['name']
                        matched_sub = cat['subs'][0] if cat['subs'] else "未分類"
                        break
            
            entry = {
                "Date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Category": matched_cat,
                "SubCategory": matched_sub,
                "Duration": round(duration_min, 2),
                "Memo": title,
                "Source": "Calendar",
                "EventID": eid
            }
            if save_log_to_sheets(entry):
                new_entries.append(entry)
        
        if new_entries:
            st.success(f"{len(new_entries)}件の新しいカレンダー予定を同期しました。")
            st.rerun()
        else:
            st.info("新しい予定はありませんでした。")
    except Exception as e:
        st.error(f"カレンダー同期エラー: {e}")

# --- UI COMPONENTS ---

def sidebar_auth():
    with st.sidebar:
        st.image("https://img.icons8.com/clouds/100/000000/stopwatch.png", width=100)
        st.title("作業マニア")
        st.markdown("### 認証ステータス")
        
        if 'token' in st.session_state:
            st.success("✅ Google連携中")
            if st.button("🔄 再認証 / ログアウト"):
                del st.session_state.token
                st.rerun()
        else:
            st.info("🔓 未認証")
            if st.button("Google連携を開始"):
                get_google_creds()
                st.rerun()
        
        st.divider()
        if st.button("📋 最新データを読み込み"):
            load_settings_from_sheets()
            st.session_state.logs = load_logs_from_sheets().to_dict('records')
            st.success("最新データを取得しました。")
        
        st.divider()
        st.write("Ver 1.0.0")

def record_tab():
    st.title("🚀 作業記録")
    
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
                    if save_log_to_sheets(entry):
                        st.session_state.logs.append(entry)
                        st.success("保存しました。")
                    
                    st.session_state.elapsed_seconds = 0
                    st.session_state.needs_save = False
                    st.rerun()

    with col2:
        st.subheader("カテゴリー")
        cols = st.columns(2)
        for idx, cat in enumerate(st.session_state.categories):
            with cols[idx % 2]:
                btn_label = f"● {cat['name']}"
                if st.button(btn_label, key=f"cat_{idx}", use_container_width=True):
                    st.session_state.selected_cat_idx = idx
        
        if 'selected_cat_idx' in st.session_state:
            selected_cat = st.session_state.categories[st.session_state.selected_cat_idx]
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

    st.divider()
    st.subheader("📅 カレンダー同期")
    if st.button("Googleカレンダーから取得"):
        sync_calendar()


def analysis_tab():
    st.title("📊 稼働分析")
    
    # Reload logs from sheets if possible
    df = load_logs_from_sheets()
    
    if df.empty:
        st.info("データがありません。作業を記録してください。")
        return
        
    # Ensure color mapping
    color_map = {cat['name']: cat['color'] for cat in st.session_state.categories}
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("カテゴリー別時間配分")
        cat_counts = df.groupby('Category')['Duration'].sum().reset_index()
        fig_pie = px.pie(
            cat_counts, values='Duration', names='Category', 
            hole=.3, color='Category', color_discrete_map=color_map
        )
        st.plotly_chart(fig_pie, use_container_width=True)
        
    with col2:
        st.subheader("日次稼働推移")
        # Pre-process dates
        df['Date_only'] = pd.to_datetime(df['Date']).dt.date
        daily_cat = df.groupby(['Date_only', 'Category'])['Duration'].sum().reset_index()
        
        fig_bar = px.bar(
            daily_cat, x='Date_only', y='Duration', color='Category', 
            barmode='stack', color_discrete_map=color_map
        )
        fig_bar.update_layout(xaxis_title="日付", yaxis_title="作業時間 (分)")
        st.plotly_chart(fig_bar, use_container_width=True)
    
    st.divider()
    st.subheader("最近のログ")
    st.dataframe(df.sort_values('Date', ascending=False).head(20), use_container_width=True)

def settings_tab():
    st.title("⚙️ 設定")
    st.markdown("設定内容はスプレッドシートの `settings` シートに保存されます。")
    
    if st.button("💾 全ての設定をシートに保存", type="primary"):
        save_settings_to_sheets()

    for i, cat in enumerate(st.session_state.categories):
        with st.expander(f"{cat['name']} ({cat['color']})"):
            c1, c2 = st.columns(2)
            with c1:
                new_name = st.text_input("大カテゴリー名", value=cat['name'], key=f"edit_name_{i}")
                new_color = st.color_picker("カラー", value=cat['color'], key=f"edit_color_{i}")
            with c2:
                new_subs = st.text_area("小カテゴリー (カンマ区切り)", value=", ".join(cat['subs']), key=f"edit_subs_{i}")
                new_keys = st.text_input("同期キーワード (カンマ区切り)", value=", ".join(cat['keywords']), key=f"edit_keys_{i}")
            
            if st.button("更新", key=f"update_local_{i}"):
                st.session_state.categories[i] = {
                    "name": new_name,
                    "color": new_color,
                    "subs": [s.strip() for s in new_subs.split(",") if s.strip()],
                    "keywords": [k.strip() for k in new_keys.split(",") if k.strip()]
                }
                st.toast(f"{new_name} を一時更新しました。保存ボタンで確定してください。")

# --- MAIN APP ---

def main():
    # Initial load from sheets if possible
    if not st.session_state.data_loaded:
        if 'token' in st.session_state:
            load_settings_from_sheets()
            st.session_state.data_loaded = True

    sidebar_auth()
    
    tab1, tab2, tab3 = st.tabs(["🚀 記録", "📊 分析", "⚙️ 設定"])
    
    with tab1:
        record_tab()
    with tab2:
        analysis_tab()
    with tab3:
        settings_tab()

    # Periodic Rerun if timer is running
    if st.session_state.timer_running:
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    main()
