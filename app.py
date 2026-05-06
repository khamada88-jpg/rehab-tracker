import streamlit as st
from supabase import create_client, Client
import datetime
import pandas as pd
import altair as alt

# --- 1. Supabaseの初期化 ---
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- 2. セッション状態の初期化 ---
if "user" not in st.session_state:
    st.session_state.user = None
if "profile" not in st.session_state:
    st.session_state.profile = None

# --- 3. プロフィール情報の取得＆自動作成 ---
def get_profile(user_id, email):
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if res.data:
        return res.data[0]
    else:
        new_profile = {
            "id": user_id,
            "user_email": email,
            "user_name": email.split('@')[0],
            "role": "staff",
            "daily_goal": 17,
            "annual_goal": 3570
        }
        supabase.table("profiles").insert(new_profile).execute()
        return new_profile

# --- 4. ログイン機能 ---
def login():
    st.title("リハビリ単位管理システム")
    st.subheader("ログイン")
    with st.form("login_form"):
        email = st.text_input("メールアドレス")
        password = st.text_input("パスワード", type="password")
        if st.form_submit_button("ログイン"):
            try:
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user = response.user
                st.session_state.profile = get_profile(response.user.id, email)
                st.rerun()
            except Exception as e:
                st.error("ログイン失敗: 適切な情報を入力してください。")

# --- 5. スタッフ用画面（個人ダッシュボード） ---
def staff_view(profile):
    user_email = profile["user_email"]
    daily_goal = float(profile["daily_goal"])
    annual_goal = float(profile["annual_goal"])
    quota_month = annual_goal / 12
    
    st.title("単位入力・達成度確認")
    st.info(f"スタッフ: {profile['user_name']} さん / 1日目標: {int(daily_goal)} 単位")

    res = supabase.table("daily_units").select("*").eq("user_email", user_email).execute()
    df = pd.DataFrame(res.data)

    st.subheader("達成状況")
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        today = datetime.date.today()
        
        month_total = df[df["date"].dt.month == today.month]["unit_count"].sum()
        month_pct = (month_total / quota_month) * 100
        year_total = df["unit_count"].sum()
        year_pct = (year_total / annual_goal) * 100
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("今月の進捗率", f"{month_pct:.1f} %")
            st.caption(f"📈 {int(month_total)} / {int(quota_month)} 単位")
            st.progress(min(month_total / quota_month, 1.0))
        with col2:
            st.metric("年間の進捗率", f"{year_pct:.1f} %")
            st.caption(f"📊 {int(year_total)} / {int(annual_goal)} 単位")
            st.progress(min(year_total / annual_goal, 1.0))

        st.divider()
        st.subheader("単位取得の推移")
        daily_sum = df.groupby(df["date"].dt.date)["unit_count"].sum().reset_index()
        daily_sum.columns = ["date", "unit_count"]
        daily_sum["date"] = pd.to_datetime(daily_sum["date"])
        daily_sum["status"] = daily_sum["unit_count"].apply(lambda x: "目標達成" if x >= daily_goal else "未達成")
        
        bars = alt.Chart(daily_sum).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
            x=alt.X('date:T', axis=alt.Axis(format='%m/%d', title='日付', labelAngle=0)),
            y=alt.Y('unit_count:Q', title='単位数'),
            color=alt.Color('status:N', scale=alt.Scale(domain=['目標達成', '未達成'], range=['#4CAF50', '#FF5252']), legend=alt.Legend(title="状況")),
            tooltip=[alt.Tooltip('date:T', title='日付'), alt.Tooltip('unit_count:Q', title='取得単位'), alt.Tooltip('status:N', title='判定')]
        )
        line = alt.Chart(pd.DataFrame({'y': [daily_goal]})).mark_rule(color='black', strokeDash=[5, 5], size=2).encode(y='y')
        st.altair_chart(bars + line, use_container_width=True)
    else:
        st.info("データが登録されるとここにグラフが表示されます。")

    st.divider()
    with st.expander("今日の単位を入力する", expanded=True):
        with st.form("entry_form", clear_on_submit=True):
            d = st.date_input("日付", datetime.date.today())
            u = st.number_input("単位数", min_value=0, max_value=40, value=int(daily_goal))
            if st.form_submit_button("データを登録する"):
                try:
                    supabase.table("daily_units").insert({"user_email": user_email, "date": str(d), "unit_count": u}).execute()
                    st.success("正常に登録されました！")
                    st.rerun()
                except Exception as e:
                    st.error(f"登録エラー: {e}")

