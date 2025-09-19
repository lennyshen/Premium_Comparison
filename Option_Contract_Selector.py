import streamlit as st
import pandas as pd
import akshare as ak
import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 页面配置
st.set_page_config(
    page_title="贴水比较器",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 标题和说明
st.title("贴水比较器")
st.markdown("""
选择两个行权价对应的Call和Put合约，查看4个合约的最新买一卖一价格。
""")

# 自动计算合约月份的函数（从原文件复用）
def get_contract_months():
    """根据第4个星期三规则自动计算合约月份"""
    today = datetime.date.today()
    
    # 计算本月第4个星期三
    first_day = datetime.date(today.year, today.month, 1)
    # 计算第一个星期三
    first_wednesday = first_day + datetime.timedelta(days=(2 - first_day.weekday()) % 7)
    # 第四个星期三 = 第一个星期三 + 3周
    fourth_wednesday = first_wednesday + datetime.timedelta(weeks=3)
    
    # 判断今天是否在本月第4个周三及之前
    if today <= fourth_wednesday:
        # 使用本月作为基准
        base_month = today.month
        base_year = today.year
    else:
        # 使用下月作为基准
        if today.month == 12:
            base_month = 1
            base_year = today.year + 1
        else:
            base_month = today.month + 1
            base_year = today.year
    
    # 计算4个合约月份
    contract_months = []
    
    # 本月合约
    current_month = f"{base_year % 100:02d}{base_month:02d}"
    contract_months.append(current_month)
    
    # 下月合约
    if base_month == 12:
        next_month = 1
        next_year = base_year + 1
    else:
        next_month = base_month + 1
        next_year = base_year
    next_month_contract = f"{next_year % 100:02d}{next_month:02d}"
    contract_months.append(next_month_contract)
    
    # 本季合约（3、6、9、12月）
    quarter_months = [3, 6, 9, 12]
    current_quarter_month = None
    current_quarter_year = base_year
    
    for qm in quarter_months:
        if base_month <= qm:
            current_quarter_month = qm
            break
    
    if current_quarter_month is None:
        current_quarter_month = 3
        current_quarter_year = base_year + 1
    
    current_quarter_contract = f"{current_quarter_year % 100:02d}{current_quarter_month:02d}"
    
    # 检查本季合约是否与本月或下月合约重复
    if current_quarter_contract in [current_month, next_month_contract]:
        # 如果重复，将本季和下季合约都往后推一个季度
        if current_quarter_month == 12:
            current_quarter_month = 3
            current_quarter_year += 1
        else:
            current_quarter_month = quarter_months[quarter_months.index(current_quarter_month) + 1]
        
        current_quarter_contract = f"{current_quarter_year % 100:02d}{current_quarter_month:02d}"
    
    contract_months.append(current_quarter_contract)
    
    # 下季合约
    if current_quarter_month == 12:
        next_quarter_month = 3
        next_quarter_year = current_quarter_year + 1
    else:
        next_quarter_month = quarter_months[quarter_months.index(current_quarter_month) + 1]
        next_quarter_year = current_quarter_year
    
    next_quarter_contract = f"{next_quarter_year % 100:02d}{next_quarter_month:02d}"
    contract_months.append(next_quarter_contract)
    
    return contract_months

# 建立期权代码映射关系（从原文件复用）
@st.cache_data(ttl=43200)  # 缓存12小时
def get_option_code_mapping():
    """建立CONTRACT_ID到SECURITY_ID的映射关系"""
    mapping = {}
    
    def get_previous_working_days(num_days=10):
        """获取上一个工作日开始的日期列表，排除周六周日"""
        dates = []
        current_date = datetime.date.today()
        
        while len(dates) < num_days:
            current_date -= datetime.timedelta(days=1)
            # 跳过周六(5)和周日(6)
            if current_date.weekday() < 5:  # 0-4是周一到周五
                dates.append(current_date.strftime("%Y%m%d"))
        
        return dates
    
    try:
        # 获取最近的工作日列表
        working_dates = get_previous_working_days(10)  # 获取最近10个工作日
        
        option_risk_df = None
        used_date = None
        
        # 尝试多个工作日期，找到一个有效的
        for date in working_dates:
            try:
                option_risk_df = ak.option_risk_indicator_sse(date=date)
                if not option_risk_df.empty:
                    used_date = date
                    break
            except Exception as date_error:
                continue
        
        if option_risk_df is None or option_risk_df.empty:
            return {}
        
        # 检查是否有期望的列名
        actual_columns = list(option_risk_df.columns)
        required_columns = ['SECURITY_ID', 'CONTRACT_ID', 'CONTRACT_SYMBOL']
        missing_columns = [col for col in required_columns if col not in actual_columns]
        
        if missing_columns:
            return {}
        
        # 建立CONTRACT_ID到SECURITY_ID的映射
        for _, row in option_risk_df.iterrows():
            try:
                contract_id = str(row['CONTRACT_ID'])
                security_id = str(row['SECURITY_ID'])
                contract_symbol = str(row['CONTRACT_SYMBOL'])
                
                # 建立映射关系
                mapping[contract_id] = {
                    'security_id': security_id,
                    'contract_symbol': contract_symbol
                }
                
            except Exception as row_error:
                continue
        
        return mapping
        
    except Exception as e:
        return {}

# 获取基础期权数据（从原文件复用并修改）
@st.cache_data(ttl=43200)
def get_basic_option_data():
    """获取基础期权数据，缓存12小时"""
    etf_symbols = [
        "华泰柏瑞沪深300ETF期权",      # 300ETF
        "南方中证500ETF期权",          # 500ETF
        "华夏上证50ETF期权",           # 50ETF
        "华夏科创50ETF期权",           # 科创50ETF
        "易方达科创50ETF期权"          # 科创板50ETF
    ]
    
    # 自动获取合约月份
    contract_months = get_contract_months()
    
    all_option_data = []
    for symbol in etf_symbols:
        for month in contract_months:
            try:
                option_data = ak.option_finance_board(symbol=symbol, end_month=month)
                if not option_data.empty:
                    option_data['ETF类型'] = symbol
                    all_option_data.append(option_data)
            except Exception as e:
                st.warning(f"获取 {symbol} {month} 月合约失败: {str(e)}")
                continue
    
    if not all_option_data:
        return pd.DataFrame()
    
    option_finance_board_df = pd.concat(all_option_data)
    # 从合约交易代码中提取月份信息
    option_finance_board_df['合约月份'] = option_finance_board_df['合约交易代码'].str[7:11]
    
    return option_finance_board_df

# 获取期权买一卖一价格
def get_option_bid_ask_price(security_id):
    """获取期权的买一价和卖一价"""
    try:
        option_data = ak.option_sse_spot_price_sina(symbol=security_id)
        
        # 获取买一价
        bid_price = None
        try:
            bid_price = float(option_data[option_data['字段'] == '买价']['值'].iloc[0])
        except (IndexError, KeyError, ValueError):
            bid_price = 0.0
        
        # 获取卖一价
        ask_price = None
        try:
            ask_price = float(option_data[option_data['字段'] == '卖价']['值'].iloc[0])
        except (IndexError, KeyError, ValueError):
            ask_price = 0.0
        
        # 获取最新价作为参考
        last_price = None
        try:
            last_price = float(option_data[option_data['字段'] == '最新价']['值'].iloc[0])
        except (IndexError, KeyError, ValueError):
            last_price = 0.0
        
        return {
            'bid_price': round(bid_price, 4) if bid_price > 0 else 0.0,
            'ask_price': round(ask_price, 4) if ask_price > 0 else 0.0,
            'last_price': round(last_price, 4) if last_price > 0 else 0.0
        }
        
    except Exception as e:
        return {
            'bid_price': 0.0,
            'ask_price': 0.0,
            'last_price': 0.0,
            'error': str(e)
        }

# 获取实时ETF价格（不缓存，每次都获取最新价格）
def get_real_time_etf_prices():
    """获取实时ETF价格"""
    etf_config = {
        "sh510300": {"name": "300ETF", "keywords": ["沪深300", "300ETF"]},
        "sh510500": {"name": "500ETF", "keywords": ["中证500", "500ETF"]},
        "sh510050": {"name": "50ETF", "keywords": ["上证50", "50ETF"]},
        "sh588000": {"name": "科创50ETF", "keywords": ["华夏科创50", "科创50ETF"]},
        "sh588080": {"name": "科创板50ETF", "keywords": ["易方达科创50", "科创板50ETF", "易方达"]}
    }
    
    etf_prices = {}
    for symbol, config in etf_config.items():
        try:
            spot_price_df = ak.option_sse_underlying_spot_price_sina(symbol=symbol)
            current_price = float(spot_price_df.loc[spot_price_df['字段'] == '最近成交价', '值'].iloc[0])
            etf_prices[symbol] = round(current_price, 4)  # 保留4位小数
        except Exception as e:
            etf_prices[symbol] = 0.0  # 设置默认值
    
    return etf_config, etf_prices

# 根据ETF类型获取对应的ETF价格
def get_etf_price_for_type(etf_type_name, etf_config, etf_prices):
    """根据ETF类型名称获取对应的ETF价格"""
    # 创建所有可能的匹配项，按关键词长度降序排列
    matches = []
    for symbol, config in etf_config.items():
        for keyword in config['keywords']:
            if keyword in etf_type_name:
                matches.append((len(keyword), symbol, keyword))
    
    # 按关键词长度降序排序，优先匹配更具体的关键词
    matches.sort(reverse=True)
    
    if matches:
        return etf_prices.get(matches[0][1], 0.0)
    
    # 默认返回300ETF价格
    return etf_prices.get("sh510300", 0.0)

# 计算时间价值
def calculate_time_value(option_price, etf_price, strike_price, option_type):
    """计算期权的时间价值：时间价值 = 交易价格 - 内在价值"""
    if option_type.upper() == 'CALL' or option_type.upper() == 'C':
        # Call期权内在价值 = max(标的价格 - 行权价, 0)
        intrinsic_value = max(etf_price - strike_price, 0)
    else:
        # Put期权内在价值 = max(行权价 - 标的价格, 0)
        intrinsic_value = max(strike_price - etf_price, 0)
    
    # 时间价值 = 交易价格 - 内在价值（可以为负数）
    time_value = option_price - intrinsic_value
    return time_value

# 计算贴水值
def calculate_premium_value(call_time_value, put_time_value):
    """计算贴水值：Put时间价值 - Call时间价值"""
    return put_time_value - call_time_value

# ETF类型映射
ETF_DISPLAY_NAMES = {
    "华泰柏瑞沪深300ETF期权": "300ETF",
    "南方中证500ETF期权": "500ETF", 
    "华夏上证50ETF期权": "50ETF",
    "华夏科创50ETF期权": "科创50ETF",
    "易方达科创50ETF期权": "科创板50ETF"
}

# 初始化会话状态
if 'option_data' not in st.session_state:
    st.session_state.option_data = None
if 'option_mapping' not in st.session_state:
    st.session_state.option_mapping = None
if 'auto_refresh_active' not in st.session_state:
    st.session_state.auto_refresh_active = False
if 'last_auto_refresh_time' not in st.session_state:
    st.session_state.last_auto_refresh_time = 0
if 'max_premium_diff' not in st.session_state:
    st.session_state.max_premium_diff = None
if 'max_premium_diff_time' not in st.session_state:
    st.session_state.max_premium_diff_time = None
if 'premium_diff_history' not in st.session_state:
    st.session_state.premium_diff_history = []
if 'today_date' not in st.session_state:
    st.session_state.today_date = datetime.date.today().strftime('%Y-%m-%d')
if 'historical_max_premium_diff' not in st.session_state:
    st.session_state.historical_max_premium_diff = None
if 'historical_max_premium_diff_datetime' not in st.session_state:
    st.session_state.historical_max_premium_diff_datetime = None

# 侧边栏 - 用户选择界面
st.sidebar.header("📋 选择期权合约")

# 获取基础数据
with st.spinner("正在加载期权数据..."):
    if st.session_state.option_data is None:
        st.session_state.option_data = get_basic_option_data()
    if st.session_state.option_mapping is None:
        st.session_state.option_mapping = get_option_code_mapping()

option_data = st.session_state.option_data
option_mapping = st.session_state.option_mapping

if option_data is None or option_data.empty:
    st.error("无法获取期权数据，请稍后重试")
    st.stop()

# ETF类型选择
etf_types = option_data['ETF类型'].unique().tolist()
selected_etf = st.sidebar.selectbox(
    "选择ETF类型",
    etf_types,
    format_func=lambda x: ETF_DISPLAY_NAMES.get(x, x)
)

# 过滤选定ETF的数据
filtered_data = option_data[option_data['ETF类型'] == selected_etf]
available_months = sorted(filtered_data['合约月份'].unique().tolist())

# 第一组合约选择
st.sidebar.subheader("🎯 第一组合约")
selected_month_1 = st.sidebar.selectbox(
    "第一组合约月份",
    available_months,
    key="month_1"
)

# 获取第一组的可用行权价
month_1_data = filtered_data[filtered_data['合约月份'] == selected_month_1]
available_strikes_1 = sorted(month_1_data['行权价'].unique().tolist())

strike_1 = st.sidebar.selectbox(
    "第一组行权价",
    available_strikes_1,
    index=0,
    key="strike_1"
)

# 第一组交易方向选择
trade_direction_1 = st.sidebar.selectbox(
    "第一组交易方向",
    ["Buy", "Sell"],
    key="direction_1",
    help="Buy: Call取卖一价，Put取买一价；Sell: Call取买一价，Put取卖一价"
)

# 第二组合约选择
st.sidebar.subheader("🎯 第二组合约")
selected_month_2 = st.sidebar.selectbox(
    "第二组合约月份",
    available_months,
    key="month_2"
)

# 获取第二组的可用行权价
month_2_data = filtered_data[filtered_data['合约月份'] == selected_month_2]
available_strikes_2 = sorted(month_2_data['行权价'].unique().tolist())

strike_2 = st.sidebar.selectbox(
    "第二组行权价",
    available_strikes_2,
    index=0,
    key="strike_2"
)

# 第二组交易方向选择
trade_direction_2 = st.sidebar.selectbox(
    "第二组交易方向",
    ["Buy", "Sell"],
    key="direction_2",
    help="Buy: Call取卖一价，Put取买一价；Sell: Call取买一价，Put取卖一价"
)

# 刷新控制按钮
st.sidebar.subheader("🔄 刷新控制")
col_refresh, col_stop = st.sidebar.columns(2)

with col_refresh:
    refresh_button = st.button("🔄 开始自动刷新", help="开始每5秒自动刷新价格")

with col_stop:
    stop_button = st.button("⏹️ 停止刷新", help="停止自动刷新")

# 处理按钮点击
if refresh_button:
    st.session_state.auto_refresh_active = True
    st.session_state.last_auto_refresh_time = time.time()

if stop_button:
    st.session_state.auto_refresh_active = False

# 主界面显示
st.subheader(f"{ETF_DISPLAY_NAMES.get(selected_etf, selected_etf)} 期权合约对比")
st.markdown(f"**第一组:** {trade_direction_1} {selected_month_1}月 行权价{strike_1} | **第二组:** {trade_direction_2} {selected_month_2}月 行权价{strike_2}")

# 获取对应的合约代码
def get_contract_codes(etf_type, month, strike):
    """获取指定条件的Call和Put合约代码"""
    # 根据月份过滤数据
    month_data = filtered_data[filtered_data['合约月份'] == month]
    contracts = month_data[month_data['行权价'] == strike]
    
    call_contracts = contracts[contracts['合约交易代码'].str.contains('C')]
    put_contracts = contracts[contracts['合约交易代码'].str.contains('P')]
    
    call_code = call_contracts.iloc[0]['合约交易代码'] if len(call_contracts) > 0 else None
    put_code = put_contracts.iloc[0]['合约交易代码'] if len(put_contracts) > 0 else None
    
    return call_code, put_code

# 获取四个合约的代码
call_1, put_1 = get_contract_codes(selected_etf, selected_month_1, strike_1)
call_2, put_2 = get_contract_codes(selected_etf, selected_month_2, strike_2)

contracts_info = [
    {"name": f"Call {selected_month_1}-{strike_1}", "code": call_1, "type": "Call", "strike": strike_1, "month": selected_month_1},
    {"name": f"Put {selected_month_1}-{strike_1}", "code": put_1, "type": "Put", "strike": strike_1, "month": selected_month_1},
    {"name": f"Call {selected_month_2}-{strike_2}", "code": call_2, "type": "Call", "strike": strike_2, "month": selected_month_2},
    {"name": f"Put {selected_month_2}-{strike_2}", "code": put_2, "type": "Put", "strike": strike_2, "month": selected_month_2},
]

# 检查是否需要刷新数据
current_time = time.time()
should_refresh = False

# 检查是否需要重置当天记录（新的一天）
current_date = datetime.date.today().strftime('%Y-%m-%d')
if st.session_state.today_date != current_date:
    st.session_state.today_date = current_date
    st.session_state.max_premium_diff = None
    st.session_state.max_premium_diff_time = None
    st.session_state.premium_diff_history = []

# 判断是否需要刷新
if refresh_button:
    should_refresh = True
elif st.session_state.auto_refresh_active and (current_time - st.session_state.last_auto_refresh_time >= 5):
    should_refresh = True
    st.session_state.last_auto_refresh_time = current_time
elif 'price_data' not in st.session_state:
    should_refresh = True

# 显示合约信息
if should_refresh:
        # 获取ETF实时价格
        etf_config, etf_prices = get_real_time_etf_prices()
        current_etf_price = get_etf_price_for_type(selected_etf, etf_config, etf_prices)
        
        price_results = []
        
        # 使用线程池并行获取价格
        def get_contract_price(contract_info):
            if contract_info['code'] is None:
                return {
                    'name': contract_info['name'],
                    'code': 'N/A',
                    'bid_price': 0.0,
                    'ask_price': 0.0,
                    'last_price': 0.0,
                    'error': '合约不存在'
                }
            
            # 从映射中获取security_id
            security_id = None
            if contract_info['code'] in option_mapping:
                security_id = option_mapping[contract_info['code']]['security_id']
            
            if security_id is None:
                return {
                    'name': contract_info['name'],
                    'code': contract_info['code'],
                    'bid_price': 0.0,
                    'ask_price': 0.0,
                    'last_price': 0.0,
                    'error': '无法获取security_id'
                }
            
            # 获取价格
            price_data = get_option_bid_ask_price(security_id)
            price_data['name'] = contract_info['name']
            price_data['code'] = contract_info['code']
            price_data['strike'] = contract_info['strike']
            price_data['type'] = contract_info['type']
            price_data['month'] = contract_info['month']
            
            return price_data
        
        # 并行获取所有合约价格
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(get_contract_price, contract): contract for contract in contracts_info}
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    price_results.append(result)
                except Exception as e:
                    contract = futures[future]
                    price_results.append({
                        'name': contract['name'],
                        'code': contract.get('code', 'N/A'),
                        'bid_price': 0.0,
                        'ask_price': 0.0,
                        'last_price': 0.0,
                        'error': str(e)
                    })
        
        # 计算贴水值
        def calculate_group_premium(group_num, trade_direction, month, strike):
            """计算单组合约的贴水值"""
            call_data = next((p for p in price_results if p['name'] == f"Call {month}-{strike}"), None)
            put_data = next((p for p in price_results if p['name'] == f"Put {month}-{strike}"), None)
            
            if not call_data or not put_data or 'error' in call_data or 'error' in put_data:
                return None
            
            # 根据交易方向选择价格
            if trade_direction == "Buy":
                # Buy: Call取卖一价，Put取买一价
                call_price = call_data['ask_price']
                put_price = put_data['bid_price']
            else:  # Sell
                # Sell: Call取买一价，Put取卖一价
                call_price = call_data['bid_price']
                put_price = put_data['ask_price']
            
            # 计算时间价值
            call_time_value = calculate_time_value(call_price, current_etf_price, strike, 'CALL')
            put_time_value = calculate_time_value(put_price, current_etf_price, strike, 'PUT')
            
            # 计算贴水值
            premium_value = calculate_premium_value(call_time_value, put_time_value)
            
            return {
                'group': group_num,
                'trade_direction': trade_direction,
                'month': month,
                'strike': strike,
                'call_price': call_price,
                'put_price': put_price,
                'call_time_value': call_time_value,
                'put_time_value': put_time_value,
                'premium_value': premium_value
            }
        
        # 计算两组的贴水值
        group1_premium = calculate_group_premium(1, trade_direction_1, selected_month_1, strike_1)
        group2_premium = calculate_group_premium(2, trade_direction_2, selected_month_2, strike_2)
        
        # 计算贴水值差值
        premium_diff = None
        if group1_premium and group2_premium:
            premium_diff = group2_premium['premium_value'] - group1_premium['premium_value']
            
            # 记录贴水差值历史
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            current_datetime = datetime.datetime.now(beijing_tz)
            current_time_str = current_datetime.strftime('%H:%M:%S')
            current_datetime_str = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
            
            # 添加到历史记录
            st.session_state.premium_diff_history.append({
                'time': current_time_str,
                'diff': premium_diff,
                'group1_premium': group1_premium['premium_value'],
                'group2_premium': group2_premium['premium_value']
            })
            
            # 只保留最近50条记录
            if len(st.session_state.premium_diff_history) > 50:
                st.session_state.premium_diff_history = st.session_state.premium_diff_history[-50:]
            
            # 更新当天最大贴水差值
            if st.session_state.max_premium_diff is None or abs(premium_diff) > abs(st.session_state.max_premium_diff):
                st.session_state.max_premium_diff = premium_diff
                st.session_state.max_premium_diff_time = current_time_str
            
            # 更新历史最大贴水差值
            if st.session_state.historical_max_premium_diff is None or abs(premium_diff) > abs(st.session_state.historical_max_premium_diff):
                st.session_state.historical_max_premium_diff = premium_diff
                st.session_state.historical_max_premium_diff_datetime = current_datetime_str
        
        # 存储所有计算结果
        st.session_state.price_data = price_results
        st.session_state.etf_price = current_etf_price
        st.session_state.group1_premium = group1_premium
        st.session_state.group2_premium = group2_premium
        st.session_state.premium_diff = premium_diff

