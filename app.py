import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
from dhanhq import dhanhq, DhanContext

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Pro Quant Momentum System", layout="wide", page_icon="📈")
st.title("📈 Pro Quant Momentum System (Powered by Dhan API)")

# --- API CREDENTIALS (Use st.secrets in Streamlit Cloud) ---
try:
    CLIENT_ID = st.secrets["DHAN_CLIENT_ID"]
    ACCESS_TOKEN = st.secrets["DHAN_ACCESS_TOKEN"]
except:
    # Local testing fallback - Replace with actual keys
    CLIENT_ID = "YOUR_CLIENT_ID"
    ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"

# Initialize Dhan API
dhan_context = DhanContext(CLIENT_ID, ACCESS_TOKEN)
dhan = dhanhq(dhan_context)

# --- 1. GET DHAN SECURITY IDs (LOCAL FILE SUPPORT ADDED) ---
@st.cache_data(ttl=86400)
def get_dhan_security_map():
    try:
        # System sabse pehle in local files ko dhoondega
        local_files = [
            "Untitled spreadsheet - Sheet1 (11)_2.csv", 
            "Untitled spreadsheet - Sheet1 (11).csv",
            "api-scrip-master.csv",
            "dhan_scrip_master.csv"
        ]
        
        df_dhan = None
        for lf in local_files:
            if os.path.exists(lf):
                df_dhan = pd.read_csv(lf, low_memory=False)
                st.sidebar.success(f"📂 Loaded Dhan IDs from: {lf}")
                break
                
        # Agar local file nahi mili, toh fallback live server se fetch karega
        if df_dhan is None:
            csv_url = "https://images.dhan.co/api-data/api-scrip-master.csv"
            df_dhan = pd.read_csv(csv_url, low_memory=False)
            st.sidebar.info("🌐 Fetched Dhan IDs from Live Server")

        # Map logic (Pre-filtered ya Full dono files par kaam karega)
        if 'SEM_EXM_EXCH_ID' in df_dhan.columns:
            nse_stocks = df_dhan[(df_dhan['SEM_EXM_EXCH_ID'] == 'NSE') & (df_dhan['SEM_SERIES'] == 'EQ')]
        else:
            nse_stocks = df_dhan 

        security_dict = dict(zip(nse_stocks['SEM_TRADING_SYMBOL'], nse_stocks['SEM_SMST_SECURITY_ID']))
        security_dict["^NSEI"] = "26000" # Nifty 50 manual entry
        return security_dict
    except Exception as e:
        st.error(f"Error fetching Dhan Scrip Master: {e}")
        return {}

DHAN_MAP = get_dhan_security_map()

# --- 2. LOAD USER SYMBOLS ---
@st.cache_data
def load_symbols():
    file_path = "Untitled spreadsheet - Sheet1 (11)_2.csv"
    if not os.path.exists(file_path):
        file_path = "symbols.csv"
        
    if os.path.exists(file_path):
        df_symbols = pd.read_csv(file_path)
        
        # Smart Column Detection (Taki KeyError: 'Symbol' na aaye)
        if 'Symbol' in df_symbols.columns:
            col_name = 'Symbol'
        elif 'SYMBOL' in df_symbols.columns:
            col_name = 'SYMBOL'
        elif 'SEM_TRADING_SYMBOL' in df_symbols.columns:
            col_name = 'SEM_TRADING_SYMBOL'
        else:
            col_name = df_symbols.columns[0]
            
        ticker_list = []
        for sym in df_symbols[col_name].dropna():
            sym_str = str(sym).strip().replace('.NS', '') 
            ticker_list.append(sym_str)
        return ticker_list
    else:
        st.warning("CSV file not found! Please upload 'STOCK SYMBOLS (1).csv'. Running with fallback.")
        return ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "ITC", "LT"]

TICKERS = load_symbols()
BENCHMARK = "^NSEI" 

st.sidebar.success(f"✅ Loaded {len(TICKERS)} stocks for Backtest")
st.sidebar.info("🔌 Connected to DhanHQ API")

import time # Ise file ke top par import zaroor karein agar nahi hai

