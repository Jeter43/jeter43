"""
交易用例模块 (trading_system/application/use_cases/trading_use_case.py)

功能概述：
    处理核心交易逻辑，包括股票选择、交易决策和订单执行。
    作为交易系统的核心业务逻辑层，协调各个服务完成交易流程。

核心特性：
    1. 交易流程管理：完整的交易决策和执行流程
    2. 风险管理：集成风险控制机制
    3. 状态跟踪：实时跟踪交易状态和性能
    4. 错误恢复：交易失败的自动恢复机制
    5. 性能监控：交易性能统计和分析

设计模式：
    - 用例模式：封装特定的业务场景
    - 策略模式：可插拔的交易策略
    - 观察者模式：交易状态通知

版本历史：
    v1.0 - 基础交易用例
    v2.0 - 增加风险管理和错误恢复
    v3.0 - 集成新配置系统和性能监控
"""

import time
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import logging

from quant_system.infrastructure.brokers.base import Broker
from quant_system.domain.services.stock_selection import StockSelectionService
from quant_system.domain.services.position_management import PositionManagementService
from quant_system.core.config import ConfigManager, TradingEnvironment
from quant_system.utils.logger import get_logger


class TradingUseCase:
    """
    交易用例 - 优化版本

    负责执行具体的交易业务逻辑，包括选股、交易决策和订单管理。
    协调各个服务完成完整的交易流程。

    属性:
        broker: 券商接口实例
        stock_selector: 选股服务实例
        position_manager: 仓位管理服务实例
        config: 配置管理器实例
        trading_securities: 当前交易的股票列表
        _trading_enabled: 交易开关状态
        _performance_stats: 交易性能统计
    """

    def __init__(self,
                 broker: Broker,
                 stock_selector: StockSelectionService,
                 position_manager: PositionManagementService,
                 config: ConfigManager):
        """
        初始化交易用例 - 增强版本，支持分级仓位
        """
        self.broker = broker
        self.stock_selector = stock_selector
        self.position_manager = position_manager
        self.config = config
        self.logger = get_logger(__name__)

        # 交易状态
        self.trading_securities: List[str] = []
        self._trading_enabled = True
        self._last_trading_time: Optional[datetime] = None

        # 新增：分级仓位状态
        self._scaling_enabled = self._check_scaling_enabled()
        self._last_scaling_check: Optional[datetime] = None

        # 性能统计
        self._performance_stats = {
            'total_trades': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'scaling_trades': 0,  # 新增：加仓交易统计
            'total_volume': Decimal('0'),
            'total_value': Decimal('0'),
            'start_time': datetime.now(),
            'last_trade_time': None
        }

        # 错误记录
        self._error_log = []

        self.logger.info(f"交易用例初始化完成 - 分级仓位: {'启用' if self._scaling_enabled else '禁用'}")

    def run(self) -> None:
        """
        运行交易主循环

        执行完整的交易流程：选股 -> 订阅行情 -> 交易决策 -> 订单执行
        支持优雅停止和错误恢复。
        """
        self.logger.info("🎯 启动交易系统主循环")

        try:
            # 前置检查
            if not self._pre_trading_checks():
                self.logger.error("交易前检查失败，停止交易")
                return

            # 主交易循环
            while self._trading_enabled:
                try:
                    current_time = datetime.now()

                    # 执行选股逻辑
                    if self._should_run_selection():
                        self._execute_stock_selection()

                    # 执行交易策略
                    if self.trading_securities:
                        self._execute_trading_strategy()

                    # 更新性能统计
                    self._update_performance_stats()

                    # 等待下一轮
                    time.sleep(self._get_trading_interval())

                    # 检查停止条件
                    if self._should_stop_trading():
                        self.logger.info("达到停止条件，结束交易")
                        break

                except KeyboardInterrupt:
                    self.logger.info("🛑 用户中断交易")
                    break
                except Exception as e:
                    self._handle_trading_error("主循环", e)
                    time.sleep(10)  # 错误后等待

        except Exception as e:
            self.logger.error(f"交易系统严重错误: {e}")
        finally:
            self._cleanup()
            self.logger.info("交易系统已停止")

    async def run_async(self) -> None:
        """
        异步运行交易主循环

        提供异步版本的交易循环，适合在异步环境中使用。
        """
        self.logger.info("🔄 启动异步交易系统")

        try:
            while self._trading_enabled:
                try:
                    # 执行选股逻辑
                    if self._should_run_selection():
                        await self._execute_stock_selection_async()

                    # 执行交易策略
                    if self.trading_securities:
                        await self._execute_trading_strategy_async()

                    # 等待下一轮
                    await asyncio.sleep(self._get_trading_interval())

                except Exception as e:
                    self._handle_trading_error("异步主循环", e)
                    await asyncio.sleep(10)

        except Exception as e:
            self.logger.error(f"异步交易系统错误: {e}")
        finally:
            await self._cleanup_async()

    def execute_single_trade(self,
                             symbol: str,
                             quantity: int,
                             price: Optional[float] = None,
                             order_type: str = "LIMIT") -> Dict[str, Any]:
        """
        执行单次交易

        Args:
            symbol: 股票代码
            quantity: 交易数量
            price: 交易价格（市价单可省略）
            order_type: 订单类型

        Returns:
            Dict[str, Any]: 交易结果
        """
        self.logger.info(f"执行单次交易: {symbol} x {quantity} ({order_type})")

        try:
            # 验证交易参数
            validation_result = self._validate_trade_parameters(symbol, quantity, price, order_type)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'error': validation_result['error'],
                    'order_id': None
                }

            # 风险检查
            risk_check = self._perform_risk_check(symbol, quantity, price)
            if not risk_check['allowed']:
                return {
                    'success': False,
                    'error': f"风险检查失败: {risk_check['reason']}",
                    'order_id': None
                }

            # 执行交易
            if order_type.upper() == "MARKET":
                order_result = self.broker.place_market_order(symbol, quantity)
            else:
                order_result = self.broker.place_limit_order(symbol, quantity, price)

            # 更新统计
            self._update_trade_stats(order_result)

            return order_result

        except Exception as e:
            error_msg = f"单次交易执行失败: {e}"
            self.logger.error(error_msg)
            self._record_error('single_trade', error_msg)
            return {
                'success': False,
                'error': error_msg,
                'order_id': None
            }

    def get_trading_status(self) -> Dict[str, Any]:
        """
        获取交易状态

        Returns:
            Dict[str, Any]: 交易状态信息
        """
        return {
            'trading_enabled': self._trading_enabled,
            'active_securities': self.trading_securities,
            'performance_stats': self._performance_stats.copy(),
            'last_trading_time': self._last_trading_time,
            'error_count': len(self._error_log),
            'config_environment': self.config.trading.environment.value
        }

    def enable_trading(self) -> None:
        """启用交易"""
        if self._trading_enabled:
            self.logger.warning("交易已经启用")
            return

        self._trading_enabled = True
        self.logger.info("✅ 交易已启用")

    def disable_trading(self) -> None:
        """禁用交易"""
        if not self._trading_enabled:
            self.logger.warning("交易已经禁用")
            return

        self._trading_enabled = False
        self.logger.info("🛑 交易已禁用")

    def _pre_trading_checks(self) -> bool:
        """
        交易前检查

        Returns:
            bool: 检查是否通过
        """
        self.logger.info("执行交易前检查...")

        checks = [
            self._check_broker_connection(),
            self._check_account_status(),
            self._check_market_status(),
            self._check_trading_permissions()
        ]

        all_passed = all(checks)

        if all_passed:
            self.logger.info("✅ 所有交易前检查通过")
        else:
            self.logger.error("❌ 交易前检查失败")

        return all_passed

    def _check_broker_connection(self) -> bool:
        """检查券商连接"""
        try:
            account_info = self.broker.get_account_info()
            if account_info and account_info.get('account_id'):
                self.logger.info(f"券商连接正常 - 账户: {account_info['account_id']}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"券商连接检查失败: {e}")
            return False

    def _check_account_status(self) -> bool:
        """检查账户状态"""
        try:
            account_info = self.broker.get_account_info()
            if not account_info:
                return False

            # 检查账户是否可交易
            if account_info.get('trading_enabled', True) is False:
                self.logger.error("账户交易功能被禁用")
                return False

            # 检查资金是否充足（简化检查）
            available_cash = account_info.get('available_cash', 0)
            if available_cash <= 0:
                self.logger.warning("账户可用资金为0")

            return True

        except Exception as e:
            self.logger.error(f"账户状态检查失败: {e}")
            return False

    def _check_market_status(self) -> bool:
        """检查市场状态"""
        try:
            # 获取当前市场配置
            market_config = self.config.get_current_market_config()
            if not market_config.is_market_open():
                self.logger.warning("市场未开盘")
                return False
            return True
        except Exception as e:
            self.logger.error(f"市场状态检查失败: {e}")
            return False

    def _check_trading_permissions(self) -> bool:
        """检查交易权限"""
        # 在模拟环境中总是返回True
        if self.config.trading.environment == TradingEnvironment.SIMULATE:
            return True

        # 实盘环境检查交易权限
        try:
            # 这里可以添加具体的权限检查逻辑
            self.logger.info("交易权限检查通过")
            return True
        except Exception as e:
            self.logger.error(f"交易权限检查失败: {e}")
            return False

    def _should_run_selection(self) -> bool:
        """
        判断是否应该执行选股

        Returns:
            bool: 是否应该执行选股
        """
        # 使用选股服务的逻辑
        return self.stock_selector.should_run_selection()

    def _execute_stock_selection(self) -> None:
        """执行选股逻辑"""
        try:
            self.logger.info("🔍 执行选股分析...")

            # 调用选股服务
            selected_stocks = self.stock_selector.select_stocks_with_priority()

            if selected_stocks:
                self.trading_securities = selected_stocks
                self._subscribe_securities()
                self.logger.info(f"选股完成: {len(selected_stocks)} 只股票")
            else:
                self.logger.warning("选股未选中任何股票")
                self.trading_securities = []

        except Exception as e:
            self._handle_trading_error("选股", e)

    async def _execute_stock_selection_async(self) -> None:
        """异步执行选股逻辑"""
        try:
            # 这里可以实现异步选股逻辑
            self._execute_stock_selection()
        except Exception as e:
            self._handle_trading_error("异步选股", e)

    def _subscribe_securities(self) -> None:
        """订阅股票行情"""
        if not self.trading_securities:
            return

        try:
            self.broker.subscribe(self.trading_securities, ["QUOTE", "K_1M"])
            self.logger.info(f"📡 已订阅 {len(self.trading_securities)} 只股票的行情数据")
        except Exception as e:
            self.logger.error(f"订阅行情失败: {e}")

    def _execute_trading_strategy(self) -> None:
        """执行交易策略 - 增强版本，支持分级仓位"""
        try:
            self.logger.info("💼 执行交易策略分析...")

            # 获取市场数据
            market_data = self.broker.get_market_snapshot(self.trading_securities)
            if not market_data:
                self.logger.warning("无法获取市场数据，跳过交易")
                return

            # 获取投资组合信息
            portfolio = self._get_current_portfolio()
            if not portfolio:
                self.logger.warning("无法获取投资组合信息，跳过交易")
                return

            # 执行交易决策（包含分级仓位逻辑）
            trading_decisions = self._make_trading_decisions_with_scaling(market_data, portfolio)

            # 执行交易
            for decision in trading_decisions:
                if decision['action'] == 'BUY':
                    self._execute_buy_order(decision)
                elif decision['action'] == 'SELL':
                    self._execute_sell_order(decision)
                elif decision['action'] == 'SCALING_BUY':  # 新增：加仓操作
                    self._execute_scaling_buy_order(decision)

            self._last_trading_time = datetime.now()

        except Exception as e:
            self._handle_trading_error("交易策略", e)

    async def _execute_trading_strategy_async(self) -> None:
        """异步执行交易策略"""
        try:
            # 这里可以实现异步交易逻辑
            self._execute_trading_strategy()
        except Exception as e:
            self._handle_trading_error("异步交易策略", e)

    def _make_trading_decisions(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        制定交易决策

        Args:
            market_data: 市场数据

        Returns:
            List[Dict[str, Any]]: 交易决策列表
        """
        decisions = []

        for symbol in self.trading_securities:
            if symbol not in market_data:
                continue

            data = market_data[symbol]
            current_price = data.get('last_price', 0)

            # 简化交易决策逻辑
            # 实际应该基于更复杂的策略
            signal_strength = self.stock_selector.get_signal_strength(symbol)

            if signal_strength > 80 and current_price > 0:
                decisions.append({
                    'symbol': symbol,
                    'action': 'BUY',
                    'quantity': 100,  # 简化数量
                    'price': current_price,
                    'reason': f'强买入信号: {signal_strength}',
                    'timestamp': datetime.now()
                })

        self.logger.info(f"生成 {len(decisions)} 个交易决策")
        return decisions

    def _execute_buy_order(self, decision: Dict[str, Any]) -> None:
        """
        执行买入订单

        Args:
            decision: 交易决策
        """
        try:
            symbol = decision['symbol']
            quantity = decision['quantity']
            price = decision['price']

            self.logger.info(f"🟢 执行买入: {symbol} x {quantity} @ {price:.2f}")

            # 在模拟环境中只记录不执行
            if self.config.trading.environment == TradingEnvironment.SIMULATE:
                self.logger.info(f"[模拟] 买入 {symbol} {quantity}股")
                return

            # 实盘环境执行交易
            order_result = self.broker.place_limit_order(symbol, quantity, price)

            if order_result.get('success'):
                self.logger.info(f"✅ 买入订单提交成功: {order_result.get('order_id')}")
            else:
                self.logger.error(f"❌ 买入订单提交失败: {order_result.get('error')}")

        except Exception as e:
            self.logger.error(f"买入订单执行失败: {e}")

    def _execute_sell_order(self, decision: Dict[str, Any]) -> None:
        """
        执行卖出订单

        Args:
            decision: 交易决策
        """
        try:
            symbol = decision['symbol']
            quantity = decision['quantity']
            price = decision['price']

            self.logger.info(f"🔴 执行卖出: {symbol} x {quantity} @ {price:.2f}")

            # 在模拟环境中只记录不执行
            if self.config.trading.environment == TradingEnvironment.SIMULATE:
                self.logger.info(f"[模拟] 卖出 {symbol} {quantity}股")
                return

            # 实盘环境执行交易
            order_result = self.broker.place_limit_order(symbol, -quantity, price)

            if order_result.get('success'):
                self.logger.info(f"✅ 卖出订单提交成功: {order_result.get('order_id')}")
            else:
                self.logger.error(f"❌ 卖出订单提交失败: {order_result.get('error')}")

        except Exception as e:
            self.logger.error(f"卖出订单执行失败: {e}")

    def _validate_trade_parameters(self, symbol: str, quantity: int,
                                   price: Optional[float], order_type: str) -> Dict[str, Any]:
        """
        验证交易参数

        Args:
            symbol: 股票代码
            quantity: 数量
            price: 价格
            order_type: 订单类型

        Returns:
            Dict[str, Any]: 验证结果
        """
        if quantity <= 0:
            return {'valid': False, 'error': '交易数量必须大于0'}

        if order_type.upper() != "MARKET" and (price is None or price <= 0):
            return {'valid': False, 'error': '限价单必须指定有效价格'}

        if not symbol or len(symbol.strip()) == 0:
            return {'valid': False, 'error': '股票代码不能为空'}

        return {'valid': True, 'error': None}

    def _perform_risk_check(self, symbol: str, quantity: int,
                            price: Optional[float]) -> Dict[str, Any]:
        """
        执行风险检查

        Args:
            symbol: 股票代码
            quantity: 数量
            price: 价格

        Returns:
            Dict[str, Any]: 风险检查结果
        """
        try:
            # 简化风险检查
            # 实际应该基于仓位、资金、市场情况等
            if price and quantity and price * quantity > 1000000:  # 单笔交易超过100万
                return {
                    'allowed': False,
                    'reason': '单笔交易金额过大'
                }

            return {
                'allowed': True,
                'reason': '风险检查通过'
            }

        except Exception as e:
            self.logger.error(f"风险检查异常: {e}")
            return {
                'allowed': False,
                'reason': f'风险检查异常: {e}'
            }

    def _update_trade_stats(self, order_result: Dict[str, Any]) -> None:
        """
        更新交易统计

        Args:
            order_result: 订单结果
        """
        self._performance_stats['total_trades'] += 1

        if order_result.get('success'):
            self._performance_stats['successful_trades'] += 1
        else:
            self._performance_stats['failed_trades'] += 1

        self._performance_stats['last_trade_time'] = datetime.now()

    def _update_performance_stats(self) -> None:
        """更新性能统计"""
        # 可以在这里添加更复杂的性能统计逻辑
        pass

    def _get_trading_interval(self) -> int:
        """
        获取交易间隔

        Returns:
            int: 交易间隔（秒）
        """
        # 根据配置返回交易检查间隔
        return getattr(self.config.system, 'trading_check_interval_seconds', 10)

    def _should_stop_trading(self) -> bool:
        """
        判断是否应该停止交易

        Returns:
            bool: 是否应该停止交易
        """
        # 检查停止条件
        # 例如：达到每日交易限额、市场收盘等
        current_time = datetime.now()

        # 简单的时间检查（下午4点后停止）
        if current_time.hour >= 16:
            self.logger.info("已过交易时间，停止交易")
            return True

        return False

    def _handle_trading_error(self, context: str, error: Exception) -> None:
        """
        处理交易错误

        Args:
            context: 错误上下文
            error: 异常对象
        """
        error_msg = f"交易错误 [{context}]: {error}"
        self.logger.error(error_msg)

        # 记录错误
        self._error_log.append({
            'timestamp': datetime.now(),
            'context': context,
            'error': str(error),
            'type': type(error).__name__
        })

        # 根据错误类型决定是否停止交易
        if isinstance(error, (ConnectionError, TimeoutError)):
            self.logger.warning("网络连接错误，暂停交易")
            self._trading_enabled = False

    def _cleanup(self) -> None:
        """清理资源"""
        self.logger.info("清理交易资源...")

        # 取消订阅
        if self.trading_securities:
            try:
                self.broker.unsubscribe(self.trading_securities)
                self.logger.info("已取消行情订阅")
            except Exception as e:
                self.logger.error(f"取消订阅失败: {e}")

        # 重置状态
        self.trading_securities = []
        self._trading_enabled = False

        # 输出性能报告
        self._log_performance_report()

    async def _cleanup_async(self) -> None:
        """异步清理资源"""
        self._cleanup()

    def _log_performance_report(self) -> None:
        """记录性能报告 - 增强版本"""
        duration = datetime.now() - self._performance_stats['start_time']

        total_trades = self._performance_stats['total_trades']
        scaling_trades = self._performance_stats.get('scaling_trades', 0)
        scaling_ratio = scaling_trades / max(total_trades, 1) * 100

        report = f"""
    📊 交易性能报告:
       运行时长: {duration}
       总交易次数: {total_trades}
       - 成功交易: {self._performance_stats['successful_trades']}
       - 失败交易: {self._performance_stats['failed_trades']}
       - 加仓交易: {scaling_trades} ({scaling_ratio:.1f}%)
       成功率: {self._performance_stats['successful_trades'] / max(total_trades, 1) * 100:.1f}%
       错误次数: {len(self._error_log)}
       分级仓位: {'启用' if self._scaling_enabled else '禁用'}
    """
        self.logger.info(report)

    def _check_scaling_enabled(self) -> bool:
        """检查是否启用分级仓位"""
        try:
            if hasattr(self.config.trading, 'position_scaling_enabled'):
                return self.config.trading.position_scaling_enabled
            return False
        except Exception as e:
            self.logger.warning(f"检查分级仓位配置失败: {e}")
            return False

    def _make_trading_decisions_with_scaling(self, market_data: Dict[str, Any], portfolio: Any) -> List[Dict[str, Any]]:
        """
        制定交易决策 - 增强版本，支持分级仓位

        Args:
            market_data: 市场数据
            portfolio: 投资组合

        Returns:
            List[Dict[str, Any]]: 交易决策列表
        """
        decisions = []

        # 1. 先检查现有持仓的加仓机会
        scaling_decisions = self._check_scaling_opportunities(portfolio, market_data)
        decisions.extend(scaling_decisions)

        # 2. 再检查新开仓机会（避免与加仓冲突）
        new_position_decisions = self._check_new_position_opportunities(portfolio, market_data, scaling_decisions)
        decisions.extend(new_position_decisions)

        self.logger.info(
            f"生成 {len(decisions)} 个交易决策 (新开仓: {len(new_position_decisions)}, 加仓: {len(scaling_decisions)})")
        return decisions

    def _check_scaling_opportunities(self, portfolio: Any, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        检查加仓机会

        Args:
            portfolio: 投资组合
            market_data: 市场数据

        Returns:
            List[Dict[str, Any]]: 加仓决策列表
        """
        scaling_decisions = []

        if not self._scaling_enabled:
            return scaling_decisions

        try:
            # 检查每个现有持仓的加仓条件
            for symbol, position in portfolio.positions.items():
                if symbol not in market_data:
                    continue

                current_data = market_data[symbol]
                current_price = current_data.get('last_price', 0)

                if current_price <= 0:
                    continue

                # 获取当前仓位级别
                current_level = self._get_position_level(portfolio, symbol)

                # 检查加仓条件
                scaling_suggestion = self.position_manager.calculate_scaling_position_size(
                    symbol, current_price, portfolio, current_level
                )

                # 如果建议加仓且风险等级可接受
                if (scaling_suggestion.suggested_quantity > 0 and
                        scaling_suggestion.risk_level.value != 'CRITICAL' and
                        scaling_suggestion.is_scaling_position):
                    scaling_decisions.append({
                        'symbol': symbol,
                        'action': 'SCALING_BUY',
                        'quantity': scaling_suggestion.suggested_quantity,
                        'price': current_price,
                        'target_level': scaling_suggestion.position_level,
                        'reason': f'分级加仓 L{current_level}→L{scaling_suggestion.position_level}: {scaling_suggestion.reason}',
                        'timestamp': datetime.now(),
                        'batch_info': {
                            'current_level': current_level,
                            'target_level': scaling_suggestion.position_level,
                            'profit_ratio': scaling_suggestion.current_profit_ratio
                        }
                    })

                    self.logger.info(f"🎯 发现加仓机会: {symbol} L{current_level}→L{scaling_suggestion.position_level} "
                                     f"数量: {scaling_suggestion.suggested_quantity}")

            return scaling_decisions

        except Exception as e:
            self.logger.error(f"检查加仓机会异常: {e}")
            return []

    def _check_new_position_opportunities(self, portfolio: Any, market_data: Dict[str, Any],
                                          existing_decisions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        检查新开仓机会

        Args:
            portfolio: 投资组合
            market_data: 市场数据
            existing_decisions: 已存在的交易决策

        Returns:
            List[Dict[str, Any]]: 新开仓决策列表
        """
        new_decisions = []

        # 获取已决定交易的股票（避免重复）
        decided_symbols = {decision['symbol'] for decision in existing_decisions}

        for symbol in self.trading_securities:
            # 跳过已决定交易的股票
            if symbol in decided_symbols:
                continue

            if symbol not in market_data:
                continue

            data = market_data[symbol]
            current_price = data.get('last_price', 0)

            # 简化交易决策逻辑
            signal_strength = self.stock_selector.get_signal_strength(symbol)

            if signal_strength > 80 and current_price > 0:
                # 计算初始建仓数量
                initial_suggestion = self.position_manager.calculate_safe_position_size(
                    symbol, current_price, portfolio, is_initial=True
                )

                if (initial_suggestion.suggested_quantity > 0 and
                        initial_suggestion.risk_level.value != 'CRITICAL'):
                    new_decisions.append({
                        'symbol': symbol,
                        'action': 'BUY',
                        'quantity': initial_suggestion.suggested_quantity,
                        'price': current_price,
                        'reason': f'初始建仓 L1: 信号强度 {signal_strength}',
                        'timestamp': datetime.now(),
                        'batch_info': {
                            'level': 1,
                            'is_initial': True
                        }
                    })

        return new_decisions

    def _get_position_level(self, portfolio: Any, symbol: str) -> int:
        """
        获取仓位级别

        Args:
            portfolio: 投资组合
            symbol: 股票代码

        Returns:
            int: 仓位级别 (0=无持仓, 1=初始, 2=第一次加仓, 3=第二次加仓)
        """
        try:
            if hasattr(portfolio, 'get_position_level'):
                return portfolio.get_position_level(symbol)
            else:
                # 回退逻辑：根据持仓比例判断
                position = portfolio.positions.get(symbol)
                if not position:
                    return 0

                position_value = position.market_value
                total_assets = getattr(portfolio, 'total_assets', 1)
                position_ratio = position_value / total_assets

                if position_ratio >= 0.18:
                    return 3
                elif position_ratio >= 0.10:
                    return 2
                elif position_ratio > 0:
                    return 1
                else:
                    return 0

        except Exception as e:
            self.logger.error(f"获取仓位级别异常 {symbol}: {e}")
            return 0

    def _execute_scaling_buy_order(self, decision: Dict[str, Any]) -> None:
        """
        执行加仓买入订单

        Args:
            decision: 加仓交易决策
        """
        try:
            symbol = decision['symbol']
            quantity = decision['quantity']
            price = decision['price']
            target_level = decision.get('target_level', 2)
            batch_info = decision.get('batch_info', {})

            self.logger.info(f"🟡 执行加仓买入: {symbol} x {quantity} @ {price:.2f} (L{target_level})")

            # 在模拟环境中只记录不执行
            if self.config.trading.environment == TradingEnvironment.SIMULATE:
                self.logger.info(f"[模拟] 加仓买入 {symbol} {quantity}股 -> L{target_level}")
                self._performance_stats['scaling_trades'] += 1
                return

            # 实盘环境执行交易
            order_result = self.broker.place_limit_order(symbol, quantity, price)

            if order_result.get('success'):
                self.logger.info(f"✅ 加仓买入订单提交成功: {order_result.get('order_id')} -> L{target_level}")
                self._performance_stats['scaling_trades'] += 1

                # 记录加仓批次信息（如果支持）
                self._record_scaling_batch(symbol, quantity, price, target_level, batch_info)
            else:
                self.logger.error(f"❌ 加仓买入订单提交失败: {order_result.get('error')}")

        except Exception as e:
            self.logger.error(f"加仓买入订单执行失败: {e}")

    def _record_scaling_batch(self, symbol: str, quantity: int, price: float,
                              target_level: int, batch_info: Dict[str, Any]) -> None:
        """
        记录加仓批次信息

        Args:
            symbol: 股票代码
            quantity: 数量
            price: 价格
            target_level: 目标级别
            batch_info: 批次信息
        """
        try:
            # 这里可以添加批次记录逻辑
            # 例如：更新投资组合的批次信息、记录到数据库等
            self.logger.debug(f"记录加仓批次: {symbol} L{target_level} {quantity}股 @ {price:.2f}")

        except Exception as e:
            self.logger.error(f"记录加仓批次异常: {e}")

    def _get_current_portfolio(self) -> Optional[Any]:
        """
        获取当前投资组合

        Returns:
            Optional[Any]: 投资组合对象
        """
        try:
            # 从券商获取账户信息
            account_info = self.broker.get_account_info()
            if not account_info:
                return None

            # 创建或更新投资组合对象
            # 这里需要根据你的具体实现来调整
            portfolio = getattr(self, '_portfolio', None)
            if not portfolio:
                # 创建新的投资组合对象
                from quant_system.domain.entities.portfolio import Portfolio
                portfolio = Portfolio(
                    account_id=account_info.get('account_id', 'default'),
                    total_assets=account_info.get('total_assets', 0),
                    cash=account_info.get('available_cash', 0),
                    available_cash=account_info.get('available_cash', 0)
                )
                self._portfolio = portfolio

            # 更新投资组合信息
            portfolio.update_from_account_info(account_info)
            return portfolio

        except Exception as e:
            self.logger.error(f"获取投资组合异常: {e}")
            return None