# 创建固定的状态显示区域
status_container = st.container()
with status_container:
    # 显示自动刷新状态和ETF价格
    status_col1, status_col2, status_col3 = st.columns([1, 1, 1])
    
    with status_col1:
        if st.session_state.auto_refresh_active:
            if should_refresh:
                st.success("🔄 正在刷新数据...")
            else:
                # 显示倒计时
                time_since_last_refresh = time.time() - st.session_state.last_auto_refresh_time
                remaining_time = max(0, 5 - time_since_last_refresh)
                st.success(f"🔄 下次刷新: {remaining_time:.1f}秒")
        else:
            st.info("⏸️ 自动刷新已停止")
    
    with status_col2:
        if 'etf_price' in st.session_state:
            st.info(f"📊 **{ETF_DISPLAY_NAMES.get(selected_etf, selected_etf)}**: {st.session_state.etf_price:.4f}")
        else:
            st.info("📊 等待价格数据...")
    
    with status_col3:
        # 显示最后更新时间
        if 'price_data' in st.session_state:
            beijing_tz = datetime.timezone(datetime.timedelta(hours=8))
            beijing_time = datetime.datetime.now(beijing_tz)
            st.info(f"⏰ {beijing_time.strftime('%H:%M:%S')}")

# 显示当天最大贴水差值和历史最大贴水差值
max_diff_col1, max_diff_col2 = st.columns(2)