# --- 3. FETCH DHAN HISTORICAL DATA (BULLETPROOF VERSION) ---
@st.cache_data(show_spinner=False)
def fetch_historical_data(tickers, start_date, end_date):
    df_combined = pd.DataFrame()
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    # 1. Fetch Stocks from Dhan API
    for symbol in tickers:
        sec_id = DHAN_MAP.get(symbol)
        if not sec_id:
            continue
            
        try:
            # 🛑 API Rate Limit Protection (Server block se bachne ke liye delay)
            time.sleep(0.2) 
            
            req_data = dhan.historical_daily_data(
                symbol=str(sec_id), 
                exchange_segment='NSE_EQ' if symbol != BENCHMARK else 'IDX_I',
                instrument_type='EQUITY' if symbol != BENCHMARK else 'INDEX',
                expiry_code=0,
                from_date=start_str,
                to_date=end_str
            )
            
            if req_data.get('status') == 'success' and req_data.get('data'):
                temp_df = pd.DataFrame(req_data['data'])
                # Handle possible column name changes by Dhan
                date_col = 'start_Time' if 'start_Time' in temp_df.columns else 'date'
                temp_df['Date'] = pd.to_datetime(temp_df[date_col])
                temp_df.set_index('Date', inplace=True)
                
                df_combined[symbol] = temp_df['close']
            else:
                # Dhan API exact error console me print karega
                print(f"Dhan API Error for {symbol}: {req_data}")
                
        except Exception as e:
            print(f"Crash for {symbol}: {e}")
            pass 
            
    # 🛑 2. NIFTY 50 FALLBACK (Safe Net)
    # Agar Dhan API ne Nifty 50 ka data nahi diya, toh backtest fail na ho isliye yfinance se uthayega
    if BENCHMARK not in df_combined.columns or df_combined[BENCHMARK].isnull().all():
        try:
            import yfinance as yf
            bench_data = yf.download(BENCHMARK, start=start_date, end=end_date, progress=False)['Close']
            df_combined[BENCHMARK] = bench_data
        except:
            pass
            
    df_combined = df_combined.ffill().dropna(how='all')
    return df_combined
# CREATE TABS
# ==========================================
tab1, tab2 = st.tabs(["🔴 Live Momentum Scanner", "📊 Pro Quant Backtest Engine"])

# ==========================================
# TAB 1: LIVE SCANNER
# ==========================================
with tab1:
    st.header("Current Month Selection")
    top_n = st.slider("Select Top N Stocks for Portfolio", min_value=3, max_value=20, value=10, key='live_n')
    
    if st.button("Run Live Scanner (Dhan API)"):
        with st.spinner(f"Fetching live data for {len(TICKERS)} stocks from Dhan. Please wait..."):
            end_date = datetime.today()
            start_date = end_date - timedelta(days=250)
            
            data = fetch_historical_data(TICKERS, start_date, end_date)
            
            results = []
            for t in TICKERS:
                if t in data.columns:
                    series = data[t].dropna()
                    if len(series) >= 126: 
                        curr_price = series.iloc[-1]
                        price_6m_ago = series.iloc[-126]
                        roc = ((curr_price - price_6m_ago) / price_6m_ago) * 100
                        
                        results.append({
                            'Stock': t, 
                            'Current Price (₹)': round(curr_price, 2),
                            '6M Return (%)': round(roc, 2), 
                            'Momentum Score': round(roc, 2)
                        })
            
            if results:
                df = pd.DataFrame(results).sort_values(by='Momentum Score', ascending=False).reset_index(drop=True)
                df.index += 1
                
                st.success(f"🏆 Top {top_n} Stocks to Buy & Hold right now:")
                st.dataframe(df.head(top_n), use_container_width=True)
                st.info(f"💡 **Action:** Allocate {round(100/top_n, 2)}% of your capital to each of these {top_n} stocks.")
            else:
                st.error("Not enough data fetched. Check API credentials or internet connection.")

