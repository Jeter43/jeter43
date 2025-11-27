# trading_system/application/use_cases/backtest_engine.py
"""
回测引擎
支持分钟级回测，模拟真实交易环境
"""

import sys
import os
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from dataclasses import dataclass, field

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from quant_system.core.config import ConfigManager, SystemMode
from quant_system.domain.strategies.strategy_factory import StrategyFactory
from quant_system.infrastructure.brokers.base import Broker


@dataclass
class BacktestTrade:
    """回测交易记录"""
    timestamp: datetime
    symbol: str
    action: str  # 'BUY' or 'SELL'
    quantity: int
    price: float
    commission: float = 0.0
    remark: str = ""


@dataclass
class BacktestPosition:
    """回测持仓"""
    symbol: str
    quantity: int
    cost_price: float
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: float = 0.0


@dataclass
class BacktestPortfolio:
    """回测投资组合"""
    initial_capital: float
    cash: float
    positions: Dict[str, BacktestPosition] = field(default_factory=dict)
    trades: List[BacktestTrade] = field(default_factory=list)
    daily_values: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        """计算组合总价值"""
        position_value = sum(
            pos.quantity * self._get_current_price(pos.symbol)
            for pos in self.positions.values()
        )
        return self.cash + position_value

    def _get_current_price(self, symbol: str) -> float:
        """获取当前价格 - 需要在回测环境中实现"""
        # 这里应该在回测循环中动态更新
        return 0.0


@dataclass
class BacktestResult:
    """回测结果"""
    # 基础指标
    initial_capital: float
    final_value: float
    total_return: float
    annual_return: float

    # 风险指标
    max_drawdown: float
    volatility: float
    sharpe_ratio: float

    # 交易指标
    total_trades: int
    winning_trades: int
    win_rate: float
    avg_profit_per_trade: float

    # 详细记录
    trades: List[BacktestTrade]
    daily_portfolio: List[Dict[str, Any]]

    # 策略表现
    strategy_performance: Dict[str, Any]


