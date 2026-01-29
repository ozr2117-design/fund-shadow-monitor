import streamlit as st
import requests
import time
import json
import pandas as pd # 记得在 requirements.txt 里加上 pandas
from datetime import datetime, timedelta
from github import Github

# === ⚙️ 基础配置 ===
st.set_page_config(
    page_title="全域鹰眼 (影子修正Pro)",
    page_icon="🦅",
    layout="centered"
)

# === 📊 核心数据定义 ===
MARKET_INDICES = {
    'sh000001': '上证指数',
    'sz399006': '创业板指',
    'hkHSTECH': '恒生科技'
}

# ⚠️ 请确保这里是真实的 6 位基金代码
FUND_CODES_MAP = {
    '摩根均衡C (梁鹏/周期)': '009968',
    '泰康新锐C (韩庆/成长)': '009340',
    '财通优选C (金梓才/AI)': '009354'
}

# === 🛠️ GitHub 数据库操作 ===

def get_repo():
    """连接 GitHub 仓库"""
    try:
        token = st.secrets["github_token"]
        username = st.secrets["github_username"]
        repo_name = st.secrets["repo_name"]
        g = Github(token)
        return g.get_user(username).get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub 连接失败: {e}")
        return None

def load_json(filename):
    """读取 JSON 文件"""
    repo = get_repo()
    if not repo: return {}, None
    try:
        content = repo.get_contents(filename)
        return json.loads(content.decoded_content.decode('utf-8')), content.sha
    except:
        return {}, None

def save_json(filename, data, sha, message):
    """写入 JSON 文件"""
    repo = get_repo()
    if repo:
        new_content = json.dumps(data, indent=4, ensure_ascii=False)
        if sha:
            repo.update_file(filename, message, new_content, sha)
        else:
            repo.create_file(filename, message, new_content)

def save_factor_history(date_str, new_factors_dict):
    """📈 记录仪：保存当天的系数快照"""
    history, sha = load_json('factor_history.json')
    if not isinstance(history, dict):
        history = {}
    history[date_str] = new_factors_dict
    save_json('factor_history.json', history, sha, f"Factor Log {date_str}")

# === 🕷️ 数据获取 (爬虫模块) ===

def get_realtime_price(stock_codes):
    """腾讯接口获取实时行情 (支持股票和ETF)"""
    if not stock_codes: return {}
    codes_str = ",".join(stock_codes)
    url = f"http://qt.gtimg.cn/q={codes_str}"
    
    try:
        r = requests.get(url, timeout=3)
        text = r.text
    except:
        return None

    price_data = {}
    parts = text.split(';')
    for part in parts:
        if '="' in part:
            try:
                key_raw = part.split('=')[0].strip()
                code = key_raw.split('_')[-1] 
                data = part.split('="')[1].strip('"').split('~')
                if len(data) > 30:
                    name = data[1].replace(" ", "")
                    current = float(data[3])
                    close = float(data[4])
                    pct = 0.0
                    if close > 0:
                        pct = ((current - close) / close) * 100
                    price_data[code] = {'name': name, 'change': pct}
            except:
                continue
    return price_data

def get_official_nav(fund_code):
    """
    🚀 升级版爬虫：直连天天基金(东财)官方接口
    """
    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=1"
    headers = {
        "Referer": "http://fund.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            res = r.json()
            if "Data" in res and "LSJZList" in res["Data"]:
                data_list = res["Data"]["LSJZList"]
                if len(data_list) > 0:
                    latest_data = data_list[0]
                    net_date = latest_data["FSRQ"]
                    growth_rate = latest_data["JZZZL"]
                    if growth_rate == "": return None, None
                    return float(growth_rate), net_date
    except:
        pass
    return None, None

# === 🚀 主程序 ===
def main():
    st.title("🦅 全域鹰眼 V5.0 (完全体)")

    funds_config, config_sha = load_json('funds.json')
    if not funds_config:
        st.stop()

    # ==========================================
    # 👇 侧边栏控制台
    # ==========================================
    with st.sidebar:
        st.header("🎮 控制台")
        mode = st.radio("选择模式", ["📡 实时监控", "💾 收盘存证", "⚖️ 晚间审计"])
        st.divider()

        # --- 💾 模式 B: 收盘存证 ---
        if mode == "💾 收盘存证":
            st.info("ℹ️ 最佳操作时间：收盘后 (15:00 - 23:59)。")
            if st.button("📸 立即存证"):
                with st.spinner("正在计算(含影子修正)..."):
                    snapshot_data = {}
                    all_codes = []
                    for f in funds_config.values():
                        for s in f['holdings']: all_codes.append(s['code'])
                        if 'shadow_code' in f: all_codes.append(f['shadow_code'])
                    
                    prices = get_realtime_price(list(set(all_codes)))
                    
                    if prices:
                        today_str = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
                        
                        for name, info in funds_config.items():
                            # 1. 持仓估值
                            val = 0
                            w = 0
                            for s in info['holdings']:
                                if s['code'] in prices:
                                    val += prices[s['code']]['change'] * s['weight']
                                    w += s['weight']
                            raw_holdings = val / w if w > 0 else 0
                            
                            # 2. 影子估值
                            shadow_est = 0
                            s_code = info.get('shadow_code')
                            s_weight = info.get('shadow_weight', 0)
                            if s_code and s_code in prices:
                                shadow_est = prices[s_code]['change']
                            
                            # 3. 混合计算
                            mixed_est = (raw_holdings * (1 - s_weight)) + (shadow_est * s_weight)
                            snapshot_data[name] = mixed_est
                        
                        history, hist_sha = load_json('history.json')
                        history[today_str] = snapshot_data
                        save_json('history.json', history, hist_sha, f"Snapshot {today_str}")
                        st.success(f"✅ {today_str} 影子版快照已保存！")
                        st.json(snapshot_data