# ==========================================
# TAB 2: BACKTEST & EQUITY CURVE
# ==========================================
with tab2:
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        bt_top_n = st.slider("Stocks to hold", min_value=3, max_value=20, value=10, key='bt_n')
    with col2:
        txn_cost_pct = st.number_input("Txn Cost (%)", min_value=0.0, max_value=5.0, value=1.0, step=0.1)
    with col3:
        rebalance_freq = st.selectbox("Rebalance", ["Monthly", "Quarterly"])
    with col4:
        backtest_period = st.selectbox("Test Duration", ["3 Years", "5 Years", "9 Years", "10 Years", "15 Years"], index=2)
    with col5:
        chunk_years = st.slider("Split Breakdown (Yrs)", min_value=1, max_value=5, value=3)
    
    st.header(f"Momentum Strategy vs Nifty 50 ({backtest_period} Engine)")
    
    if st.button("Run Pro Backtest & Analytics"):
        
        years_map = {"3 Years": 3, "5 Years": 5, "9 Years": 9, "10 Years": 10, "15 Years": 15}
        selected_years = years_map[backtest_period]
        end = datetime.today()
        start = end - timedelta(days=(365 * selected_years) + 182)
        
        with st.spinner(f"Fetching {backtest_period} historical tick data from Dhan API. (Takes 1-2 mins on first run, cached instantly after)..."):
            all_tickers = TICKERS + [BENCHMARK]
            df_daily = fetch_historical_data(all_tickers, start, end)
            
        if df_daily.empty or len(df_daily) < 130:
            st.error("Failed to fetch historical data from Dhan API. Please check your credentials and network.")
        else:
            with st.spinner("Simulating multi-year rebalancing and calculating Institutional Quants metrics..."):
                monthly_dates = df_daily.resample('ME').last().index
                portfolio_returns = []
                benchmark_returns = []
                dates_tracked = []
                txn_cost_decimal = txn_cost_pct / 100.0
                previous_ranked_stocks = []
                active_positions = {}
                completed_trades = []
                
                step = 1 if rebalance_freq == "Monthly" else 3
                periods_per_year = 12 if rebalance_freq == "Monthly" else 4
                
                for i in range(6, len(monthly_dates) - step, step):
                    eval_date = monthly_dates[i]
                    start_lookback = monthly_dates[i-6]
                    next_rebalance_date = monthly_dates[i+step]
                    
                    scores = {}
                    for t in TICKERS:
                        if t in df_daily.columns:
                            p_eval = df_daily[t].loc[:eval_date].dropna()
                            p_start = df_daily[t].loc[:start_lookback].dropna()
                            
                            if len(p_eval) > 0 and len(p_start) > 0:
                                curr_price = p_eval.iloc[-1]
                                old_price = p_start.iloc[-1]
                                roc = (curr_price - old_price) / old_price
                                scores[t] = roc
                    
                    if not scores: continue
                    ranked_stocks = sorted(scores, key=scores.get, reverse=True)[:bt_top_n]
                    
                    for t in list(active_positions.keys()):
                        if t not in ranked_stocks:
                            try:
                                entry_date = active_positions[t]['entry_date']
                                entry_price = active_positions[t]['entry_price']
                                exit_price = df_daily[t].loc[:eval_date].dropna().iloc[-1]
                                days_held = (eval_date - entry_date).days
                                net_ret = ((exit_price - entry_price) / entry_price) - txn_cost_decimal
                                
                                completed_trades.append({
                                    'Stock': t, 'Entry Date': entry_date.strftime('%Y-%m-%d'),
                                    'Entry Price (₹)': round(entry_price, 2), 'Exit Date': eval_date.strftime('%Y-%m-%d'),
                                    'Exit Price (₹)': round(exit_price, 2), 'Holding Days': days_held,
                                    'Net Return (%)': round(net_ret * 100, 2)
                                })
                            except Exception:
                                pass
                            del active_positions[t]
                    
                    for t in ranked_stocks:
                        if t not in active_positions:
                            try:
                                entry_price = df_daily[t].loc[:eval_date].dropna().iloc[-1]
                                active_positions[t] = {'entry_date': eval_date, 'entry_price': entry_price}
                            except Exception:
                                pass

                    port_period_ret = 0
                    valid_stocks = 0
                    for t in ranked_stocks:
                        try:
                            buy_price = df_daily[t].loc[:eval_date].dropna().iloc[-1]
                            sell_price = df_daily[t].loc[:next_rebalance_date].dropna().iloc[-1]
                            gross_ret = (sell_price - buy_price) / buy_price
                            net_ret = gross_ret - txn_cost_decimal if t not in previous_ranked_stocks else gross_ret
                            port_period_ret += net_ret
                            valid_stocks += 1
                        except Exception:
                            pass
                    
                    if valid_stocks > 0:
                        port_period_ret = port_period_ret / valid_stocks
                    portfolio_returns.append(port_period_ret)
                    
                    try:
                        bench_buy = df_daily[BENCHMARK].loc[:eval_date].dropna().iloc[-1]
                        bench_sell = df_daily[BENCHMARK].loc[:next_rebalance_date].dropna().iloc[-1]
                        benchmark_returns.append((bench_sell - bench_buy) / bench_buy)
                    except Exception:
                        benchmark_returns.append(0)
                    
                    dates_tracked.append(next_rebalance_date)
                    previous_ranked_stocks = ranked_stocks

                if dates_tracked:
                    final_date = dates_tracked[-1]
                    for t in list(active_positions.keys()):
                        try:
                            entry_date = active_positions[t]['entry_date']
                            entry_price = active_positions[t]['entry_price']
                            exit_price = df_daily[t].loc[:final_date].dropna().iloc[-1]
                            days_held = (final_date - entry_date).days
                            net_ret = ((exit_price - entry_price) / entry_price) - txn_cost_decimal
                            
                            completed_trades.append({
                                'Stock': t, 'Entry Date': entry_date.strftime('%Y-%m-%d'),
                                'Entry Price (₹)': round(entry_price, 2), 'Exit Date': final_date.strftime('%Y-%m-%d') + " (Active)",
                                'Exit Price (₹)': round(exit_price, 2), 'Holding Days': days_held,
                                'Net Return (%)': round(net_ret * 100, 2)
                            })
                        except Exception:
                            pass

                # --- METRICS & PLOTS ---
                if portfolio_returns and len(dates_tracked) > 1:
                    equity_df = pd.DataFrame(index=dates_tracked)
                    equity_df['Momentum Strategy (Net)'] = 100 * (1 + pd.Series(portfolio_returns)).cumprod().values
                    equity_df['Nifty 50 Benchmark'] = 100 * (1 + pd.Series(benchmark_returns)).cumprod().values
                    
                    st.line_chart(equity_df, height=400, color=["#00C853", "#FFA500"])
                    
                    final_port_val = equity_df['Momentum Strategy (Net)'].iloc[-1]
                    final_bench_val = equity_df['Nifty 50 Benchmark'].iloc[-1]
                    days_total = (dates_tracked[-1] - dates_tracked[0]).days
                    years = days_total / 365.25 if days_total > 0 else 1
                    cagr = ((final_port_val / 100) ** (1 / years)) - 1
                    bench_cagr = ((final_bench_val / 100) ** (1 / years)) - 1
                    
                    roll_max = equity_df['Momentum Strategy (Net)'].cummax()
                    drawdown = (equity_df['Momentum Strategy (Net)'] - roll_max) / roll_max
                    max_dd = drawdown.min() * 100
                    current_dd = drawdown.iloc[-1] * 100
                    
                    bench_roll_max = equity_df['Nifty 50 Benchmark'].cummax()
                    bench_drawdown = (equity_df['Nifty 50 Benchmark'] - bench_roll_max) / bench_roll_max
                    bench_max_dd = bench_drawdown.min() * 100
                    
                    rf_rate = 0.06
                    port_returns_series = pd.Series(portfolio_returns)
                    annual_factor = np.sqrt(periods_per_year)
                    std_dev = port_returns_series.std()
                    sharpe_ratio = (cagr - rf_rate) / (std_dev * annual_factor) if std_dev != 0 else 0
                    
                    downside_returns = port_returns_series[port_returns_series < 0]
                    downside_dev = downside_returns.std() * annual_factor
                    sortino_ratio = (cagr - rf_rate) / downside_dev if downside_dev > 0 else 0
                    calmar_ratio = cagr / abs(max_dd / 100) if max_dd != 0 else 0
                    
                    trades_df = pd.DataFrame(completed_trades)
                    if not trades_df.empty:
                        total_trades = len(trades_df)
                        avg_holding_days = int(trades_df['Holding Days'].mean())
                        winning_trades = trades_df[trades_df['Net Return (%)'] > 0]
                        losing_trades = trades_df[trades_df['Net Return (%)'] <= 0]
                        win_rate = (len(winning_trades) / total_trades) * 100
                        avg_win = winning_trades['Net Return (%)'].mean() if not winning_trades.empty else 0
                        avg_loss = losing_trades['Net Return (%)'].mean() if not losing_trades.empty else 0
                        gross_profit = winning_trades['Net Return (%)'].sum()
                        gross_loss = abs(losing_trades['Net Return (%)'].sum())
                        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0
                        payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
                        best_trade = trades_df['Net Return (%)'].max()
                        worst_trade = trades_df['Net Return (%)'].min()
                    else:
                        total_trades = avg_holding_days = win_rate = avg_win = avg_loss = profit_factor = payoff_ratio = best_trade = worst_trade = 0
                    
                    st.markdown("---")
                    st.subheader(f"📅 Non-Overlapping Sub-Period Analysis ({chunk_years}-Year Blocks)")
                    
                    chunk_days = int(chunk_years * 365.25)
                    chunk_data = []
                    start_idx = 0
                    
                    while start_idx < len(equity_df):
                        start_date = equity_df.index[start_idx]
                        target_end_date = start_date + timedelta(days=chunk_days)
                        chunk_df = equity_df.loc[start_date:target_end_date]
                        
                        if len(chunk_df) > 1:
                            actual_end_date = chunk_df.index[-1]
                            strat_ret = (chunk_df['Momentum Strategy (Net)'].iloc[-1] / chunk_df['Momentum Strategy (Net)'].iloc[0] - 1) * 100
                            bench_ret = (chunk_df['Nifty 50 Benchmark'].iloc[-1] / chunk_df['Nifty 50 Benchmark'].iloc[0] - 1) * 100
                            strat_dd = ((chunk_df['Momentum Strategy (Net)'] - chunk_df['Momentum Strategy (Net)'].cummax()) / chunk_df['Momentum Strategy (Net)'].cummax()).min() * 100
                            bench_dd = ((chunk_df['Nifty 50 Benchmark'] - chunk_df['Nifty 50 Benchmark'].cummax()) / chunk_df['Nifty 50 Benchmark'].cummax()).min() * 100
                            
                            chunk_data.append({
                                "Time Period": f"{start_date.strftime('%b %Y')} - {actual_end_date.strftime('%b %Y')}",
                                "Strategy Return (%)": round(strat_ret, 2),
                                "Nifty 50 Return (%)": round(bench_ret, 2),
                                "Strategy Max DD (%)": round(strat_dd, 2),
                                "Nifty Max DD (%)": round(bench_dd, 2)
                            })
                            
                        next_indices = np.where(equity_df.index > target_end_date)[0]
                        if len(next_indices) > 0:
                            start_idx = next_indices[0]
                        else:
                            break
                    
                    if chunk_data:
                        chunk_df_final = pd.DataFrame(chunk_data)
                        st.dataframe(chunk_df_final.style.highlight_max(subset=['Strategy Return (%)'], color='lightgreen')
                                                    .highlight_min(subset=['Strategy Max DD (%)'], color='lightcoral'), 
                                     use_container_width=True)
                    
                    st.markdown("---")
                    st.subheader(f"📈 Core Performance Analytics")
                    
                    st.markdown("**1. Return & Core Risk**")
                    r1_c1, r1_c2, r1_c3, r1_c4, r1_c5 = st.columns(5)
                    r1_c1.metric("🚀 Strategy CAGR", f"{round(cagr * 100, 2)} %")
                    r1_c2.metric("📉 Strategy Max DD", f"{round(max_dd, 2)} %")
                    r1_c3.metric("⚠️ Floating Drawdown", f"{round(current_dd, 2)} %")
                    r1_c4.metric("📈 Nifty 50 CAGR", f"{round(bench_cagr * 100, 2)} %")
                    r1_c5.metric("📉 Nifty Max DD", f"{round(bench_max_dd, 2)} %")
                    
                    st.markdown("**2. Advanced Quant Ratios**")
                    r2_c1, r2_c2, r2_c3, r2_c4, r2_c5 = st.columns(5)
                    r2_c1.metric("📊 Sharpe Ratio", f"{round(sharpe_ratio, 2)}")
                    r2_c2.metric("🟢 Sortino Ratio", f"{round(sortino_ratio, 2)}")
                    r2_c3.metric("🛡️ Calmar Ratio", f"{round(calmar_ratio, 2)}")
                    r2_c4.metric("⚖️ Payoff Ratio", f"{round(payoff_ratio, 2)}")
                    r2_c5.metric("💰 Profit Factor", f"{round(profit_factor, 2)}")

                    st.markdown("**3. Trade Execution Stats**")
                    r3_c1, r3_c2, r3_c3, r3_c4, r3_c5 = st.columns(5)
                    r3_c1.metric("🎯 Win Rate", f"{round(win_rate, 1)} %")
                    r3_c2.metric("📈 Avg Win", f"+{round(avg_win, 2)} %")
                    r3_c3.metric("📉 Avg Loss", f"{round(avg_loss, 2)} %")
                    r3_c4.metric("🏆 Best Trade", f"+{round(best_trade, 2)} %")
                    r3_c5.metric("🔄 Total Trades", f"{total_trades}")
                    
                    st.markdown("---")
                    st.subheader("📝 Per Script Total Returns & Trade Log")
                    with st.expander("Click to View Complete Trade History"):
                        st.dataframe(trades_df.sort_values(by='Entry Date', ascending=False), use_container_width=True)
                else:
                    st.error("Data fetched but simulation failed. Ensure 'STOCK SYMBOLS (1).csv' has valid NSE symbols.")