class BacktestEngine:
    """回测引擎 - 核心回测功能"""

    def __init__(self, config: ConfigManager, strategy_factory: StrategyFactory):
        self.config = config
        self.strategy_factory = strategy_factory
        self.logger = get_logger()

        # 回测数据
        self.historical_data: Dict[str, pd.DataFrame] = {}
        self.current_datetime: Optional[datetime] = None
        self.data_index: Dict[str, int] = {}

        # 回测状态
        self.portfolio: Optional[BacktestPortfolio] = None
        self.is_running = False

        # 策略实例
        self.selection_strategies = []
        self.risk_strategies = []

        # 性能跟踪
        self.performance_metrics = {}

        self._initialize_strategies()

    def _initialize_strategies(self):
        """初始化策略实例"""
        try:
            # 初始化选股策略
            for strategy_name in self.config.system.selection_strategies:
                strategy = self.strategy_factory.get_selection_strategy(strategy_name.value)
                self.selection_strategies.append(strategy)
                self.logger.info(f"✅ 加载选股策略: {strategy.name}")

            # 初始化风控策略
            for strategy_name in self.config.system.risk_strategies:
                strategy = self.strategy_factory.get_risk_strategy(strategy_name.value)
                self.risk_strategies.append(strategy)
                self.logger.info(f"✅ 加载风控策略: {strategy.name}")

        except Exception as e:
            self.logger.error(f"初始化策略失败: {e}")

    def load_historical_data(self, symbols: List[str], start_date: str, end_date: str):
        """
        加载历史数据

        Args:
            symbols: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        """
        self.logger.info(f"📊 加载历史数据: {start_date} 至 {end_date}")

        # 这里应该从数据源加载真实数据
        # 暂时使用模拟数据
        for symbol in symbols:
            self.historical_data[symbol] = self._generate_mock_data(
                symbol, start_date, end_date
            )
            self.data_index[symbol] = 0

        self.logger.info(f"✅ 加载完成: {len(symbols)} 只股票数据")

    def _generate_mock_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        生成模拟分钟级数据用于测试
        """
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        # 生成交易时间序列 (分钟级)
        trading_days = pd.date_range(start=start_dt, end=end_dt, freq='D')
        all_minutes = []

        for day in trading_days:
            if day.weekday() < 5:  # 只包括工作日
                # 上午交易时段: 9:30-12:00
                morning = pd.date_range(
                    start=day.replace(hour=9, minute=30),
                    end=day.replace(hour=12, minute=0),
                    freq='1min'
                )
                # 下午交易时段: 13:00-16:00
                afternoon = pd.date_range(
                    start=day.replace(hour=13, minute=0),
                    end=day.replace(hour=16, minute=0),
                    freq='1min'
                )
                all_minutes.extend(morning)
                all_minutes.extend(afternoon)

        # 生成价格数据 (随机游走)
        n_points = len(all_minutes)
        base_price = np.random.uniform(50, 200)
        returns = np.random.normal(0.0001, 0.01, n_points)  # 日波动约1.5%
        prices = base_price * (1 + returns).cumprod()

        # 生成OHLCV数据
        data = {
            'timestamp': all_minutes,
            'open': prices * np.random.uniform(0.995, 1.005, n_points),
            'high': prices * np.random.uniform(1.005, 1.015, n_points),
            'low': prices * np.random.uniform(0.985, 0.995, n_points),
            'close': prices,
            'volume': np.random.randint(100000, 1000000, n_points)
        }

        return pd.DataFrame(data)

    def run_backtest(self, symbols: List[str]) -> BacktestResult:
        """
        运行回测

        Args:
            symbols: 要回测的股票列表

        Returns:
            BacktestResult: 回测结果
        """
        self.logger.info("🚀 开始回测...")

        # 初始化投资组合
        self.portfolio = BacktestPortfolio(
            initial_capital=self.config.backtest.initial_capital,
            cash=self.config.backtest.initial_capital
        )

        self.is_running = True

        try:
            # 回测主循环
            while self.is_running and self._has_more_data():
                # 推进到下一分钟
                if not self._advance_time():
                    break

                # 执行分钟级策略
                self._execute_minute_strategy()

                # 记录每日组合价值
                self._record_daily_portfolio()

            # 生成回测报告
            result = self._generate_backtest_result()
            self.logger.info("✅ 回测完成")
            return result

        except Exception as e:
            self.logger.error(f"回测执行异常: {e}")
            raise

    def _has_more_data(self) -> bool:
        """检查是否还有数据"""
        if not self.historical_data:
            return False

        # 检查所有股票是否都有数据
        for symbol, data in self.historical_data.items():
            if self.data_index[symbol] < len(data) - 1:
                return True
        return False

    def _advance_time(self) -> bool:
        """推进到下一时间点"""
        if not self.current_datetime:
            # 初始化时间
            first_symbol = list(self.historical_data.keys())[0]
            self.current_datetime = self.historical_data[first_symbol].iloc[0]['timestamp']
            return True

        # 找到下一个有效时间点
        next_datetime = None
        for symbol, data in self.historical_data.items():
            current_idx = self.data_index[symbol]
            if current_idx < len(data) - 1:
                candidate_time = data.iloc[current_idx + 1]['timestamp']
                if next_datetime is None or candidate_time < next_datetime:
                    next_datetime = candidate_time

        if next_datetime is None:
            return False

        # 更新所有股票的数据索引
        for symbol, data in self.historical_data.items():
            current_idx = self.data_index[symbol]
            while (current_idx < len(data) - 1 and
                   data.iloc[current_idx + 1]['timestamp'] <= next_datetime):
                current_idx += 1
            self.data_index[symbol] = current_idx

        self.current_datetime = next_datetime
        return True

    def _execute_minute_strategy(self):
        """执行分钟级策略"""
        if not self.portfolio:
            return

        current_market_data = self._get_current_market_data()

        try:
            # 只在交易时间执行策略
            if not self._is_trading_time():
                return

            # 执行选股策略 (按配置频率)
            if self._should_run_selection():
                selected_stocks = self._execute_selection_strategies(current_market_data)
                self._execute_trading_decisions(selected_stocks, current_market_data)

            # 执行风控策略 (按配置频率)
            if self._should_run_risk_check():
                risk_result = self._execute_risk_strategies(current_market_data)
                self._execute_risk_actions(risk_result, current_market_data)

        except Exception as e:
            self.logger.error(f"分钟策略执行异常: {e}")

    def _get_current_market_data(self) -> Dict[str, Any]:
        """获取当前市场数据"""
        market_data = {}

        for symbol, data in self.historical_data.items():
            current_idx = self.data_index[symbol]
            if current_idx < len(data):
                current_row = data.iloc[current_idx]
                market_data[symbol] = {
                    'price': current_row['close'],
                    'open': current_row['open'],
                    'high': current_row['high'],
                    'low': current_row['low'],
                    'volume': current_row['volume'],
                    'timestamp': current_row['timestamp']
                }

        return market_data

    def _is_trading_time(self) -> bool:
        """判断是否为交易时间"""
        if not self.current_datetime:
            return False

        time = self.current_datetime.time()
        # 港股交易时间: 9:30-12:00, 13:00-16:00
        morning_session = (time >= datetime.strptime('09:30', '%H:%M').time() and
                           time <= datetime.strptime('12:00', '%H:%M').time())
        afternoon_session = (time >= datetime.strptime('13:00', '%H:%M').time() and
                             time <= datetime.strptime('16:00', '%H:%M').time())

        return morning_session or afternoon_session

    def _should_run_selection(self) -> bool:
        """判断是否应该执行选股"""
        # 简化实现：每天执行一次选股
        if not self.current_datetime:
            return False

        current_time = self.current_datetime.time()
        return current_time == datetime.strptime('10:00', '%H:%M').time()

    def _should_run_risk_check(self) -> bool:
        """判断是否应该执行风控检查"""
        # 每分钟都执行风控检查
        return True

    def _execute_selection_strategies(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """执行选股策略"""
        selected_stocks = []

        for strategy in self.selection_strategies:
            if strategy.enabled:
                try:
                    # 获取股票池
                    stock_universe = list(self.historical_data.keys())
                    selected = strategy.select_stocks(stock_universe)
                    selected_stocks.extend(selected)

                    self.logger.debug(f"✅ {strategy.name} 选股: {len(selected)} 只")

                except Exception as e:
                    self.logger.error(f"选股策略 {strategy.name} 执行失败: {e}")

        # 合并和排序结果
        return self._merge_selection_results(selected_stocks)

    def _execute_risk_strategies(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行风控策略"""
        combined_result = {
            'risk_level': 'LOW',
            'actions': [],
            'strategies': []
        }

        for strategy in self.risk_strategies:
            if strategy.enabled:
                try:
                    risk_result = strategy.check_risk(self.portfolio, market_data)
                    combined_result['strategies'].append({
                        'name': strategy.name,
                        'risk_level': risk_result['risk_level']
                    })
                    combined_result['actions'].extend(risk_result['actions'])

                except Exception as e:
                    self.logger.error(f"风控策略 {strategy.name} 执行失败: {e}")

        return combined_result

    def _execute_trading_decisions(self, selected_stocks: List[Dict[str, Any]],
                                   market_data: Dict[str, Any]):
        """执行交易决策"""
        if not self.portfolio:
            return

        for stock in selected_stocks[:self.config.trading.max_stocks]:
            symbol = stock['symbol']

            # 检查是否已经持有
            if symbol in self.portfolio.positions:
                continue

            # 计算买入数量
            quantity = self._calculate_buy_quantity(symbol, market_data)
            if quantity <= 0:
                continue

            # 执行买入
            self._execute_buy_order(symbol, quantity, market_data, f"选股: {stock['reason']}")

    def _execute_risk_actions(self, risk_result: Dict[str, Any], market_data: Dict[str, Any]):
        """执行风控动作"""
        if not self.portfolio:
            return

        for action in risk_result['actions']:
            if action.get('symbol'):
                # 个股风控动作
                symbol = action['symbol']
                if symbol in self.portfolio.positions:
                    quantity = self.portfolio.positions[symbol].quantity
                    self._execute_sell_order(symbol, quantity, market_data, action['reason'])
            else:
                # 组合级风控动作
                self.logger.warning(f"组合风控: {action['reason']}")

    def _calculate_buy_quantity(self, symbol: str, market_data: Dict[str, Any]) -> int:
        """计算买入数量"""
        if not self.portfolio:
            return 0

        current_price = market_data.get(symbol, {}).get('price', 0)
        if current_price <= 0:
            return 0

        # 计算可用资金
        available_cash = self.portfolio.cash * 0.8  # 保留20%现金

        # 计算仓位大小
        position_value = available_cash * self.config.trading.initial_position_ratio

        # 计算数量
        raw_quantity = position_value / current_price
        quantity = int(raw_quantity / 100) * 100  # 按手数取整

        return quantity if quantity > 0 else 0

    def _execute_buy_order(self, symbol: str, quantity: int, market_data: Dict[str, Any], remark: str):
        """执行买入订单"""
        if not self.portfolio:
            return

        current_price = market_data.get(symbol, {}).get('price', 0)
        if current_price <= 0:
            return

        # 计算交易成本
        trade_value = quantity * current_price
        commission = trade_value * self.config.backtest.commission_rate

        # 检查资金是否足够
        if self.portfolio.cash < (trade_value + commission):
            self.logger.warning(f"资金不足，无法买入 {symbol}")
            return

        # 执行交易
        self.portfolio.cash -= (trade_value + commission)

        # 记录交易
        trade = BacktestTrade(
            timestamp=self.current_datetime,
            symbol=symbol,
            action='BUY',
            quantity=quantity,
            price=current_price,
            commission=commission,
            remark=remark
        )
        self.portfolio.trades.append(trade)

        # 更新持仓
        if symbol in self.portfolio.positions:
            # 加仓
            old_pos = self.portfolio.positions[symbol]
            total_quantity = old_pos.quantity + quantity
            total_cost = (old_pos.cost_price * old_pos.quantity + current_price * quantity)
            avg_cost = total_cost / total_quantity

            self.portfolio.positions[symbol] = BacktestPosition(
                symbol=symbol,
                quantity=total_quantity,
                cost_price=avg_cost,
                entry_time=old_pos.entry_time
            )
        else:
            # 新建持仓
            self.portfolio.positions[symbol] = BacktestPosition(
                symbol=symbol,
                quantity=quantity,
                cost_price=current_price,
                entry_time=self.current_datetime
            )

        self.logger.info(f"📈 买入 {symbol} {quantity}股 @ {current_price:.2f} - {remark}")

    def _execute_sell_order(self, symbol: str, quantity: int, market_data: Dict[str, Any], remark: str):
        """执行卖出订单"""
        if not self.portfolio or symbol not in self.portfolio.positions:
            return

        position = self.portfolio.positions[symbol]
        current_price = market_data.get(symbol, {}).get('price', 0)
        if current_price <= 0:
            return

        # 确定卖出数量
        sell_quantity = min(quantity, position.quantity)

        # 计算交易成本
        trade_value = sell_quantity * current_price
        commission = trade_value * self.config.backtest.commission_rate

        # 执行交易
        self.portfolio.cash += (trade_value - commission)

        # 记录交易
        trade = BacktestTrade(
            timestamp=self.current_datetime,
            symbol=symbol,
            action='SELL',
            quantity=sell_quantity,
            price=current_price,
            commission=commission,
            remark=remark
        )
        self.portfolio.trades.append(trade)

        # 更新持仓
        if sell_quantity == position.quantity:
            # 平仓
            del self.portfolio.positions[symbol]
        else:
            # 减仓
            self.portfolio.positions[symbol] = BacktestPosition(
                symbol=symbol,
                quantity=position.quantity - sell_quantity,
                cost_price=position.cost_price,
                entry_time=position.entry_time
            )

        self.logger.info(f"📉 卖出 {symbol} {sell_quantity}股 @ {current_price:.2f} - {remark}")

    def _merge_selection_results(self, all_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合并选股结果"""
        seen_symbols = set()
        merged = []

        for stock in sorted(all_stocks, key=lambda x: x['score'], reverse=True):
            if stock['symbol'] not in seen_symbols:
                merged.append(stock)
                seen_symbols.add(stock['symbol'])

        return merged[:self.config.trading.max_stocks]

    def _record_daily_portfolio(self):
        """记录每日组合价值"""
        if not self.portfolio or not self.current_datetime:
            return

        current_time = self.current_datetime.time()

        # 只在收盘时记录
        if current_time == datetime.strptime('16:00', '%H:%M').time():
            daily_record = {
                'date': self.current_datetime.date(),
                'portfolio_value': self.portfolio.total_value,
                'cash': self.portfolio.cash,
                'positions_count': len(self.portfolio.positions),
                'timestamp': self.current_datetime
            }
            self.portfolio.daily_values.append(daily_record)

    def _generate_backtest_result(self) -> BacktestResult:
        """生成回测结果"""
        if not self.portfolio:
            raise ValueError("投资组合未初始化")

        # 计算基础指标
        initial_capital = self.portfolio.initial_capital
        final_value = self.portfolio.total_value
        total_return = (final_value - initial_capital) / initial_capital

        # 计算年化收益率
        backtest_days = len(self.portfolio.daily_values)
        if backtest_days > 0:
            annual_return = (1 + total_return) ** (365 / backtest_days) - 1
        else:
            annual_return = 0

        # 计算最大回撤
        max_drawdown = self._calculate_max_drawdown()

        # 计算波动率
        volatility = self._calculate_volatility()

        # 计算夏普比率
        sharpe_ratio = self._calculate_sharpe_ratio(annual_return, volatility)

        # 计算交易指标
        total_trades = len(self.portfolio.trades)
        winning_trades = self._count_winning_trades()
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_profit = self._calculate_avg_profit_per_trade()

        return BacktestResult(
            initial_capital=initial_capital,
            final_value=final_value,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            total_trades=total_trades,
            winning_trades=winning_trades,
            win_rate=win_rate,
            avg_profit_per_trade=avg_profit,
            trades=self.portfolio.trades,
            daily_portfolio=self.portfolio.daily_values,
            strategy_performance=self.performance_metrics
        )

    def _calculate_max_drawdown(self) -> float:
        """计算最大回撤"""
        if not self.portfolio.daily_values:
            return 0

        portfolio_values = [day['portfolio_value'] for day in self.portfolio.daily_values]
        peak = portfolio_values[0]
        max_dd = 0

        for value in portfolio_values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_volatility(self) -> float:
        """计算波动率"""
        if len(self.portfolio.daily_values) < 2:
            return 0

        returns = []
        for i in range(1, len(self.portfolio.daily_values)):
            prev_value = self.portfolio.daily_values[i - 1]['portfolio_value']
            curr_value = self.portfolio.daily_values[i]['portfolio_value']
            daily_return = (curr_value - prev_value) / prev_value
            returns.append(daily_return)

        return np.std(returns) * np.sqrt(252)  # 年化波动率

    def _calculate_sharpe_ratio(self, annual_return: float, volatility: float) -> float:
        """计算夏普比率"""
        risk_free_rate = 0.02  # 假设无风险利率2%
        if volatility == 0:
            return 0
        return (annual_return - risk_free_rate) / volatility

    def _count_winning_trades(self) -> int:
        """计算盈利交易数量"""
        if not self.portfolio.trades:
            return 0

        # 简化实现：需要配对买卖交易
        return len(self.portfolio.trades) // 2  # 临时实现

    def _calculate_avg_profit_per_trade(self) -> float:
        """计算平均每笔交易盈利"""
        # 简化实现
        return 0.0

    def generate_report(self, result: BacktestResult) -> Dict[str, Any]:
        """生成详细回测报告"""
        report = {
            'summary': {
                '初始资金': f"¥{result.initial_capital:,.2f}",
                '最终价值': f"¥{result.final_value:,.2f}",
                '总收益率': f"{result.total_return:.2%}",
                '年化收益率': f"{result.annual_return:.2%}",
                '最大回撤': f"{result.max_drawdown:.2%}",
                '夏普比率': f"{result.sharpe_ratio:.2f}",
            },
            'trading': {
                '总交易次数': result.total_trades,
                '盈利交易数': result.winning_trades,
                '胜率': f"{result.win_rate:.2%}",
                '平均每笔盈利': f"¥{result.avg_profit_per_trade:,.2f}",
            },
            'risk_metrics': {
                '波动率': f"{result.volatility:.2%}",
                '最大回撤': f"{result.max_drawdown:.2%}",
                '夏普比率': f"{result.sharpe_ratio:.2f}",
            }
        }

        return report

    def plot_performance(self, result: BacktestResult, save_path: str = None):
        """绘制回测绩效图表"""
        if not result.daily_portfolio:
            self.logger.warning("没有足够的数据绘制图表")
            return

        # 准备数据
        dates = [day['date'] for day in result.daily_portfolio]
        portfolio_values = [day['portfolio_value'] for day in result.daily_portfolio]

        # 创建图表
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))

        # 1. 组合价值曲线
        ax1.plot(dates, portfolio_values, linewidth=2, color='#2E86AB')
        ax1.set_title('组合价值曲线', fontweight='bold')
        ax1.set_ylabel('组合价值 (元)')
        ax1.grid(True, alpha=0.3)

        # 2. 收益率分布
        returns = []
        for i in range(1, len(portfolio_values)):
            ret = (portfolio_values[i] - portfolio_values[i - 1]) / portfolio_values[i - 1]
            returns.append(ret)

        ax2.hist(returns, bins=30, color='#F18F01', alpha=0.7, edgecolor='black')
        ax2.set_title('日收益率分布', fontweight='bold')
        ax2.set_xlabel('日收益率')
        ax2.set_ylabel('频率')
        ax2.grid(True, alpha=0.3)

        # 3. 回撤分析
        drawdowns = self._calculate_drawdown_series(portfolio_values)
        ax3.plot(dates[1:], drawdowns, linewidth=2, color='#C73E1D')
        ax3.fill_between(dates[1:], drawdowns, 0, color='red', alpha=0.3)
        ax3.set_title('回撤分析', fontweight='bold')
        ax3.set_ylabel('回撤 (%)')
        ax3.grid(True, alpha=0.3)

        # 4. 月度收益热力图
        try:
            monthly_returns = self._calculate_monthly_returns(dates, portfolio_values)
            sns.heatmap(monthly_returns, annot=True, fmt='.1%', cmap='RdYlGn',
                        center=0, ax=ax4, cbar_kws={'label': '收益率'})
            ax4.set_title('月度收益率热力图', fontweight='bold')
        except:
            ax4.text(0.5, 0.5, '数据不足\n生成热力图', ha='center', va='center')
            ax4.set_title('月度收益率热力图', fontweight='bold')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"📈 图表已保存: {save_path}")

        plt.show()

    def _calculate_drawdown_series(self, portfolio_values: List[float]) -> List[float]:
        """计算回撤序列"""
        drawdowns = []
        peak = portfolio_values[0]

        for value in portfolio_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            drawdowns.append(drawdown)

        return drawdowns

    def _calculate_monthly_returns(self, dates: List[datetime], values: List[float]) -> pd.DataFrame:
        """计算月度收益率"""
        # 简化实现
        return pd.DataFrame()


# 导出类
__all__ = ['BacktestEngine', 'BacktestResult', 'BacktestTrade', 'BacktestPortfolio']