with max_diff_col1:
    if st.session_state.max_premium_diff is not None:
        st.metric(
            f"📈 今日最大贴水差值 (绝对值)",
            f"{st.session_state.max_premium_diff:.4f}",
            help=f"记录时间: {st.session_state.today_date} {st.session_state.max_premium_diff_time}"
        )

with max_diff_col2:
    if st.session_state.historical_max_premium_diff is not None:
        st.metric(
            f"🏆 历史最大贴水差值 (绝对值)",
            f"{st.session_state.historical_max_premium_diff:.4f}",
            help=f"记录时间: {st.session_state.historical_max_premium_diff_datetime}"
        )

# 显示贴水分析结果
if 'group1_premium' in st.session_state and 'group2_premium' in st.session_state and 'premium_diff' in st.session_state:
    group1 = st.session_state.group1_premium
    group2 = st.session_state.group2_premium
    diff = st.session_state.premium_diff
    
    if group1 and group2 and diff is not None:
        # 创建三列布局显示贴水分析
        analysis_col1, analysis_col2, analysis_col3 = st.columns(3)
        
        with analysis_col1:
            st.metric(
                f"第一组贴水值 ({trade_direction_1})",
                f"{group1['premium_value']:.4f}",
                help=f"Put时间价值({group1['put_time_value']:.4f}) - Call时间价值({group1['call_time_value']:.4f})\n时间价值 = 交易价格 - 内在价值"
            )
        
        with analysis_col2:
            st.metric(
                f"第二组贴水值 ({trade_direction_2})",
                f"{group2['premium_value']:.4f}",
                help=f"Put时间价值({group2['put_time_value']:.4f}) - Call时间价值({group2['call_time_value']:.4f})\n时间价值 = 交易价格 - 内在价值"
            )
        
        with analysis_col3:
            delta_color = "normal"
            if diff > 0:
                delta_color = "normal"
                delta_text = f"+{diff:.4f}"
            elif diff < 0:
                delta_color = "inverse"
                delta_text = f"{diff:.4f}"
            else:
                delta_text = "0.0000"
            
            st.metric(
                "贴水值差值",
                f"{diff:.4f}",
                delta=delta_text,
                help="第二组贴水值 - 第一组贴水值"
            )

