import backtrader as bt
import datetime
import pandas as pd
import numpy as np
import matplotlib # Keep for potential direct use or if Backtrader requires it
import matplotlib.pyplot as plt # For custom plotting
import sys
import ast # For converting string representation of dict back to dict
import random # For Monte Carlo Simulation

# print("Imports successful")

DEFAULT_START_DATE = datetime.datetime(2023, 1, 1) 
DEFAULT_END_DATE = datetime.datetime(2023, 1, 3)   

ASSET_SYMBOL = "ES" 

TIMEFRAMES = [
    (bt.TimeFrame.Minutes, 1, "1min"), (bt.TimeFrame.Minutes, 5, "5min"),
    (bt.TimeFrame.Minutes, 15, "15min"), (bt.TimeFrame.Minutes, 30, "30min"),
    (bt.TimeFrame.Minutes, 60, "1h"), (bt.TimeFrame.Minutes, 240, "4h"),
    (bt.TimeFrame.Days, 1, "1d"), (bt.TimeFrame.Weeks, 1, "1w"),
]

def load_csv_data(data_path, start_date, end_date, bt_timeframe, bt_compression):
    try:
        data_feed = bt.feeds.GenericCSVData(
            dataname=data_path, fromdate=start_date, todate=end_date,
            dtformat=('%Y-%m-%d %H:%M:%S'), timeframe=bt_timeframe,
            compression=bt_compression, datetime=0, open=1, high=2, low=3, 
            close=4, volume=5, openinterest=-1 
        )
        return data_feed
    except FileNotFoundError: print(f"Error: Data file not found at {data_path}"); sys.exit(1) 
    except Exception as e: print(f"Error loading data: {e}"); sys.exit(1) 

class VWAP(bt.Indicator):
    lines = ('vwap',) # Corrected: comma outside string
    params = (('period', 20),); plotinfo = dict(subplot=False) 
    def __init__(self):
        self.addminperiod(self.p.period)
        tp = (self.datas[0].close + self.datas[0].high + self.datas[0].low) / 3.0
        pv = tp * self.datas[0].volume
        self.lines.vwap = bt.indicators.SumN(pv, period=self.p.period) / \
                          bt.indicators.SumN(self.datas[0].volume, period=self.p.period)

class Supertrend(bt.Indicator):
    lines = ('supertrend',) # Corrected: This was likely already correct, but ensuring tuple format
    params = (('period', 7), ('multiplier', 3)); plotinfo = dict(subplot=False) 
    def __init__(self):
        self.atr_val = bt.indicators.ATR(self.datas[0], period=self.p.period)
        self.median_price = (self.datas[0].high + self.datas[0].low) / 2.0
        self.prev_final_upper_band = 0.0; self.prev_final_lower_band = 0.0; self.trend = 1 
    def next(self):
        hi, lo, cl = self.datas[0].high[0], self.datas[0].low[0], self.datas[0].close[0]; atr = self.atr_val[0]
        b_upper = self.median_price[0] + (self.p.multiplier*atr); b_lower = self.median_price[0] - (self.p.multiplier*atr)
        if len(self) == 1: 
            self.prev_final_upper_band = b_upper; self.prev_final_lower_band = b_lower
            self.trend = 1 if cl > self.median_price[0] else -1
            self.l.supertrend[0] = self.prev_final_lower_band if self.trend == 1 else self.prev_final_upper_band
            return
        f_upper = self.prev_final_upper_band; f_lower = self.prev_final_lower_band
        if b_upper < self.prev_final_upper_band or self.datas[0].close[-1] > self.prev_final_upper_band: f_upper = b_upper
        if b_lower > self.prev_final_lower_band or self.datas[0].close[-1] < self.prev_final_lower_band: f_lower = b_lower
        if self.trend == 1 and cl < self.prev_final_lower_band: self.trend = -1 
        elif self.trend == -1 and cl > self.prev_final_upper_band: self.trend = 1
        self.l.supertrend[0] = f_lower if self.trend == 1 else f_upper
        self.prev_final_upper_band = f_upper; self.prev_final_lower_band = f_lower

