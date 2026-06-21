import streamlit as st
from supabase import create_client, Client
import datetime
import pandas as pd
import altair as alt

# --- 1. 設定：全員共通の簡易パスワード ---
COMMON_PASSWORD = "pass1234" # ← 修正済みの共通パスワード

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

# --- 4. プロフィールの取得＆更新 ---
def get_profile(user_id, email, exact_name=None):
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    if res.data:
        if exact_name and res.data[0]["user_name"] != exact_name:
            supabase.table("profiles").update({"user_name": exact_name}).eq("id", user_id).execute()
            res.data[0]["user_name"] = exact_name
        return res.data[0]
    else:
        name_to_use = exact_name if exact_name else email.split('@')[0]
        new_profile = {"id": user_id, "user_email": email, "user_name": name_to_use, "role": "staff", "daily_goal": 17, "annual_goal": 3570}
        supabase.table("profiles").insert(new_profile).execute()
        return new_profile

# --- 5. ログイン機能（名前選択式） ---
def login():
    st.title("リハビリ単位管理システム")
    st.subheader("名前を選んでログイン")

    STAFF_LIST = ["臺", "會田", "馬籠", "佐藤", "田熊", "濵田"]
    
    selected_name = st.selectbox("あなたのお名前は？", STAFF_LIST)

    if st.button(f"{selected_name} としてログイン"):
        try:
            res = supabase.table("profiles").select("user_email").eq("user_name", selected_name).execute()
            if res.data:
                selected_email = res.data[0]["user_email"]
                response = supabase.auth.sign_in_with_password({"email": selected_email, "password": COMMON_PASSWORD})
                st.session_state.user = response.user
                st.session_state.profile = get_profile(response.user.id, selected_email)
                st.rerun()
            else:
                st.warning(f"「{selected_name}」さんのアカウント紐づけが完了していません。下の『初回登録』から1度だけログインしてください。")
        except Exception as e:
            st.error("ログインに失敗しました。")
    
    st.divider()
    with st.expander("【初回のみ】アカウント紐づけ・管理者ログイン"):
        with st.form("manual_login"):
            st.write("初回のみ、ご自身の名前とメールアドレスを紐づけます。")
            init_name = st.selectbox("あなたの名前", STAFF_LIST)
            email = st.text_input("メールアドレス")
            password = st.text_input("パスワード", type="password")
            if st.form_submit_button("紐づけてログイン"):
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = response.user
                    st.session_state.profile = get_profile(response.user.id, email, exact_name=init_name)
                    st.success("紐づけが完了しました！")
                    st.rerun()
                except:
                    st.error("ログイン失敗。情報を確認してください。")

# --- 6. スタッフ用画面（個人ダッシュボード） ---
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
            st.metric("今月の進捗", f"{(month_total/quota_month*100):.1f} %", f"{int(month_total)} / {int(quota_month)} 単位")
            st.progress(min(month_total/quota_month, 1.0))
        with col2:
            st.metric("年間の進捗", f"{(year_total/annual_goal*100):.1f} %", f"{int(year_total)} / {int(annual_goal)} 単位")
            st.progress(min(year_total/annual_goal, 1.0))

        st.divider()
        st.subheader("📈 日々の単位推移")
        daily_sum = df.groupby(df["date"].dt.date)["unit_count"].sum().reset_index()
        daily_sum.columns = ["date", "unit_count"]
        daily_sum["date"] = pd.to_datetime(daily_sum["date"])
        daily_sum["status"] = daily_sum["unit_count"].apply(lambda x: "目標達成" if x >= daily_goal else "未達成")
        
        bars = alt.Chart(daily_sum).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
            x=alt.X('date:T', axis=alt.Axis(format='%m/%d', title='日付', labelAngle=0)),
            y=alt.Y('unit_count:Q', title='単位数'),
            color=alt.Color('status:N', scale=alt.Scale(domain=['目標達成', '未達成'], range=['#4CAF50', '#FF5252'])),
            tooltip=['date:T', 'unit_count']
        ).properties(height=250)
        line = alt.Chart(pd.DataFrame({'y': [daily_goal]})).mark_rule(color='black', strokeDash=[5, 5]).encode(y='y')
        st.altair_chart(bars + line, use_container_width=True)
        
        # ★追加機能：月別の実績振り返り
        st.subheader("📅 月別の実績")
        df["year_month"] = df["date"].dt.strftime("%Y/%m")
        monthly_sum = df.groupby("year_month")["unit_count"].sum().reset_index()
        monthly_chart = alt.Chart(monthly_sum).mark_bar(color='#1f77b4', cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
            x=alt.X('year_month:N', title='年月'),
            y=alt.Y('unit_count:Q', title='合計単位数'),
            tooltip=['year_month', 'unit_count']
        ).properties(height=250)
        st.altair_chart(monthly_chart, use_container_width=True)
        
    else:
        st.info("データが登録されるとここにグラフが表示されます。")

    with st.expander("今日の単位を入力 / 修正", expanded=True):
        with st.form("entry_form", clear_on_submit=True):
            d = st.date_input("日付", datetime.date.today())
            u = st.number_input("単位数", min_value=0, max_value=40, value=int(daily_goal))
            if st.form_submit_button("登録・修正する"):
                try:
                    existing = supabase.table("daily_units").select("*").eq("user_email", user_email).eq("date", str(d)).execute()
                    if existing.data:
                        supabase.table("daily_units").update({"unit_count": u}).eq("user_email", user_email).eq("date", str(d)).execute()
                        st.success(f"{d} の単位を {u} 単位に修正しました！")
                    else:
                        supabase.table("daily_units").insert({"user_email": user_email, "date": str(d), "unit_count": u}).execute()
                        st.success(f"{d} の単位を新規登録しました！")
                    st.rerun()
                except Exception as e:
                    st.error(f"登録エラー: {e}")