# 显示价格数据
if 'price_data' in st.session_state:
    price_data = st.session_state.price_data
    
    # 创建两列布局，每列显示一个行权价的Call和Put
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"### 第一组: {trade_direction_1} {selected_month_1}月 行权价{strike_1}")
        
        # Call合约
        call_1_data = next((p for p in price_data if p['name'] == f"Call {selected_month_1}-{strike_1}"), None)
        if call_1_data:
            with st.container():
                st.markdown(f"**Call {selected_month_1}-{strike_1}** ({call_1_data['code']})")
                col1_1, col1_2, col1_3 = st.columns(3)
                
                # 根据交易方向高亮显示使用的价格
                call_used_price = "ask_price" if trade_direction_1 == "Buy" else "bid_price"
                
                with col1_1:
                    if call_used_price == "bid_price":
                        st.metric("买一价 ⭐", f"{call_1_data['bid_price']:.4f}")
                    else:
                        st.metric("买一价", f"{call_1_data['bid_price']:.4f}")
                with col1_2:
                    if call_used_price == "ask_price":
                        st.metric("卖一价 ⭐", f"{call_1_data['ask_price']:.4f}")
                    else:
                        st.metric("卖一价", f"{call_1_data['ask_price']:.4f}")
                with col1_3:
                    st.metric("最新价", f"{call_1_data['last_price']:.4f}")
                
                if 'error' in call_1_data:
                    st.error(f"错误: {call_1_data['error']}")
        
        st.markdown("---")
        
        # Put合约
        put_1_data = next((p for p in price_data if p['name'] == f"Put {selected_month_1}-{strike_1}"), None)
        if put_1_data:
            with st.container():
                st.markdown(f"**Put {selected_month_1}-{strike_1}** ({put_1_data['code']})")
                col1_1, col1_2, col1_3 = st.columns(3)
                
                # 根据交易方向高亮显示使用的价格 (Put与Call相反)
                put_used_price = "bid_price" if trade_direction_1 == "Buy" else "ask_price"
                
                with col1_1:
                    if put_used_price == "bid_price":
                        st.metric("买一价 ⭐", f"{put_1_data['bid_price']:.4f}")
                    else:
                        st.metric("买一价", f"{put_1_data['bid_price']:.4f}")
                with col1_2:
                    if put_used_price == "ask_price":
                        st.metric("卖一价 ⭐", f"{put_1_data['ask_price']:.4f}")
                    else:
                        st.metric("卖一价", f"{put_1_data['ask_price']:.4f}")
                with col1_3:
                    st.metric("最新价", f"{put_1_data['last_price']:.4f}")
                
                if 'error' in put_1_data:
                    st.error(f"错误: {put_1_data['error']}")
    
    with col2:
        st.markdown(f"### 第二组: {trade_direction_2} {selected_month_2}月 行权价{strike_2}")
        
        # Call合约
        call_2_data = next((p for p in price_data if p['name'] == f"Call {selected_month_2}-{strike_2}"), None)
        if call_2_data:
            with st.container():
                st.markdown(f"**Call {selected_month_2}-{strike_2}** ({call_2_data['code']})")
                col2_1, col2_2, col2_3 = st.columns(3)
                
                # 根据交易方向高亮显示使用的价格
                call_used_price = "ask_price" if trade_direction_2 == "Buy" else "bid_price"
                
                with col2_1:
                    if call_used_price == "bid_price":
                        st.metric("买一价 ⭐", f"{call_2_data['bid_price']:.4f}")
                    else:
                        st.metric("买一价", f"{call_2_data['bid_price']:.4f}")
                with col2_2:
                    if call_used_price == "ask_price":
                        st.metric("卖一价 ⭐", f"{call_2_data['ask_price']:.4f}")
                    else:
                        st.metric("卖一价", f"{call_2_data['ask_price']:.4f}")
                with col2_3:
                    st.metric("最新价", f"{call_2_data['last_price']:.4f}")
                
                if 'error' in call_2_data:
                    st.error(f"错误: {call_2_data['error']}")
        
        st.markdown("---")
        
        # Put合约
        put_2_data = next((p for p in price_data if p['name'] == f"Put {selected_month_2}-{strike_2}"), None)
        if put_2_data:
            with st.container():
                st.markdown(f"**Put {selected_month_2}-{strike_2}** ({put_2_data['code']})")
                col2_1, col2_2, col2_3 = st.columns(3)
                
                # 根据交易方向高亮显示使用的价格 (Put与Call相反)
                put_used_price = "bid_price" if trade_direction_2 == "Buy" else "ask_price"
                
                with col2_1:
                    if put_used_price == "bid_price":
                        st.metric("买一价 ⭐", f"{put_2_data['bid_price']:.4f}")
                    else:
                        st.metric("买一价", f"{put_2_data['bid_price']:.4f}")
                with col2_2:
                    if put_used_price == "ask_price":
                        st.metric("卖一价 ⭐", f"{put_2_data['ask_price']:.4f}")
                    else:
                        st.metric("卖一价", f"{put_2_data['ask_price']:.4f}")
                with col2_3:
                    st.metric("最新价", f"{put_2_data['last_price']:.4f}")
                
                if 'error' in put_2_data:
                    st.error(f"错误: {put_2_data['error']}")

