import streamlit as st
import requests
import time
import json
from datetime import datetime, timedelta
from github import Github

# === ⚙️ 基础配置 ===
st.set_page_config(
    page_title="全域鹰眼 (影子修正版)",
    page_icon="🦅",
    layout="centered"
)

# === 📊 核心数据定义 ===
MARKET_INDICES = {
    'sh000001': '上证指数',
    'sz399006': '创业板指',
    'hkHSTECH': '恒生科技'
}

# ⚠️⚠️⚠️ 请填入真实的 6 位基金代码 (用于晚间抓取官方净值)
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

# === 🕷️ 数据获取 ===

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
    """第三方接口获取官方净值"""
    url = f"https://api.doctorxiong.club/v1/fund/detail?code={fund_code}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            res = r.json()
            if res['code'] == 200:
                data = res['data']
                return float(data['lastDayGrowth']), data['netWorthDate']
    except:
        pass
    return None, None

# === 🚀 主程序 ===
def main():
    st.title("🦅 全域鹰眼 V5.0 (影子版)")

    funds_config, config_sha = load_json('funds.json')
    if not funds_config:
        st.stop()

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
                    # 收集所有代码
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
                            
                            # 3. 混合计算 (不乘 factor，存原始混合值)
                            mixed_est = (raw_holdings * (1 - s_weight)) + (shadow_est * s_weight)
                            snapshot_data[name] = mixed_est
                        
                        history, hist_sha = load_json('history.json')
                        history[today_str] = snapshot_data
                        save_json('history.json', history, hist_sha, f"Snapshot {today_str}")
                        st.success(f"✅ {today_str} 影子版快照已保存！")
                        st.json(snapshot_data)
                    else:
                        st.error("行情获取失败")

        # --- ⚖️ 模式 C: 晚间审计 ---
        elif mode == "⚖️ 晚间审计":
            st.info("ℹ️ 对比'昨日混合快照'与'官方净值'，自动修正系数。")
            history, hist_sha = load_json('history.json')
            if history:
                last_date = sorted(history.keys())[-1]
                st.markdown(f"📅 审计目标：**{last_date}**")
                
                if st.button("🚀 开始审计"):
                    updates_log = []
                    need_save = False
                    progress_bar = st.progress(0)
                    
                    for idx, (name, info) in enumerate(funds_config.items()):
                        mixed_est = history[last_date].get(name)
                        code = FUND_CODES_MAP.get(name)
                        
                        if mixed_est is not None and code:
                            off_pct, off_date = get_official_nav(code)
                            if off_date and off_date >= last_date:
                                if mixed_est != 0:
                                    perfect_factor = off_pct / mixed_est
                                    old_factor = info['factor']
                                    # 影子版减震器 (保留85%旧系数，更稳健)
                                    new_factor = (old_factor * 0.85) + (perfect_factor * 0.15)
                                    
                                    funds_config[name]['factor'] = round(new_factor, 4)
                                    updates_log.append(f"✅ {name}: {old_factor} -> {new_factor:.4f}")
                                    need_save = True
                            else:
                                updates_log.append(f"⏳ {name}: 官方未更新")
                        progress_bar.progress((idx + 1) / len(funds_config))
                    
                    if need_save:
                        save_json('funds.json', funds_config, config_sha, f"Audit Update {last_date}")
                        st.balloons()
                        st.success("系数已修正，系统即将重启...")
                        time.sleep(3)
                        st.rerun()
                    else:
                        st.text("\n".join(updates_log))
            else:
                st.error("无历史快照")

    # === 📡 模式 A: 实时监控 (含影子修正) ===
    if mode == "📡 实时监控":
        placeholder = st.empty()
        
        all_codes = list(MARKET_INDICES.keys())
        for f in funds_config.values():
            for s in f['holdings']: all_codes.append(s['code'])
            if 'shadow_code' in f: all_codes.append(f['shadow_code'])
        all_codes = list(set(all_codes))
        
        while True:
            with placeholder.container():
                market_data = get_realtime_price(all_codes)
                if not market_data:
                    st.warning("📡 连接卫星中...")
                    time.sleep(2)
                    continue
                
                # 1. 大盘看板
                bj_time = datetime.utcnow() + timedelta(hours=8)
                st.caption(f"最后刷新: {bj_time.strftime('%H:%M:%S')} (影子修正版)")
                st.subheader("📈 市场风向")
                col1, col2, col3 = st.columns(3)
                cols = [col1, col2, col3]
                for i, code in enumerate(MARKET_INDICES):
                    info = market_data.get(code)
                    if info: cols[i].metric(MARKET_INDICES[code], f"{info['change']:.2f}%")
                st.divider()

                # 2. 基金卡片 (V5.0 核心展示)
                for fund_name, fund_info in funds_config.items():
                    holdings = fund_info['holdings']
                    factor = fund_info.get('factor', 1.0)
                    
                    # 读取影子配置
                    shadow_code = fund_info.get('shadow_code')
                    shadow_w = fund_info.get('shadow_weight', 0.0)
                    
                    # 算持仓
                    total_val = 0
                    total_w = 0
                    top_stocks = []
                    for s in holdings:
                        info = market_data.get(s['code'])
                        if info:
                            total_val += info['change'] * s['weight']
                            total_w += s['weight']
                            if len(top_stocks) < 5:
                                top_stocks.append({"股票": info['name'], "涨跌": f"{info['change']:+.2f}%"})
                    
                    raw_holdings = total_val / total_w if total_w > 0 else 0
                    
                    # 算影子
                    shadow_est = 0
                    shadow_name = "未配置"
                    if shadow_code and shadow_code in market_data:
                        shadow_est = market_data[shadow_code]['change']
                        shadow_name = market_data[shadow_code]['name']
                    
                    # 混合计算
                    mixed_est = (raw_holdings * (1 - shadow_w)) + (shadow_est * shadow_w)
                    final_est = mixed_est * factor
                    
                    color = "red" if final_est > 0 else "green"
                    emoji = "🔥" if final_est > 0 else "❄️"
                    
                    with st.expander(f"{emoji} {fund_name.split('(')[0]} | {final_est:+.2f}%"):
                        st.markdown(f"**最终估值**: :{color}[{final_est:+.2f}%]")
                        
                        # 详细拆解
                        st.caption(f"""
                        🧮 **算法拆解**:
                        • 持仓贡献 ({100-shadow_w*100:.0f}%): `{raw_holdings:+.2f}%`
                        • 影子修正 ({shadow_w*100:.0f}%): `{shadow_est:+.2f}%` ({shadow_name})
                        • 混合结果: `{mixed_est:+.2f}%`
                        • 调节系数: `{factor}`
                        """)
                        st.table(top_stocks)
            
            time.sleep(30)

if __name__ == "__main__":
    main()