# --- 7. 管理者用画面（チーム統計） ---
def admin_view():
    st.title("チーム進捗管理（主任モード）")
    units_data = supabase.table("daily_units").select("*").execute().data
    profs_data = supabase.table("profiles").select("*").execute().data
    
    if units_data and profs_data:
        units = pd.DataFrame(units_data)
        profs = pd.DataFrame(profs_data)
        units["date"] = pd.to_datetime(units["date"])
        today = datetime.date.today()
        
        month_sum = units[units["date"].dt.month == today.month].groupby("user_email")["unit_count"].sum().reset_index()
        year_sum = units.groupby("user_email")["unit_count"].sum().reset_index()
        
        summary = pd.merge(profs, year_sum, on="user_email", how="left").fillna(0)
        summary = pd.merge(summary, month_sum, on="user_email", how="left", suffixes=('_year', '_month')).fillna(0)
        
        summary["今月の目標"] = (summary["annual_goal"] / 12).astype(int)
        summary["月進捗(%)"] = (summary["unit_count_month"] / summary["今月の目標"] * 100).round(1)
        summary["年進捗(%)"] = (summary["unit_count_year"] / summary["annual_goal"] * 100).round(1)
        
        display_df = summary[["user_name", "unit_count_month", "今月の目標", "月進捗(%)", "unit_count_year", "annual_goal", "年進捗(%)"]]
        display_df.columns = ["氏名", "今月の単位", "今月の目標", "月進捗(%)", "年間累計", "年間目標", "年進捗(%)"]
        
        st.subheader("📝 今月の達成状況一覧")
        st.dataframe(display_df.sort_values("月進捗(%)", ascending=False), use_container_width=True, hide_index=True)
        
        # ★追加機能：チーム全体の過去の月別実績表
        st.divider()
        st.subheader("📅 チーム全体の月別実績一覧")
        units["year_month"] = units["date"].dt.strftime("%Y/%m")
        team_monthly = units.groupby(["user_email", "year_month"])["unit_count"].sum().reset_index()
        team_monthly = pd.merge(team_monthly, profs[["user_email", "user_name"]], on="user_email", how="left")
        
        # スタッフを行、年月を列にした見やすい表を作成
        pivot_df = team_monthly.pivot(index="user_name", columns="year_month", values="unit_count").fillna(0).astype(int).reset_index()
        pivot_df = pivot_df.rename(columns={"user_name": "氏名"})
        st.dataframe(pivot_df, use_container_width=True, hide_index=True)
        
    else:
        st.info("集計データがありません。")

# --- 8. メインルーチン ---
if st.session_state.user is None:
    login()
else:
    prof = st.session_state.profile
    with st.sidebar:
        st.write(f"👤 {prof['user_name']} さん")
        if st.button("ログアウト"):
            st.session_state.user = None
            st.session_state.profile = None
            st.rerun()
            
    if prof and prof["role"] == "admin":
        tab1, tab2 = st.tabs(["📊 個人ダッシュボード", "📋 チーム管理画面"])
        with tab1: staff_view(prof)
        with tab2: admin_view()
    else:
        staff_view(prof)