# --- 6. 管理者用画面（チーム統計） ---
def admin_view():
    st.title("チーム進捗管理（主任モード）")
    
    # データの統合取得
    units_data = supabase.table("daily_units").select("*").execute().data
    profs_data = supabase.table("profiles").select("*").execute().data
    
    units = pd.DataFrame(units_data)
    profs = pd.DataFrame(profs_data)

    if not units.empty and not profs.empty:
        units["date"] = pd.to_datetime(units["date"])
        today = datetime.date.today()

        # 今月の集計
        month_units = units[units["date"].dt.month == today.month]
        month_sum = month_units.groupby("user_email")["unit_count"].sum().reset_index()
        month_sum.columns = ["user_email", "今月の単位"]

        # 全期間（年間）の集計
        year_sum = units.groupby("user_email")["unit_count"].sum().reset_index()
        year_sum.columns = ["user_email", "累計単位"]

        # プロフィールと結合
        summary = pd.merge(profs, year_sum, on="user_email", how="left").fillna(0)
        summary = pd.merge(summary, month_sum, on="user_email", how="left").fillna(0)

        # 各種計算
        summary["今月の目標"] = (summary["annual_goal"] / 12).astype(int)
        summary["月進捗(%)"] = (summary["今月の単位"] / summary["今月の目標"] * 100).round(1)
        summary["年進捗(%)"] = (summary["累計単位"] / summary["annual_goal"] * 100).round(1)

        # 表の表示
        st.subheader("スタッフ別・達成状況一覧")
        display_df = summary[[
            "user_name", "今月の単位", "今月の目標", "月進捗(%)", 
            "累計単位", "annual_goal", "年進捗(%)"
        ]]
        display_df.columns = [
            "氏名", "今月の単位", "今月の目標", "月進捗(%)", 
            "累計単位", "年間目標", "年進捗(%)"
        ]
        
        st.dataframe(
            display_df.sort_values("月進捗(%)", ascending=False),
            hide_index=True,
            use_container_width=True
        )

        # チーム比較グラフ（今月の頑張りを可視化）
        st.subheader("スタッフ間・今月の取得単位比較")
        compare_chart = alt.Chart(summary).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5).encode(
            x=alt.X('今月の単位:Q', title='今月の取得単位'),
            y=alt.Y('user_name:N', title='スタッフ名', sort='-x'),
            color=alt.Color('user_name:N', legend=None)
        ).properties(height=300)
        
        st.altair_chart(compare_chart, use_container_width=True)
    else:
        st.warning("まだ集計対象となるデータが蓄積されていません。")

# --- 7. メインルーチン ---
if st.session_state.user is None:
    login()
else:
    prof = st.session_state.profile
    with st.sidebar:
        st.title("Menu")
        st.write(f"👤 {prof['user_name']} さん")
        st.write(f"🔑 権限: {prof['role']}")
        if st.button("ログアウト"):
            st.session_state.user = None
            st.session_state.profile = None
            st.rerun()
            
    if prof and prof["role"] == "admin":
        tab1, tab2 = st.tabs(["📊 個人ダッシュボード", "📋 チーム管理画面"])
        with tab1: staff_view(prof)
        with tab2: admin_view()
    elif prof:
        staff_view(prof)