# 显示贴水差值历史记录
if st.session_state.premium_diff_history:
    with st.expander("📈 贴水差值历史记录", expanded=False):
        # 显示最近的贴水差值变化
        recent_history = st.session_state.premium_diff_history[-10:]  # 显示最近10条
        history_df = pd.DataFrame(recent_history)
        if not history_df.empty:
            history_df['diff'] = history_df['diff'].round(4)
            history_df['group1_premium'] = history_df['group1_premium'].round(4)
            history_df['group2_premium'] = history_df['group2_premium'].round(4)
            history_df.columns = ['时间', '贴水差值', '第一组贴水', '第二组贴水']
            st.dataframe(history_df.iloc[::-1], use_container_width=True, hide_index=True)  # 倒序显示，最新的在上面

# 自动刷新逻辑
if st.session_state.auto_refresh_active:
    time_since_last_refresh = time.time() - st.session_state.last_auto_refresh_time
    remaining_time = max(0, 5 - time_since_last_refresh)
    
    if remaining_time <= 0:
        # 时间到了，触发刷新
        st.rerun()
    else:
        # 使用短暂的延迟来实现自动刷新
        time.sleep(0.5)
        st.rerun()

# 添加说明
st.markdown("---")
st.markdown("""
### 使用说明
1. 在左侧选择ETF类型
2. 分别选择第一组和第二组的合约月份、行权价和交易方向：
   - **Buy**: Call期权取卖一价，Put期权取买一价
   - **Sell**: Call期权取买一价，Put期权取卖一价
3. 点击"开始自动刷新"按钮启动每5秒自动更新，点击"停止刷新"按钮停止自动更新
4. 系统会显示：
   - 自动刷新状态和ETF当前价格
   - 今日最大贴水差值（绝对值）和记录时间
   - 历史最大贴水差值（绝对值）和记录日期时间
   - 两组合约的贴水值和贴水值差值
   - 每个合约的详细价格信息（⭐标记表示用于计算的价格）
   - 最近5次贴水差值变化历史

### 贴水值计算说明
- **内在价值**：
  - Call期权：max(标的价格 - 行权价, 0)
  - Put期权：max(行权价 - 标的价格, 0)
- **时间价值** = 交易价格 - 内在价值
- **贴水值** = Put时间价值 - Call时间价值
- **贴水值差值** = 第二组贴水值 - 第一组贴水值

### 注意事项
- 价格数据来源于实时行情，可能存在延迟
- 时间价值可以为负数，表示期权交易价格低于其内在价值
- 自动刷新功能每5秒更新一次数据，会自动记录当天和历史最大贴水差值
- 今日最大贴水差值每天开始时会重置，历史最大贴水差值会持续保持
- 所有时间均为北京时间（UTC+8）
- 建议在交易时间内使用以获取准确的价格信息
""")
