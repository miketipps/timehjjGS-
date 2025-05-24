import backtrader as bt
import datetime
import pandas as pd
import numpy as np
import matplotlib # Keep for potential direct use or if Backtrader requires it
import sys

print("Imports successful")

DEFAULT_START_DATE = datetime.datetime(2023, 1, 1)
DEFAULT_END_DATE = datetime.datetime(2023, 1, 3) 

ASSET_SYMBOL = "ES" # Example, not directly used in this script version's main logic

TIMEFRAMES = [
    (bt.TimeFrame.Minutes, 1, "1min"),
    (bt.TimeFrame.Minutes, 5, "5min"),
    (bt.TimeFrame.Minutes, 15, "15min"),
    (bt.TimeFrame.Minutes, 30, "30min"),
    (bt.TimeFrame.Minutes, 60, "1h"),
    (bt.TimeFrame.Minutes, 240, "4h"),
    (bt.TimeFrame.Days, 1, "1d"),
    (bt.TimeFrame.Weeks, 1, "1w"),
]

def load_csv_data(data_path, start_date, end_date, bt_timeframe, bt_compression):
    try:
        data_feed = bt.feeds.GenericCSVData(
            dataname=data_path,
            fromdate=start_date,
            todate=end_date,
            dtformat=('%Y-%m-%d %H:%M:%S'),
            timeframe=bt_timeframe,
            compression=bt_compression,
            datetime=0, open=1, high=2, low=3, close=4, volume=5,
            openinterest=-1 # No open interest column in the CSV
        )
        return data_feed
    except FileNotFoundError:
        print(f"Error: Data file not found at {data_path}")
        sys.exit(1) # Exit if data file is critical and not found
    except Exception as e:
        print(f"Error loading data: {e}")
        sys.exit(1) # Exit on other data loading errors

# Indicator Definitions
class VWAP(bt.Indicator):
    lines = ('vwap',)
    params = (('period', 20),) 
    plotinfo = dict(subplot=False) 
    def __init__(self):
        self.addminperiod(self.p.period)
        typical_price = (self.datas[0].close + self.datas[0].high + self.datas[0].low) / 3.0
        pv = typical_price * self.datas[0].volume
        self.lines.vwap = bt.indicators.SumN(pv, period=self.p.period) / \
                          bt.indicators.SumN(self.datas[0].volume, period=self.p.period)

class Supertrend(bt.Indicator):
    lines = ('supertrend',)
    params = (('period', 7), ('multiplier', 3)) 
    plotinfo = dict(subplot=False) 
    def __init__(self):
        self.atr_val = bt.indicators.ATR(self.datas[0], period=self.p.period)
        self.median_price = (self.datas[0].high + self.datas[0].low) / 2.0
        self.prev_final_upper_band = 0.0
        self.prev_final_lower_band = 0.0
        self.trend = 1 # 1 for uptrend, -1 for downtrend
    def next(self):
        high = self.datas[0].high[0]
        low = self.datas[0].low[0]
        close = self.datas[0].close[0]
        atr = self.atr_val[0]
        basic_upper_band = self.median_price[0] + (self.p.multiplier * atr)
        basic_lower_band = self.median_price[0] - (self.p.multiplier * atr)
        if len(self) == 1: 
            self.prev_final_upper_band = basic_upper_band
            self.prev_final_lower_band = basic_lower_band
            if close > self.median_price[0]: 
                self.trend = 1
                self.lines.supertrend[0] = self.prev_final_lower_band
            else: 
                self.trend = -1
                self.lines.supertrend[0] = self.prev_final_upper_band
            return
        current_final_upper_band = self.prev_final_upper_band
        current_final_lower_band = self.prev_final_lower_band
        if basic_upper_band < self.prev_final_upper_band or self.datas[0].close[-1] > self.prev_final_upper_band:
            current_final_upper_band = basic_upper_band
        if basic_lower_band > self.prev_final_lower_band or self.datas[0].close[-1] < self.prev_final_lower_band:
            current_final_lower_band = basic_lower_band
        if self.trend == 1 and close < self.prev_final_lower_band: 
            self.trend = -1 
            self.lines.supertrend[0] = current_final_upper_band
        elif self.trend == -1 and close > self.prev_final_upper_band: 
            self.trend = 1 
            self.lines.supertrend[0] = current_final_lower_band
        else: 
            if self.trend == 1:
                self.lines.supertrend[0] = current_final_lower_band
            else: 
                self.lines.supertrend[0] = current_final_upper_band
        self.prev_final_upper_band = current_final_upper_band
        self.prev_final_lower_band = current_final_lower_band

