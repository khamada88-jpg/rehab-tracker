import streamlit as st
from supabase import create_client, Client
import datetime
import pandas as pd
import altair as alt

# --- 1. 設定：全員共通の簡易パスワード ---
COMMON_PASSWORD = "password123" # ← Supabaseで設定した共通パスワード

# --- 2. Supabaseの初期化 ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- 3. セッション状態の初期化 ---
if "user" not in st.session_state:
    st.session_state.user = None
if "profile" not in st.session_state:
    st.session_state.profile = None

# プロフィール取得
def get_profile(user_id, email):
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if res.data:
        return res.data[0]
    else:
        new_profile = {"id": user_id, "user_email": email, "user_name": email.split('@')[0], "role": "staff", "daily_goal": 17, "annual_goal": 3570}
        supabase.table("profiles").insert(new_profile).execute()
        return new_profile

# --- 4. ログイン機能（名前選択式） ---
def login():
    st.title("リハビリ単位管理システム")
    st.subheader("名前を選んでログイン")

    # ご指定いただいたスタッフリスト
    STAFF_LIST = ["臺", "會田", "馬籠", "佐藤", "田熊", "濵田"]
    
    selected_name = st.selectbox("あなたのお名前は？", STAFF_LIST)

    if st.button(f"{selected_name} としてログイン"):
        try:
            # データベースから、選択された名前に一致するメールアドレスを探す
            res = supabase.table("profiles").select("user_email").eq("user_name", selected_name).execute()
            if res.data:
                selected_email = res.data[0]["user_email"]
                # 共通パスワードでログイン実行
                response = supabase.auth.sign_in_with_password({"email": selected_email, "password": COMMON_PASSWORD})
                st.session_state.user = response.user
                st.session_state.profile = get_profile(response.user.id, selected_email)
                st.rerun()
            else:
                st.warning(f"まだ「{selected_name}」さんの名簿登録が完了していません。下の『初回登録』から一度ログインしてください。")
        except Exception as e:
            st.error("ログインに失敗しました。パスワード設定などを確認してください。")
    
    st.divider()
    with st.expander("【初回のみ】メールアドレスで登録・管理者ログイン"):
        with st.form("manual_login"):
            email = st.text_input("メールアドレス")
            password = st.text_input("パスワード", type="password")
            if st.form_submit_button("ログイン"):
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = response.user
                    st.session_state.profile = get_profile(response.user.id, email)
                    st.rerun()
                except:
                    st.error("ログイン失敗。情報を確認してください。")

# --- 5. スタッフ用画面（個人ダッシュボード） ---
def staff_view(profile):
    user_email = profile["user_email"]
    daily_goal = float(profile["daily_goal"])
    annual_goal = float(profile["annual_goal"])
    quota_month = annual_goal / 12
    
    st.title(f"{profile['user_name']} さんの進捗")
    
    res = supabase.table("daily_units").select("*").eq("user_email", user_email).execute()
    df = pd.DataFrame(res.data)

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        month_total = df[df["date"].dt.month == datetime.date.today().month]["unit_count"].sum()
        year_total = df["unit_count"].sum()
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("今月の進捗", f"{(month_total/quota_month*100):.1f} %")
            st.progress(min(month_total/quota_month, 1.0))
        with col2:
            st.metric("年間の進捗", f"{(year_total/annual_goal*100):.1f} %")
            st.progress(min(year_total/annual_goal, 1.0))

        st.divider()
        daily_sum = df.groupby(df["date"].dt.date)["unit_count"].sum().reset_index()
        daily_sum.columns = ["date", "unit_count"]
        daily_sum["date"] = pd.to_datetime(daily_sum["date"])
        daily_sum["status"] = daily_sum["unit_count"].apply(lambda x: "目標達成" if x >= daily_goal else "未達成")
        
        bars = alt.Chart(daily_sum).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
            x=alt.X('date:T', axis=alt.Axis(format='%m/%d', title='日付', labelAngle=0)),
            y=alt.Y('unit_count:Q', title='単位数'),
            color=alt.Color('status:N', scale=alt.Scale(domain=['目標達成', '未達成'], range=['#4CAF50', '#FF5252']))
        ).properties(height=300)
        line = alt.Chart(pd.DataFrame({'y': [daily_goal]})).mark_rule(color='black', strokeDash=[5, 5]).encode(y='y')
        st.altair_chart(bars + line, use_container_width=True)

    with st.expander("今日の単位を入力", expanded=True):
        with st.form("entry_form", clear_on_submit=True):
            d = st.date_input("日付", datetime.date.today())
            u = st.number_input("単位数", min_value=0, max_value=40, value=int(daily_goal))
            if st.form_submit_button("登録"):
                supabase.table("daily_units").insert({"user_email": user_email, "date": str(d), "unit_count": u}).execute()
                st.success("登録完了！")
                st.rerun()

# --- 6. 管理者用画面（チーム統計） ---
def admin_view():
    st.title("チーム進捗管理")
    units_data = supabase.table("daily_units").select("*").execute().data
    profs_data = supabase.table("profiles").select("*").execute().data
    
    if units_data and profs_data:
        units = pd.DataFrame(units_data)
        profs = pd.DataFrame(profs_data)
        units["date"] = pd.to_datetime(units["date"])
        
        month_sum = units[units["date"].dt.month == datetime.date.today().month].groupby("user_email")["unit_count"].sum().reset_index()
        year_sum = units.groupby("user_email")["unit_count"].sum().reset_index()
        
        summary = pd.merge(profs, year_sum, on="user_email", how="left").fillna(0)
        summary = pd.merge(summary, month_sum, on="user_email", how="left", suffixes=('_year', '_month')).fillna(0)
        
        st.dataframe(summary[["user_name", "unit_count_month", "unit_count_year"]].rename(columns={"user_name":"氏名", "unit_count_month":"今月", "unit_count_year":"累計"}), use_container_width=True, hide_index=True)
    else:
        st.info("集計データがありません。")

# --- 7. メインルーチン ---
if st.session_state.user is None:
    login()
else:
    prof = st.session_state.profile
    with st.sidebar:
        st.write(f"👤 {prof['user_name']} さん")
        if st.button("ログアウト"):
            st.session_state.user = None
            st.rerun()
            
    if prof and prof["role"] == "admin":
        t1, t2 = st.tabs(["📊 個人", "📋 チーム"])
        with t1: staff_view(prof)
        with tab2 if 'tab2' in locals() else t2: admin_view()
    else:
        staff_view(prof)