class FlexibleStrategy(bt.Strategy):
    params = (('atr_stop_multiplier',2.0),('atr_profit_multiplier',4.0),('es_point_value',50.0),
              ('indicator_name',None),('indicator_params',None),('risk_per_trade_percent',0.03),
              ('atr_period_for_sltp',14),('doprint_log',False))
    def log(self,txt,dt=None,doprint=False):
        if doprint or self.p.doprint_log: print(f'{(dt or self.datas[0].datetime.date(0)).isoformat()} {txt}')
    def __init__(self):
        self.dataclose=self.datas[0].close;self.order=None;self.prev_supertrend_trend=0
        if self.p.atr_period_for_sltp and self.p.atr_period_for_sltp>0:
            self.atr_for_stoploss=bt.indicators.ATR(self.datas[0],period=self.p.atr_period_for_sltp,plot=False)
        if not self.p.indicator_name:self.log('No indicator_name specified',doprint=True);return
        name=self.p.indicator_name;params_dict=self.p.indicator_params if isinstance(self.p.indicator_params,dict)else{}
        IndicatorClass=None
        if name=='SMACrossover' or name=='EMACrossover':
            MA_Type=bt.indicators.SimpleMovingAverage if name=='SMACrossover' else bt.indicators.ExponentialMovingAverage
            self.ma_fast=MA_Type(self.datas[0],period=params_dict.get('fast_period',10))
            self.ma_slow=MA_Type(self.datas[0],period=params_dict.get('slow_period',30))
            self.current_indicator_signal=bt.indicators.CrossOver(self.ma_fast,self.ma_slow,plot=False)
        elif name=='MACD':self.current_indicator_signal=bt.indicators.MACD(self.datas[0],**params_dict)
        elif name=='OnBalanceVolume':
            IndicatorClass=getattr(bt.indicators,'OnBalanceVolume',None) or getattr(bt.ind,'OnBalanceVolume',None) or getattr(bt.ind,'OBV',None)
            if IndicatorClass:self.current_indicator_signal=IndicatorClass(self.datas[0])
        elif name=='DonchianChannels':
            IndicatorClass=getattr(bt.indicators,'DonchianChannels',None) or getattr(bt.ind,'DonchianChannels',None)
            if IndicatorClass:self.current_indicator_signal=IndicatorClass(self.datas[0],**params_dict)
        elif hasattr(bt.indicators,name):IndicatorClass=getattr(bt.indicators,name)
        elif hasattr(bt.ind,name):IndicatorClass=getattr(bt.ind,name)
        if IndicatorClass and name not in ['OnBalanceVolume','DonchianChannels','SMACrossover','EMACrossover','MACD']:
            self.current_indicator_signal=IndicatorClass(self.datas[0],**params_dict)
        elif name=='VWAP':self.current_indicator_signal=VWAP(self.datas[0],**params_dict)
        elif name=='Supertrend':self.current_indicator_signal=Supertrend(self.datas[0],**params_dict)
        if name not in ['SMACrossover','EMACrossover']:
            if self.current_indicator_signal is None:self.log(f"Indicator {name} not recognized/loaded",doprint=True)
    def notify_order(self,order):
        dp=self.p.doprint_log
        if order.status in [order.Submitted,order.Accepted]:return
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXEC, Ref:{order.ref},Size:{order.executed.size},Price:{order.executed.price:.2f}',doprint=dp)
                self.buyprice=order.executed.price;self.buycomm=order.executed.comm
                if hasattr(self,'sl_price_to_set') and hasattr(self,'tp_price_to_set'):
                    self.active_sl_order=self.sell(exectype=bt.Order.Stop,price=self.sl_price_to_set,size=self.position.size,transmit=False)
                    self.active_tp_order=self.sell(exectype=bt.Order.Limit,price=self.tp_price_to_set,size=self.position.size,transmit=True)
                    del self.sl_price_to_set;del self.tp_price_to_set
            elif order.issell():
                ref=order.ref
                if self.active_sl_order and ref==self.active_sl_order.ref:
                    self.log(f'STOP LOSS, Ref:{ref}',doprint=dp);self.active_sl_order=None
                    if self.active_tp_order:self.cancel(self.active_tp_order);self.active_tp_order=None
                elif self.active_tp_order and ref==self.active_tp_order.ref:
                    self.log(f'TAKE PROFIT, Ref:{ref}',doprint=dp);self.active_tp_order=None
                    if self.active_sl_order:self.cancel(self.active_sl_order);self.active_sl_order=None
                elif self.position.size==0:
                     self.log(f'SELL EXIT, Ref:{ref}',doprint=dp)
                     if self.active_sl_order:self.cancel(self.active_sl_order);self.active_sl_order=None
                     if self.active_tp_order:self.cancel(self.active_tp_order);self.active_tp_order=None
            self.bar_executed=len(self)
        elif order.status in [order.Canceled,order.Margin,order.Rejected,order.Expired]:
            self.log(f'Order {order.ref} Fail:{order.getstatusname()}',doprint=dp)
            if self.active_sl_order and order.ref==self.active_sl_order.ref:self.active_sl_order=None
            if self.active_tp_order and order.ref==self.active_tp_order.ref:self.active_tp_order=None
        if self.order and self.order.ref==order.ref:self.order=None
    def notify_trade(self,trade):
        if not trade.isclosed:return
        self.log(f'TRADE PNL, Gross:{trade.pnl:.2f},Net:{trade.pnlcomm:.2f}',doprint=self.p.doprint_log)
    def next(self):
        if self.order:return
        if self.current_indicator_signal is None:return
        if not self.atr_for_stoploss or len(self.atr_for_stoploss.lines.atr)==0:return
        atr_val=self.atr_for_stoploss.lines.atr[0]
        if atr_val<=0:return
        cash=self.broker.getvalue();risk_abs=cash*self.p.risk_per_trade_percent
        stop_dist=self.p.atr_stop_multiplier*atr_val;risk_contract=stop_dist*self.p.es_point_value
        if risk_contract<=0:return
        size=int(risk_abs/risk_contract)
        if size==0:return
        buy_sig=False;sell_sig=False;name=self.p.indicator_name
        if name=='RSI':
            if self.current_indicator_signal[0]<30:buy_sig=True
            elif self.current_indicator_signal[0]>70:sell_sig=True
        elif name=='SMACrossover' or name=='EMACrossover':
            if self.current_indicator_signal[0]==1.0:buy_sig=True
            elif self.current_indicator_signal[0]==-1.0:sell_sig=True
        elif name=='MACD':
            if self.current_indicator_signal.macd[0]>self.current_indicator_signal.signal[0] and self.current_indicator_signal.macd[-1]<=self.current_indicator_signal.signal[-1]:buy_sig=True
            elif self.current_indicator_signal.macd[0]<self.current_indicator_signal.signal[0] and self.current_indicator_signal.macd[-1]>=self.current_indicator_signal.signal[-1]:sell_sig=True
        elif name=='BollingerBands':
            if self.dataclose[0]<self.current_indicator_signal.lines.bot[0]:buy_sig=True
            elif self.dataclose[0]>self.current_indicator_signal.lines.top[0]:sell_sig=True
        elif name == 'OnBalanceVolume':
            obv_l=None
            if hasattr(self.current_indicator_signal.lines,'onbalancevolume'):obv_l=self.current_indicator_signal.lines.onbalancevolume
            elif hasattr(self.current_indicator_signal.lines,'obv'):obv_l=self.current_indicator_signal.lines.obv
            elif self.current_indicator_signal.lines:obv_l=self.current_indicator_signal.lines[0]
            if obv_l and len(obv_l)>1:
                if obv_l[0]>obv_l[-1]:buy_sig=True
                elif obv_l[0]<obv_l[-1] and self.position:sell_sig=True
        elif name=='Supertrend':
            st_val=self.current_indicator_signal.lines.supertrend[0];curr_st_trend=self.current_indicator_signal.trend
            if curr_st_trend==1 and self.prev_supertrend_trend==-1:buy_sig=True
            elif curr_st_trend==-1 and self.prev_supertrend_trend==1:sell_sig=True
            self.prev_supertrend_trend=curr_st_trend
        if not self.position and buy_sig:
            entry_p=self.dataclose[0];sl_p=entry_p-(self.p.atr_stop_multiplier*atr_val);tp_p=entry_p+(self.p.atr_profit_multiplier*atr_val)
            if tp_p<=entry_p:tp_p=entry_p+(entry_p-sl_p)
            if tp_p<=entry_p or sl_p>=entry_p:return
            self.log(f'BUY CREATE,Size:{size},Price:{entry_p:.2f},SL:{sl_p:.2f},TP:{tp_p:.2f}',doprint=self.p.doprint_log)
            self.sl_price_to_set=sl_p;self.tp_price_to_set=tp_p;self.order=self.buy(size=size)
        elif self.position and sell_sig:
            self.log(f'SELL CREATE (Exit),Size:{self.position.size},Price:{self.dataclose[0]:.2f}',doprint=self.p.doprint_log)
            self.order=self.close()
    def stop(self):self.log(f'Strategy End:Ind={self.p.indicator_name},Params={str(self.p.indicator_params)},EndVal:{self.broker.getvalue():.2f}',doprint=self.p.doprint_log)