class FlexibleStrategy(bt.Strategy):
    params = (
        ('atr_stop_multiplier', 2.0),
        ('atr_profit_multiplier', 4.0),
        ('es_point_value', 50.0),
        ('indicator_name', None), 
        ('indicator_params', None), 
        ('risk_per_trade_percent', 0.03), 
        ('atr_period_for_sltp', 14),
        ('doprint_log', False), 
    )

    def log(self, txt, dt=None, doprint=False): 
        if doprint or self.p.doprint_log:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.dataopen = self.datas[0].open
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        self.datavolume = self.datas[0].volume
        self.order = None
        self.buyprice = None
        self.buycomm = None
        self.active_sl_order = None
        self.active_tp_order = None
        self.current_indicator_signal = None
        self.atr_for_stoploss = None
        self.prev_supertrend_trend = 0 
        
        if self.p.atr_period_for_sltp and self.p.atr_period_for_sltp > 0:
            self.atr_for_stoploss = bt.indicators.ATR(self.datas[0], period=self.p.atr_period_for_sltp, plot=False)

        if not self.p.indicator_name:
            self.log('No indicator_name specified for the strategy.', doprint=True)
            return

        name = self.p.indicator_name
        params_dict = self.p.indicator_params if isinstance(self.p.indicator_params, dict) else {}
        IndicatorClass = None

        if name == 'SMACrossover' or name == 'EMACrossover':
            fast_period = params_dict.get('fast_period', 10)
            slow_period = params_dict.get('slow_period', 30)
            MA_Type = bt.indicators.SimpleMovingAverage if name == 'SMACrossover' else bt.indicators.ExponentialMovingAverage
            self.ma_fast = MA_Type(self.datas[0], period=fast_period)
            self.ma_slow = MA_Type(self.datas[0], period=slow_period)
            self.current_indicator_signal = bt.indicators.CrossOver(self.ma_fast, self.ma_slow, plot=False)
        elif name == 'MACD':
            self.current_indicator_signal = bt.indicators.MACD(self.datas[0], **params_dict) 
        elif name == 'OnBalanceVolume':
            IndicatorClass = getattr(bt.indicators, 'OnBalanceVolume', None) or \
                             getattr(bt.ind, 'OnBalanceVolume', None) or \
                             getattr(bt.ind, 'OBV', None)
            if IndicatorClass: self.current_indicator_signal = IndicatorClass(self.datas[0])
        elif name == 'DonchianChannels':
            IndicatorClass = getattr(bt.indicators, 'DonchianChannels', None) or \
                             getattr(bt.ind, 'DonchianChannels', None)
            if IndicatorClass: self.current_indicator_signal = IndicatorClass(self.datas[0], **params_dict)
        elif hasattr(bt.indicators, name): 
            IndicatorClass = getattr(bt.indicators, name)
            if IndicatorClass: self.current_indicator_signal = IndicatorClass(self.datas[0], **params_dict)
        elif hasattr(bt.ind, name): 
             IndicatorClass = getattr(bt.ind, name)
             if IndicatorClass: self.current_indicator_signal = IndicatorClass(self.datas[0], **params_dict)
        elif name == 'VWAP': 
            self.current_indicator_signal = VWAP(self.datas[0], **params_dict)
        elif name == 'Supertrend': 
            self.current_indicator_signal = Supertrend(self.datas[0], **params_dict)
        
        if self.current_indicator_signal is None and not (name == 'SMACrossover' or name == 'EMACrossover' or (IndicatorClass is None and (name == 'OnBalanceVolume' or name == 'DonchianChannels')) ):
             self.log(f"Indicator {name} not recognized or failed to load.", doprint=True)
        elif name not in ['SMACrossover', 'EMACrossover'] and self.current_indicator_signal is not None:
             self.log(f"Indicator {name} successfully initialized.")


    def notify_order(self, order):
        log_doprint = self.p.doprint_log 
        if order.status in [order.Submitted, order.Accepted]: return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Ref: {order.ref}, Size: {order.executed.size}, Price: {order.executed.price:.2f}', doprint=log_doprint)
                self.buyprice = order.executed.price; self.buycomm = order.executed.comm
                if hasattr(self, 'sl_price_to_set') and hasattr(self, 'tp_price_to_set'):
                    self.active_sl_order = self.sell(exectype=bt.Order.Stop, price=self.sl_price_to_set, size=self.position.size, transmit=False)
                    self.active_tp_order = self.sell(exectype=bt.Order.Limit, price=self.tp_price_to_set, size=self.position.size, transmit=True)
                    del self.sl_price_to_set; del self.tp_price_to_set
            elif order.issell():
                if self.active_sl_order and order.ref == self.active_sl_order.ref:
                    self.log(f'STOP LOSS EXECUTED, Ref: {order.ref}', doprint=log_doprint)
                    if self.active_tp_order: self.cancel(self.active_tp_order); self.active_tp_order = None
                    self.active_sl_order = None
                elif self.active_tp_order and order.ref == self.active_tp_order.ref:
                    self.log(f'TAKE PROFIT EXECUTED, Ref: {order.ref}', doprint=log_doprint)
                    if self.active_sl_order: self.cancel(self.active_sl_order); self.active_sl_order = None
                    self.active_tp_order = None
                elif self.position.size == 0:
                     self.log(f'SELL EXECUTED (Exit/Close), Ref: {order.ref}', doprint=log_doprint)
                     if self.active_sl_order: self.cancel(self.active_sl_order); self.active_sl_order = None
                     if self.active_tp_order: self.cancel(self.active_tp_order); self.active_tp_order = None
            self.bar_executed = len(self)
        elif order.status in [order.Canceled, order.Margin, order.Rejected, order.Expired]:
            self.log(f'Order {order.ref} Failed: {order.getstatusname()}', doprint=log_doprint)
            if self.active_sl_order and order.ref == self.active_sl_order.ref: self.active_sl_order = None
            if self.active_tp_order and order.ref == self.active_tp_order.ref: self.active_tp_order = None
        if self.order and self.order.ref == order.ref: self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed: return
        self.log(f'TRADE PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}', doprint=self.p.doprint_log)

    def next(self):
        log_doprint = self.p.doprint_log
        if self.order: return
        if self.current_indicator_signal is None: return
        if not self.atr_for_stoploss or len(self.atr_for_stoploss.lines.atr) == 0: return
        atr_value = self.atr_for_stoploss.lines.atr[0]
        if atr_value <= 0: return
        cash = self.broker.getvalue()
        risk_per_trade_abs = cash * self.p.risk_per_trade_percent
        stop_distance_points = self.p.atr_stop_multiplier * atr_value
        risk_per_contract = stop_distance_points * self.p.es_point_value
        if risk_per_contract <= 0: return
        size = int(risk_per_trade_abs / risk_per_contract)
        if size == 0: return

        buy_signal = False; sell_signal = False
        indicator_name = self.p.indicator_name

        if indicator_name == 'RSI':
            rsi_value = self.current_indicator_signal[0]
            if rsi_value < 30: buy_signal = True
            elif rsi_value > 70: sell_signal = True 
        elif indicator_name == 'SMACrossover' or indicator_name == 'EMACrossover':
            signal_val = self.current_indicator_signal[0]
            if signal_val == 1.0: buy_signal = True
            elif signal_val == -1.0: sell_signal = True
        elif indicator_name == 'MACD':
            if self.current_indicator_signal.macd[0] > self.current_indicator_signal.signal[0] and \
               self.current_indicator_signal.macd[-1] <= self.current_indicator_signal.signal[-1]: buy_signal = True
            elif self.current_indicator_signal.macd[0] < self.current_indicator_signal.signal[0] and \
                 self.current_indicator_signal.macd[-1] >= self.current_indicator_signal.signal[-1]: sell_signal = True
        elif indicator_name == 'BollingerBands':
            if self.dataclose[0] < self.current_indicator_signal.lines.bot[0]: buy_signal = True
            elif self.dataclose[0] > self.current_indicator_signal.lines.top[0]: sell_signal = True
        elif indicator_name == 'OnBalanceVolume':
            obv_line = None
            if hasattr(self.current_indicator_signal.lines, 'onbalancevolume'): 
                obv_line = self.current_indicator_signal.lines.onbalancevolume
            elif hasattr(self.current_indicator_signal.lines, 'obv'): # Fallback for OBV alias
                obv_line = self.current_indicator_signal.lines.obv
            elif hasattr(self.current_indicator_signal.lines, 'volume'): # another possible name
                 obv_line = self.current_indicator_signal.lines.volume
            else: # Default to first line if specific names are not found
                obv_line = self.current_indicator_signal.lines[0]

            if obv_line is not None and len(obv_line) > 1: 
                if obv_line[0] > obv_line[-1]: buy_signal = True
                elif obv_line[0] < obv_line[-1] and self.position: sell_signal = True
        elif indicator_name == 'Supertrend':
            st_val = self.current_indicator_signal.lines.supertrend[0]
            current_supertrend_trend_val = self.current_indicator_signal.trend
            if current_supertrend_trend_val == 1 and self.prev_supertrend_trend == -1: buy_signal = True
            elif current_supertrend_trend_val == -1 and self.prev_supertrend_trend == 1: sell_signal = True
            self.prev_supertrend_trend = current_supertrend_trend_val
        
        if not self.position and buy_signal:
            entry_price = self.dataclose[0] 
            sl_price = entry_price - (self.p.atr_stop_multiplier * atr_value)
            tp_price = entry_price + (self.p.atr_profit_multiplier * atr_value)
            if tp_price <= entry_price: tp_price = entry_price + (entry_price - sl_price)
            if tp_price <= entry_price or sl_price >= entry_price: return
            self.log(f'BUY CREATE, Size: {size}, Entry: {entry_price:.2f}, SL: {sl_price:.2f}, TP: {tp_price:.2f}', doprint=log_doprint)
            self.sl_price_to_set = sl_price; self.tp_price_to_set = tp_price   
            self.order = self.buy(size=size)
        elif self.position and sell_signal:
            self.log(f'SELL CREATE (Exit Signal), Size: {self.position.size}, Price: {self.dataclose[0]:.2f}', doprint=log_doprint)
            self.order = self.close() 

    def stop(self):
        self.log(f'--- Strategy End --- Indicator: {self.p.indicator_name}, Params: {str(self.p.indicator_params)}, Ending Value: {self.broker.getvalue():.2f}', doprint=self.p.doprint_log)