def run_single_backtest(data_path, start_date, end_date, timeframe_enum, timeframe_comp, 
                        strategy_class, strategy_params, initial_capital):
    cerebro = bt.Cerebro(stdstats=False)
    data = load_csv_data(data_path, start_date, end_date, timeframe_enum, timeframe_comp)
    results_output = {
        'Final_Value': initial_capital, 'Sharpe_Ratio': 0.0, 'Max_Drawdown': 0.0,
        'Total_Trades': 0, 'Hit_Rate': 0.0, 'Total_Net_PnL': 0.0,
        'Profit_Factor': 0.0, 'Error': '', 
        'ATR_SLTP_Used': strategy_params.get('atr_period_for_sltp'),
        'trades_pnl_list': [] 
    }
    if data is None: 
        results_output['Error'] = 'Data loading failed'
        return results_output

    cerebro.adddata(data)
    cerebro.addstrategy(strategy_class, **strategy_params) 
    cerebro.broker.setcash(initial_capital)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    try:
        run_results = cerebro.run()
        if run_results and run_results[0]:
            strategy_instance = run_results[0]
            results_output['Final_Value'] = cerebro.broker.getvalue()
            sharpe_analysis = strategy_instance.analyzers.getbyname('sharpe').get_analysis()
            results_output['Sharpe_Ratio'] = sharpe_analysis.get('sharperatio',0.0) if sharpe_analysis else 0.0
            if results_output['Sharpe_Ratio'] is None: results_output['Sharpe_Ratio'] = 0.0
            
            drawdown_analysis = strategy_instance.analyzers.getbyname('drawdown').get_analysis()
            results_output['Max_Drawdown'] = drawdown_analysis.max.get('drawdown',0.0) if drawdown_analysis.max else 0.0
            
            trade_analysis = strategy_instance.analyzers.getbyname('trades').get_analysis() 
            results_output['Total_Trades'] = trade_analysis.get('total',{}).get('closed',0)
            won_trades = trade_analysis.get('won',{}).get('total',0)
            results_output['Hit_Rate'] = (won_trades/results_output['Total_Trades']*100) if results_output['Total_Trades']>0 else 0.0
            results_output['Total_Net_PnL'] = trade_analysis.get('pnl',{}).get('net',{}).get('total',0.0)
            
            if 'pnl' in trade_analysis and 'net' in trade_analysis['pnl'] and 'all' in trade_analysis['pnl']['net']:
                 results_output['trades_pnl_list'] = trade_analysis.pnl.net.all 
            else: results_output['trades_pnl_list'] = []

            gross_won = trade_analysis.get('won',{}).get('pnl',{}).get('total',0.0)
            gross_lost_abs = abs(trade_analysis.get('lost',{}).get('pnl',{}).get('total',0.0))
            if gross_lost_abs > 0: results_output['Profit_Factor'] = gross_won / gross_lost_abs
            elif gross_won > 0: results_output['Profit_Factor'] = 99999 
            else: results_output['Profit_Factor'] = 0.0
    except Exception as e: results_output['Error'] = str(e)
    del cerebro; del data
    return results_output