if __name__ == '__main__':
    INDICATOR_CONFIGS = []
    for p in [7, 14, 21]: INDICATOR_CONFIGS.append({'name': 'RSI', 'params': {'period': p}})
    INDICATOR_CONFIGS.append({'name': 'MACD', 'params': {'period_me1': 12, 'period_me2': 26, 'period_signal': 9}})
    INDICATOR_CONFIGS.append({'name': 'MACD', 'params': {'period_me1': 10, 'period_me2': 20, 'period_signal': 7}})
    for f, s in [(5,15), (10,30), (20,50)]: INDICATOR_CONFIGS.append({'name': 'SMACrossover', 'params': {'fast_period': f, 'slow_period': s}})
    for f, s in [(5,15), (10,30), (20,50)]: INDICATOR_CONFIGS.append({'name': 'EMACrossover', 'params': {'fast_period': f, 'slow_period': s}})
    for p in [14, 20, 30]:
        for d in [2.0, 2.5]: INDICATOR_CONFIGS.append({'name': 'BollingerBands', 'params': {'period': p, 'devfactor': d}})
    for p in [7, 14, 21]: INDICATOR_CONFIGS.append({'name': 'ADX', 'params': {'period': p}})
    INDICATOR_CONFIGS.append({'name': 'OnBalanceVolume', 'params': {}})
    for p in [14, 20, 30]: INDICATOR_CONFIGS.append({'name': 'VWAP', 'params': {'period': p}})
    for p in [14, 20, 30]: INDICATOR_CONFIGS.append({'name': 'DonchianChannels', 'params': {'period': p}})
    for p in [7, 10, 14]:
        for m in [2.5, 3.0, 3.5]: INDICATOR_CONFIGS.append({'name': 'Supertrend', 'params': {'period': p, 'multiplier': m}})

    ATR_SLTP_PERIODS = [10, 14, 20]
    all_results = []
    initial_capital = 100000.0
    data_path = 'es_data.csv'
    main_loop_doprint_log = False 

    for tf_config in TIMEFRAMES:
        bt_tf, bt_comp, tf_name = tf_config
        print(f"\n--- Testing Timeframe: {tf_name} ---")
        for ind_config in INDICATOR_CONFIGS:
            indicator_name = ind_config['name']
            indicator_params = ind_config['params']
            for atr_sltp_period_val in ATR_SLTP_PERIODS:
                print(f"  Running: TF={tf_name}, Ind={indicator_name}, Params={indicator_params}, ATR_SLTP={atr_sltp_period_val}")
                current_run_results = {
                    'Timeframe': tf_name, 'Indicator': indicator_name, 'Parameters': str(indicator_params),
                    'ATR_SLTP_Period': atr_sltp_period_val, 'Final_Value': 0, 'Sharpe_Ratio': 0, 
                    'Max_Drawdown': 0, 'Total_Trades': 0, 'Hit_Rate': 0, 'Total_Net_PnL': 0,
                    'Profit_Factor': 0, 'Error': ''
                }
                try:
                    cerebro = bt.Cerebro(stdstats=False) 
                    data_feed = load_csv_data(data_path, DEFAULT_START_DATE, DEFAULT_END_DATE, bt_tf, bt_comp)
                    cerebro.adddata(data_feed)
                    cerebro.addstrategy(FlexibleStrategy, 
                                        indicator_name=indicator_name, indicator_params=indicator_params, 
                                        atr_period_for_sltp=atr_sltp_period_val,
                                        risk_per_trade_percent=0.03, atr_stop_multiplier=2.0,
                                        atr_profit_multiplier=4.0, es_point_value=50.0,
                                        doprint_log=main_loop_doprint_log)
                    cerebro.broker.setcash(initial_capital)
                    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe') 
                    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
                    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
                    run_results = cerebro.run()
                    strategy_instance = run_results[0]
                    current_run_results['Final_Value'] = cerebro.broker.getvalue()
                    sharpe_analysis = strategy_instance.analyzers.getbyname('sharpe').get_analysis()
                    current_run_results['Sharpe_Ratio'] = sharpe_analysis.get('sharperatio', 0.0) if sharpe_analysis else 0.0
                    drawdown_analysis = strategy_instance.analyzers.getbyname('drawdown').get_analysis()
                    current_run_results['Max_Drawdown'] = drawdown_analysis.max.get('drawdown', 0.0) if drawdown_analysis.max else 0.0
                    trade_analysis = strategy_instance.analyzers.getbyname('trades').get_analysis()
                    current_run_results['Total_Trades'] = trade_analysis.get('total', {}).get('closed', 0)
                    won_trades = trade_analysis.get('won', {}).get('total', 0)
                    current_run_results['Hit_Rate'] = (won_trades / current_run_results['Total_Trades'] * 100) if current_run_results['Total_Trades'] > 0 else 0.0
                    current_run_results['Total_Net_PnL'] = trade_analysis.get('pnl', {}).get('net', {}).get('total', 0.0)
                    gross_won = trade_analysis.get('won', {}).get('pnl', {}).get('total', 0.0)
                    gross_lost_abs = abs(trade_analysis.get('lost', {}).get('pnl', {}).get('total', 0.0))
                    if gross_lost_abs > 0: current_run_results['Profit_Factor'] = gross_won / gross_lost_abs
                    elif gross_won > 0: current_run_results['Profit_Factor'] = 99999 
                    else: current_run_results['Profit_Factor'] = 0.0
                    print(f"    Completed: PnL={current_run_results['Total_Net_PnL']:.2f}, Trades={current_run_results['Total_Trades']}")
                except Exception as e:
                    print(f"    Error during backtest run: {e}")
                    current_run_results['Error'] = str(e)
                all_results.append(current_run_results)
                del cerebro; del data_feed
    print("\n--- Backtesting Campaign Complete ---")
    if not all_results:
        print("No results to display.")
    else:
        results_df = pd.DataFrame(all_results)
        results_df['Sharpe_Ratio'] = pd.to_numeric(results_df['Sharpe_Ratio'], errors='coerce').fillna(0.0)
        results_df['Profit_Factor'] = pd.to_numeric(results_df['Profit_Factor'], errors='coerce').fillna(0.0)
        results_df['Profit_Factor'].replace(float('inf'), 99999, inplace=True)
        results_df['Sort_Sharpe'] = results_df.apply(lambda row: row['Sharpe_Ratio'] if not row['Error'] else -99999, axis=1)
        results_df['Sort_Profit_Factor'] = results_df.apply(lambda row: row['Profit_Factor'] if not row['Error'] else -1, axis=1)
        sorted_results = results_df.sort_values(by=['Sort_Sharpe', 'Sort_Profit_Factor'], ascending=[False, False])
        print("\n--- Top 20 Performing Strategy Configurations ---")
        print(sorted_results[['Timeframe', 'Indicator', 'Parameters', 'ATR_SLTP_Period', 'Final_Value', 'Sharpe_Ratio', 'Max_Drawdown', 'Total_Trades', 'Hit_Rate', 'Total_Net_PnL', 'Profit_Factor', 'Error']].head(20).to_string())