if __name__ == '__main__':
    ENABLE_PLOTTING = True # Main switch for all plotting

    INDICATOR_CONFIGS = [] 
    for p in [7,14,21]: INDICATOR_CONFIGS.append({'name':'RSI','params':{'period':p}})
    INDICATOR_CONFIGS.append({'name':'MACD','params':{'period_me1':12,'period_me2':26,'period_signal':9}})
    INDICATOR_CONFIGS.append({'name':'MACD','params':{'period_me1':10,'period_me2':20,'period_signal':7}})
    for f,s in [(5,15),(10,30),(20,50)]: INDICATOR_CONFIGS.append({'name':'SMACrossover','params':{'fast_period':f,'slow_period':s}})
    for f,s in [(5,15),(10,30),(20,50)]: INDICATOR_CONFIGS.append({'name':'EMACrossover','params':{'fast_period':f,'slow_period':s}})
    for p in [14,20,30]:
        for d in [2.0,2.5]: INDICATOR_CONFIGS.append({'name':'BollingerBands','params':{'period':p,'devfactor':d}})
    for p in [7,14,21]: INDICATOR_CONFIGS.append({'name':'ADX','params':{'period':p}})
    INDICATOR_CONFIGS.append({'name':'OnBalanceVolume','params':{}})
    for p in [14,20,30]: INDICATOR_CONFIGS.append({'name':'VWAP','params':{'period':p}})
    for p in [14,20,30]: INDICATOR_CONFIGS.append({'name':'DonchianChannels','params':{'period':p}})
    for p in [7,10,14]:
        for m in [2.5,3.0,3.5]: INDICATOR_CONFIGS.append({'name':'Supertrend','params':{'period':p,'multiplier':m}})
    ATR_SLTP_PERIODS=[10,14,20];all_results=[];initial_capital=100000.0;data_path='es_data.csv';main_loop_doprint_log=False
    
    for tf_config in TIMEFRAMES:
        bt_tf_enum,bt_comp_val,tf_name_str=tf_config;print(f"\n--- Testing Timeframe: {tf_name_str} ---")
        for ind_config in INDICATOR_CONFIGS:
            indicator_name_str=ind_config['name'];indicator_params_dict=ind_config['params']
            for atr_sltp_val in ATR_SLTP_PERIODS:
                print(f"  Running Opt: TF={tf_name_str}, Ind={indicator_name_str}, Params={indicator_params_dict}, ATR_SLTP={atr_sltp_val}")
                strategy_params_for_run={'indicator_name':indicator_name_str,'indicator_params':indicator_params_dict,
                                         'atr_period_for_sltp':atr_sltp_val,'risk_per_trade_percent':0.03,
                                         'atr_stop_multiplier':2.0,'atr_profit_multiplier':4.0,
                                         'es_point_value':50.0,'doprint_log':main_loop_doprint_log}
                run_metrics=run_single_backtest(data_path,DEFAULT_START_DATE,DEFAULT_END_DATE,
                                                bt_tf_enum,bt_comp_val,FlexibleStrategy,
                                                strategy_params_for_run,initial_capital)
                current_run_summary={'Timeframe':tf_name_str,'Indicator':indicator_name_str,
                                     'Parameters':str(indicator_params_dict),'ATR_SLTP_Period':atr_sltp_val,**run_metrics}
                all_results.append(current_run_summary)
                print(f"    Opt Completed: PnL={current_run_summary['Total_Net_PnL']:.2f}, Trades={current_run_summary['Total_Trades']}, Error: {current_run_summary['Error']}")
    
    print("\n--- Backtesting Campaign Complete ---")
    if not all_results:print("No results from optimization to display or use for WFA.")
    else:
        results_df=pd.DataFrame(all_results)
        results_df['Sharpe_Ratio']=pd.to_numeric(results_df['Sharpe_Ratio'],errors='coerce').fillna(0.0)
        results_df['Profit_Factor']=pd.to_numeric(results_df['Profit_Factor'],errors='coerce').fillna(0.0)
        results_df['Profit_Factor'].replace(float('inf'),99999,inplace=True)
        results_df['Sort_Sharpe']=results_df.apply(lambda row:row['Sharpe_Ratio'] if not row['Error'] else -99999,axis=1)
        results_df['Sort_Profit_Factor']=results_df.apply(lambda row:row['Profit_Factor'] if not row['Error'] else -1,axis=1)
        sorted_results=results_df.sort_values(by=['Sort_Sharpe','Sort_Profit_Factor'],ascending=[False,False])
        print("\n--- Top 20 Performing Strategy Configurations (from initial optimization) ---")
        print(sorted_results[['Timeframe','Indicator','Parameters','ATR_SLTP_Period','Final_Value','Sharpe_Ratio','Max_Drawdown','Total_Trades','Hit_Rate','Total_Net_PnL','Profit_Factor','Error']].head(20).to_string())
        
        top_n_configs=[]
        if not sorted_results.empty:
            N_TOP_STRATEGIES=3
            successful_runs=sorted_results[sorted_results['Error']==''].copy()
            if successful_runs.empty:print("\nNo successful strategy configurations from optimization to select top N for WFA.")
            else:
                top_n_df=successful_runs.head(N_TOP_STRATEGIES)
                print(f"\n--- Extracting Top {min(N_TOP_STRATEGIES,len(top_n_df))} Strategy Configurations for WFA ---")
                for index,row in top_n_df.iterrows():
                    tf_name=row['Timeframe']
                    current_tf_details=next((item for item in TIMEFRAMES if item[2]==tf_name),None)
                    if not current_tf_details:print(f"    Skipping row {index} due to TF lookup error.");continue
                    try:indicator_params_dict=ast.literal_eval(row['Parameters'])
                    except ValueError:print(f"    Skipping row {index} due to param conversion error.");continue
                    base_strategy_params={'indicator_name':row['Indicator'],'indicator_params':indicator_params_dict,
                                          'atr_period_for_sltp':row['ATR_SLTP_Period'],
                                          'risk_per_trade_percent':0.03,'atr_stop_multiplier':2.0,
                                          'atr_profit_multiplier':4.0,'es_point_value':50.0,
                                          'doprint_log':main_loop_doprint_log}
                    top_n_configs.append({'tf_name':tf_name,'bt_timeframe':current_tf_details[0],
                                          'bt_compression':current_tf_details[1],'base_strategy_params':base_strategy_params,
                                          'sharpe_ratio':row['Sharpe_Ratio'],'profit_factor':row['Profit_Factor'],
                                          'total_pnl':row['Total_Net_PnL'],'total_trades':row['Total_Trades']})
                    print(f"  Extracted Config {len(top_n_configs)}: TF={tf_name}, Ind={row['Indicator']}, Params={indicator_params_dict}, ATR={row['ATR_SLTP_Period']}")
        
        if not top_n_configs:
            # Corrected Syntax Error from previous turn (moved print to new line)
            print("\nNo top configurations extracted from optimization, skipping Walk-Forward Analysis and Monte Carlo Simulation.")
        else:
            # --- Simplified Walk-Forward Analysis ---
            chosen_config_details_for_wfa = top_n_configs[0] 
            base_params_for_wfa = chosen_config_details_for_wfa['base_strategy_params']
            print(f"\n--- Walk-Forward Analysis for Top Strategy ---")
            print(f"Base Config for WFA: TF={chosen_config_details_for_wfa['tf_name']}, "
                  f"Ind={base_params_for_wfa['indicator_name']}, "
                  f"BaseParams={base_params_for_wfa['indicator_params']}, "
                  f"BaseATR_SLTP={base_params_for_wfa['atr_period_for_sltp']}")
            wfa_periods=[
                {'name':'WFA_P1','is_start':datetime.datetime(2023,1,1,9,30,0),'is_end':datetime.datetime(2023,1,1,9,39,59),'oos_start':datetime.datetime(2023,1,1,9,40,0),'oos_end':datetime.datetime(2023,1,1,9,49,59)},
                {'name':'WFA_P2','is_start':datetime.datetime(2023,1,1,9,35,0),'is_end':datetime.datetime(2023,1,1,9,44,59),'oos_start':datetime.datetime(2023,1,1,9,45,0),'oos_end':datetime.datetime(2023,1,2,9,34,59)},
                {'name':'WFA_P3','is_start':datetime.datetime(2023,1,1,9,40,0),'is_end':datetime.datetime(2023,1,1,9,49,59),'oos_start':datetime.datetime(2023,1,2,9,30,0),'oos_end':datetime.datetime(2023,1,2,9,39,59)}
            ]
            wfa_all_oos_metrics=[];base_atr_sltp_from_chosen_config=base_params_for_wfa['atr_period_for_sltp']
            atr_sltp_variations=sorted(list(set([max(5,base_atr_sltp_from_chosen_config-4),max(5,base_atr_sltp_from_chosen_config),max(5,base_atr_sltp_from_chosen_config+4)])))
            for i,period_def in enumerate(wfa_periods):
                print(f"\n  WFA Segment {i+1}: {period_def['name']}")
                print(f"    In-Sample Period: {period_def['is_start']} to {period_def['is_end']}")
                best_is_atr_sltp=base_atr_sltp_from_chosen_config;best_is_sharpe=-float('inf');best_is_pnl_for_tiebreak=-float('inf')
                for atr_var in atr_sltp_variations:
                    print(f"      Optimizing IS with ATR_SLTP_Period: {atr_var}")
                    current_is_params = base_params_for_wfa.copy()
                    current_is_params['atr_period_for_sltp'] = atr_var 
                    is_metrics=run_single_backtest(data_path,period_def['is_start'],period_def['is_end'],
                                                   chosen_config_details_for_wfa['bt_timeframe'],chosen_config_details_for_wfa['bt_compression'],
                                                   FlexibleStrategy,current_is_params,initial_capital)
                    if not is_metrics['Error']:
                        current_sharpe=is_metrics.get('Sharpe_Ratio',-float('inf'))
                        current_pnl=is_metrics.get('Total_Net_PnL',-float('inf'))
                        if current_sharpe>best_is_sharpe:best_is_sharpe=current_sharpe;best_is_pnl_for_tiebreak=current_pnl;best_is_atr_sltp=atr_var
                        elif current_sharpe==best_is_sharpe and current_pnl>best_is_pnl_for_tiebreak:best_is_pnl_for_tiebreak=current_pnl;best_is_atr_sltp=atr_var
                print(f"    Best IS ATR_SLTP_Period: {best_is_atr_sltp} (Sharpe: {best_is_sharpe:.2f}, PnL: {best_is_pnl_for_tiebreak:.2f})")
                print(f"    Out-of-Sample Period: {period_def['oos_start']} to {period_def['oos_end']} using optimized ATR_SLTP={best_is_atr_sltp}")
                oos_strategy_params=base_params_for_wfa.copy()
                oos_strategy_params['atr_period_for_sltp'] = best_is_atr_sltp
                oos_run_metrics=run_single_backtest(data_path,period_def['oos_start'],period_def['oos_end'],
                                                    chosen_config_details_for_wfa['bt_timeframe'],chosen_config_details_for_wfa['bt_compression'],
                                                    FlexibleStrategy,oos_strategy_params,initial_capital)
                oos_run_metrics['WFA_Segment']=period_def['name'];oos_run_metrics['Optimized_ATR_SLTP']=best_is_atr_sltp
                wfa_all_oos_metrics.append(oos_run_metrics)
                print(f"      OOS Result: PnL={oos_run_metrics['Total_Net_PnL']:.2f}, Trades={oos_run_metrics['Total_Trades']}, Sharpe={oos_run_metrics['Sharpe_Ratio']:.2f}, Error='{oos_run_metrics['Error']}'")
            print("\n--- Overall WFA Out-of-Sample Performances ---")
            if wfa_all_oos_metrics:
                wfa_results_df=pd.DataFrame(wfa_all_oos_metrics)
                print(wfa_results_df[['WFA_Segment','Optimized_ATR_SLTP','Final_Value','Sharpe_Ratio','Max_Drawdown','Total_Trades','Hit_Rate','Total_Net_PnL','Profit_Factor','Error']].to_string())
                successful_wfa_runs=wfa_results_df[wfa_results_df['Error']=='']
                if not successful_wfa_runs.empty:
                    avg_oos_sharpe=successful_wfa_runs['Sharpe_Ratio'].mean();avg_oos_pnl=successful_wfa_runs['Total_Net_PnL'].mean()
                    print(f"\nAverage OOS Sharpe Ratio (successful WFA runs): {avg_oos_sharpe:.2f}")
                    print(f"Average OOS Total Net PnL (successful WFA runs): {avg_oos_pnl:.2f}")
                else:print("\nNo successful WFA OOS runs to calculate averages.")
            else:print("No WFA OOS results to display.")

            # --- Monte Carlo Simulation ---
            print(f"\n--- Monte Carlo Simulation for Top Strategy (from Optimization, using its original ATR SLTP) ---")
            mcs_base_params = base_params_for_wfa.copy() 
            mcs_base_params['doprint_log'] = False 
            print(f"Using Base Config: TF={chosen_config_details_for_wfa['tf_name']}, Ind={mcs_base_params['indicator_name']}, Params={mcs_base_params['indicator_params']}, ATR_SLTP={mcs_base_params['atr_period_for_sltp']}")
            
            mcs_base_run_results_dict = run_single_backtest(
                data_path, DEFAULT_START_DATE, DEFAULT_END_DATE, 
                chosen_config_details_for_wfa['bt_timeframe'], 
                chosen_config_details_for_wfa['bt_compression'],
                FlexibleStrategy, mcs_base_params, initial_capital
            )

            original_trade_pnls = mcs_base_run_results_dict.get('trades_pnl_list', [])
            num_original_trades = len(original_trade_pnls)
            mcs_base_run_error = mcs_base_run_results_dict.get('Error', '')

            if mcs_base_run_error:
                 print(f"MCS SKIPPED: Error in base strategy run for MCS: {mcs_base_run_error}")
            elif num_original_trades == 0:
                print("MCS SKIPPED: No trades in the base strategy run to resample.")
            else:
                num_simulations = 100 
                simulated_total_pnls = []
                print(f"Resampling {num_original_trades} trades over {num_simulations} simulations...")

                for _ in range(num_simulations):
                    current_simulation_total_pnl = 0.0
                    if num_original_trades > 0:
                        simulated_trades_pnl = random.choices(original_trade_pnls, k=num_original_trades)
                        current_simulation_total_pnl = sum(simulated_trades_pnl)
                    simulated_total_pnls.append(current_simulation_total_pnl)

                mean_sim_pnl = np.mean(simulated_total_pnls)
                median_sim_pnl = np.median(simulated_total_pnls)
                std_dev_sim_pnl = np.std(simulated_total_pnls)
                pnl_5th_percentile = np.percentile(simulated_total_pnls, 5)
                pnl_95th_percentile = np.percentile(simulated_total_pnls, 95)
                
                loss_threshold = -0.03 * initial_capital
                num_breaches = sum(1 for pnl in simulated_total_pnls if pnl < loss_threshold)
                breach_percentage = (num_breaches / num_simulations) * 100

                print(f"\n--- Monte Carlo Simulation Results ({num_simulations} runs) ---")
                print(f"Original Strategy Total PnL (for MCS base): {sum(original_trade_pnls):.2f} over {num_original_trades} trades.")
                print(f"Simulated Mean Total PnL: {mean_sim_pnl:.2f}")
                print(f"Simulated Median Total PnL: {median_sim_pnl:.2f}")
                print(f"Simulated Std Dev of Total PnL: {std_dev_sim_pnl:.2f}")
                print(f"Simulated PnL (5th Percentile): {pnl_5th_percentile:.2f}")
                print(f"Simulated PnL (95th Percentile): {pnl_95th_percentile:.2f}")
                print(f"Percentage of runs with >3% capital loss: {breach_percentage:.2f}% (Target: < 10%)")
        
        # --- Plotting Logic (at the very end) ---
        if ENABLE_PLOTTING and top_n_configs: 
            print("\n--- Generating Plots for Top Strategy ---")
            plot_strategy_config_details = top_n_configs[0] 
            plot_strategy_params = plot_strategy_config_details['base_strategy_params'].copy()
            plot_strategy_params['doprint_log'] = True 

            print(f"Plotting for: TF={plot_strategy_config_details['tf_name']}, "
                  f"Ind={plot_strategy_params['indicator_name']}, "
                  f"Params={plot_strategy_params['indicator_params']}, "
                  f"ATR_SLTP={plot_strategy_params['atr_period_for_sltp']}")

            cerebro_plot = None; data_feed_plot = None 
            try:
                cerebro_plot = bt.Cerebro(stdstats=False) 
                data_feed_plot = load_csv_data(data_path, DEFAULT_START_DATE, DEFAULT_END_DATE, 
                                               plot_strategy_config_details['bt_timeframe'], 
                                               plot_strategy_config_details['bt_compression'])
                if data_feed_plot:
                    cerebro_plot.adddata(data_feed_plot)
                    cerebro_plot.addstrategy(FlexibleStrategy, **plot_strategy_params)
                    cerebro_plot.broker.setcash(initial_capital)
                    cerebro_plot.addanalyzer(bt.analyzers.CashValueRecorder, _name='cashvaluer')
                    
                    plot_run_results = cerebro_plot.run()
                    
                    print("Displaying Backtrader's standard plot (close plot window to continue)...")
                    try: cerebro_plot.plot(style='candlestick', barup='green', bardown='red')
                    except Exception as e_plot: print(f"    Backtrader plot failed: {e_plot} (might be due to non-GUI environment or data issues)")

                    if plot_run_results and plot_run_results[0]:
                        cash_value_analysis = plot_run_results[0].analyzers.cashvaluer.get_analysis()
                        equity_curve_points = []
                        
                        sorted_cash_items = []
                        if cash_value_analysis: 
                            try:
                                sorted_cash_items = sorted(cash_value_analysis.items(), 
                                                       key=lambda item: datetime.datetime.strptime(str(item[0]), '%Y-%m-%dT%H:%M:%S') if isinstance(item[0], str) and 'T' in item[0] 
                                                                     else datetime.datetime.strptime(str(item[0]), '%Y-%m-%d') if isinstance(item[0], str) 
                                                                     else datetime.datetime.min)
                            except Exception as e_sort:
                                print(f"Warning: Could not sort cash value items for equity curve due to date parsing: {e_sort}")

                        for date_key, value in sorted_cash_items:
                            if isinstance(date_key, str): 
                                try: dt_obj = datetime.datetime.strptime(date_key, '%Y-%m-%dT%H:%M:%S')
                                except ValueError: 
                                    try: dt_obj = datetime.datetime.strptime(date_key, '%Y-%m-%d')
                                    except ValueError: print(f"Warning: Could not parse date string '{date_key}' for equity curve."); continue
                            else: dt_obj = date_key # Assuming it's already datetime from sorting key if not string
                            equity_curve_points.append((dt_obj, value))

                        if equity_curve_points:
                            dates = [p[0] for p in equity_curve_points]
                            values = [p[1] for p in equity_curve_points]
                            print("Displaying custom equity curve plot (close plot window to continue)...")
                            plt.figure(figsize=(12, 6))
                            plt.plot(dates, values)
                            title_str = (f"Equity Curve: {plot_strategy_params.get('indicator_name', 'N/A')} {plot_strategy_params.get('indicator_params', '')} TF: {plot_strategy_config_details.get('tf_name', 'N/A')}")
                            plt.title(title_str)
                            plt.xlabel("Date")
                            plt.ylabel("Portfolio Value")
                            plt.xticks(rotation=45)
                            plt.tight_layout()
                            try: plt.show()
                            except Exception as e_plt_show: print(f"    Custom plt.show() failed: {e_plt_show} (might be due to non-GUI environment)")
                        else:
                            print("No equity data to plot for custom curve.")
                else:
                    print("Failed to load data for plotting.")
            except Exception as e:
                print(f"Error during plotting setup or run: {e}")
            finally:
                if cerebro_plot: del cerebro_plot 
                if data_feed_plot: del data_feed_plot
        elif not top_n_configs: # This corresponds to 'if not top_n_configs:' for WFA and MCS
            print("Plotting skipped: No top configurations available.")
        else: # This corresponds to 'if ENABLE_PLOTTING'
            print("Plotting skipped: ENABLE_PLOTTING is False.")

    # --- Final Recommendation ---
    print("\n--- Final Recommendation ---")
    print("Always consider WFA and MCS results alongside initial backtest performance.")
    print("Use long, high-quality historical data for meaningful conclusions.")
    print("The dummy data ('es_data.csv') must be replaced for actual analysis.")
