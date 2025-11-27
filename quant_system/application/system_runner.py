"""
系统运行器模块 (quant_system/application/system_runner.py)

功能概述：
    量化交易系统的核心运行引擎，负责根据配置模式调度不同的运行策略。
    支持选股模式、风控模式、全自动模式和回测模式。

核心特性：
    1. 多模式运行：根据配置自动切换运行模式
    2. 策略调度：动态加载和执行选股/风控策略
    3. 错误恢复：完善的异常处理和系统恢复机制
    4. 资源管理：安全的资源获取和释放
    5. 状态监控：实时监控系统运行状态

设计模式：
    - 策略模式：不同的运行模式对应不同的策略
    - 工厂模式：通过策略工厂创建具体策略实例
    - 观察者模式：系统状态监控和通知

版本历史：
    v1.0 - 基础系统运行器
    v2.0 - 增加多模式支持和错误恢复
    v3.0 - 集成新配置系统和资源管理
"""

import time
import threading
import queue
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
from decimal import Decimal
import logging

from quant_system.core.config import ConfigManager, SystemMode, Environment
from quant_system.domain.strategies.strategy_factory import StrategyFactory
from quant_system.infrastructure.brokers.base import Broker
from quant_system.domain.services.position_management import PositionManagementService
from quant_system.utils.logger import get_logger


class SystemRunner:
    """
    系统运行器 - 优化版本

    负责整个量化交易系统的运行调度，根据配置模式执行相应的交易逻辑。
    支持多种运行模式，具备完善的错误处理和资源管理。

    属性:
        config: 配置管理器实例
        strategy_factory: 策略工厂实例
        broker: 券商接口实例
        portfolio_manager: 投资组合管理器
        system_monitor: 系统监控器（可选）
        running: 系统运行状态
        last_selection_time: 上次选股时间
        last_risk_check_time: 上次风控检查时间
    """

    def __init__(self,
                 config: ConfigManager,
                 strategy_factory: StrategyFactory,
                 broker: Broker,
                 portfolio_manager: PositionManagementService,
                 service_integrator: Optional[Any] = None,
                 system_monitor: Optional[Any] = None):
        """
        初始化系统运行器

        Args:
            config: 配置管理器
            strategy_factory: 策略工厂
            broker: 券商接口
            portfolio_manager: 仓位管理服务
            service_integrator: 服务集成器（可选）
            system_monitor: 系统监控器（可选）
        """
        self.config = config
        self.strategy_factory = strategy_factory
        self.broker = broker
        self.portfolio_manager = portfolio_manager
        self.service_integrator = service_integrator
        self.system_monitor = system_monitor
        self.logger = get_logger(__name__)

        # 运行状态控制
        self.running = False
        self._stop_event = threading.Event()

        # 时间记录
        self.last_selection_time: Optional[datetime] = None
        self.last_risk_check_time: Optional[datetime] = None
        self.last_account_update_time: Optional[datetime] = None  # 上次账户状态更新时间
        self.start_time: Optional[datetime] = None

        # 性能统计 - 修复类型注解问题
        self._execution_stats: Dict[str, Union[int, List[Dict[str, Any]], Optional[datetime]]] = {
            'selection_count': 0,
            'risk_check_count': 0,
            'errors': [],
            'last_successful_run': None
        }

        self.logger.info("系统运行器初始化完成")

    def start(self) -> bool:
        """
        启动系统运行 - 优化版，减少冗余日志
        """
        self.logger.info("🚀 SystemRunner.start() 开始执行")

        if self.running:
            self.logger.warning("系统已经在运行中")
            return False

        try:
            # 前置检查
            self._pre_start_checks()
            self.logger.info("✅ 前置检查通过")

            # 设置运行状态
            self.running = True
            self._stop_event.clear()
            self.start_time = datetime.now()

            # 获取运行模式并记录配置
            mode = self.config.system.mode
            strategies = self.config.get_mode_specific_strategies()
            self.logger.info(f"🚀 启动系统 - 模式: {mode.value}, 环境: {self.config.environment.value}")
            self.logger.info(f"📋 策略配置 - 选股: {strategies['selection']}, 风控: {strategies['risk']}")

            # 根据模式启动相应的运行逻辑

            if mode == SystemMode.STOCK_SELECTION_ONLY:
                self.logger.info("🎯 进入选股模式分支")
                self._run_stock_selection_mode()
                self.logger.info("✅ 选股模式执行完成")
            elif mode == SystemMode.RISK_MANAGEMENT_ONLY:
                self.logger.info("🛡️ 进入风控模式分支")
                self._run_risk_management_mode()
            elif mode == SystemMode.FULL_AUTOMATION:
                self.logger.info("🤖 进入全自动模式分支")
                self._run_full_automation_mode()
            elif mode == SystemMode.BACKTEST:
                self.logger.info("📊 进入回测模式分支")
                self._run_backtest_mode()
            else:
                self.logger.error(f"❌ 不支持的运行模式: {mode}")
                raise ValueError(f"不支持的运行模式: {mode}")

            self.logger.info("✅ SystemRunner.start() 执行完成")
            return True

        except Exception as e:
            self.logger.error(f"❌ 系统启动失败: {e}")
            self.running = False
            raise

    def stop(self) -> bool:
        """
        停止系统运行

        Returns:
            bool: 停止是否成功
        """
        if not self.running:
            self.logger.warning("系统未在运行")
            return False

        try:
            self.logger.info("🛑 正在停止系统...")
            self.running = False
            self._stop_event.set()

            # 等待当前操作完成（如果有）
            time.sleep(1)

            # 记录运行统计
            if self.start_time:
                run_duration = datetime.now() - self.start_time
                self.logger.info(f"系统运行时长: {run_duration}")

            self.logger.info("✅ 系统已安全停止")
            return True

        except Exception as e:
            self.logger.error(f"系统停止过程中发生错误: {e}")
            return False

    def get_system_status(self) -> Dict[str, Any]:
        """
        获取系统运行状态

        Returns:
            Dict[str, Any]: 系统状态信息
        """
        return {
            'running': self.running,
            'mode': self.config.system.mode.value,
            'environment': self.config.environment.value,
            'start_time': self.start_time,
            'last_selection_time': self.last_selection_time,
            'last_risk_check_time': self.last_risk_check_time,
            'execution_stats': self._execution_stats.copy(),
            'current_market': self.config.current_market.value
        }

    def _pre_start_checks(self) -> None:
        """
        启动前检查 - 优化版，减少冗余日志
        """
        # 检查券商连接
        broker_ok = self._check_broker_connection()
        if not broker_ok:
            self.logger.error("❌ 券商连接检查失败")
            raise ConnectionError("券商连接检查失败")

        # 检查配置有效性
        config_errors = self.config.system.validate()
        if config_errors:
            self.logger.error(f"❌ 配置验证失败: {config_errors}")
            raise ValueError(f"配置验证失败: {config_errors}")

        # 检查策略可用性
        strategy_ok = self._check_strategy_availability()
        if not strategy_ok:
            self.logger.error("❌ 策略检查失败")
            raise ValueError("策略检查失败")

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("所有启动前检查通过（Broker连接、配置验证、策略可用性）")

    def _check_broker_connection(self) -> bool:
        """检查券商连接状态"""
        try:
            # 尝试获取账户信息来验证连接
            account_info = self.broker.get_account_info()
            if account_info:
                self.logger.info(f"券商连接正常 - 账户: {account_info.get('account_id', 'Unknown')}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"券商连接检查失败: {e}")
            return False

    def _check_strategy_availability(self) -> bool:
        """检查策略可用性"""
        try:
            strategies = self.config.get_mode_specific_strategies()

            # 检查选股策略
            for strategy_name in strategies['selection']:
                strategy = self.strategy_factory.get_selection_strategy(strategy_name)
                if not strategy:
                    self.logger.error(f"选股策略不可用: {strategy_name}")
                    return False
                # 检查策略是否有 select_stocks 方法
                if not hasattr(strategy, 'select_stocks'):
                    self.logger.error(f"选股策略缺少 select_stocks 方法: {strategy_name}")
                    return False

            # 检查风控策略
            for strategy_name in strategies['risk']:
                strategy = self.strategy_factory.get_risk_strategy(strategy_name)
                if not strategy:
                    self.logger.error(f"风控策略不可用: {strategy_name}")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"策略检查异常: {e}")
            return False

    def _run_stock_selection_mode(self) -> None:
        """
        运行选股模式 - 优化版，减少冗余日志
        """
        self.logger.info("🎯 进入选股模式 - 专注股票选择和推荐")

        # 获取启用的选股策略
        enabled_strategies = self.config.system.get_enabled_selection_strategies()
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"启用选股策略: {enabled_strategies} (类型: {type(enabled_strategies)}, 数量: {len(enabled_strategies) if enabled_strategies else 0})")

        if not enabled_strategies:
            self.logger.warning("⚠️ 没有启用的选股策略，选股模式将不会执行任何操作")
            print("\n❌ 没有启用的选股策略，无法执行选股")
            try:
                input("按回车键退出...")
            except KeyboardInterrupt:
                self.logger.info("用户中断程序")
            return

        try:
            # 检查Broker连接状态
            connection_ok = self._ensure_broker_connection()
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Broker连接检查结果: {connection_ok}")

            if not connection_ok:
                self.logger.error("❌ 无法建立broker连接，选股模式退出")
                print("\n❌ 无法连接券商服务，请检查网络连接")
                return

            self.logger.info("✅ Broker连接正常，开始执行选股分析")
            print("\n✅ Broker连接正常，开始执行选股分析...")

            # 显示正在执行的策略名称
            strategy_names = {
                'technical_analysis': '技术分析选股策略',
                'realtime_monitoring': '实时数据选股策略',
                'priority_stocks': '自选股策略',
                'mixed_strategy': '混合选股策略'
            }
            strategy_display_names = [strategy_names.get(s, s) for s in enabled_strategies]
            if strategy_display_names:
                print(f"📊 正在执行: {', '.join(strategy_display_names)}...")
            else:
                print("📊 正在执行选股策略...")

            # 执行选股
            selected_stocks = self._execute_selected_selection_strategies(enabled_strategies)
            self.logger.info(f"✅ 选股策略执行完成，返回 {len(selected_stocks)} 只股票")
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"选股结果详情: {selected_stocks}")

            # 显示选股结果
            self._display_selection_results(selected_stocks)
            self._display_console_selection_results(selected_stocks)

            # 开发模式交互
            if self.config.environment.value == 'development':
                self.logger.info("🔧 开发模式: 选股完成")
                self._show_current_status()

                print("\n" + "=" * 60)
                print("💡 提示: 按回车键退出程序...")
                print("=" * 60)

                try:
                    input()
                    self.logger.info("👋 用户确认退出")
                except KeyboardInterrupt:
                    self.logger.info("🛑 用户中断程序")
                except Exception as e:
                    self.logger.error(f"用户输入异常: {e}")

                self.running = False
                self.logger.info("✅ 选股模式正常结束")
                return

            # 生产环境循环
            cycle_count = 0
            max_cycles = self.config.system.max_selection_cycles if hasattr(self.config.system,
                                                                            'max_selection_cycles') else 100
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"最大循环次数: {max_cycles}")

            while self.running and not self._stop_event.is_set() and cycle_count < max_cycles:
                try:
                    current_time = datetime.now()
                    cycle_count += 1

                    # 检查是否应该执行选股
                    should_run = self._should_run_selection()
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"第 {cycle_count} 次循环，是否执行选股: {should_run}")

                    if should_run:
                        self.logger.info(f"⏰ 执行第 {cycle_count} 次定时选股分析...")
                        print(f"\n🔄 第 {cycle_count} 次定时选股分析...")

                        # 确保连接仍然有效
                        connection_ok = self._ensure_broker_connection()
                        if not connection_ok:
                            self.logger.error("❌ Broker连接丢失，停止选股循环")
                            print("❌ Broker连接丢失，停止选股循环")
                            break

                        selected_stocks = self._execute_selected_selection_strategies(enabled_strategies)
                        self.logger.info(f"✅ 循环选股完成，返回 {len(selected_stocks)} 只股票")

                        self._display_selection_results(selected_stocks)
                        self._display_console_selection_results(selected_stocks)
                        self._execution_stats['selection_count'] += 1
                        self._execution_stats['last_successful_run'] = current_time

                    # 等待下一次检查
                    sleep_seconds = self.config.system.selection_interval_minutes * 60
                    self.logger.info(f"⏳ 等待 {self.config.system.selection_interval_minutes} 分钟后再次检查...")
                    print(f"⏳ 等待 {self.config.system.selection_interval_minutes} 分钟后再次检查...")

                    # 分段睡眠，便于响应停止信号
                    for i in range(sleep_seconds):
                        if not self.running or self._stop_event.is_set():
                            if self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug("检测到停止信号，退出循环")
                            break
                        time.sleep(1)

                        # 每30秒输出一次等待状态
                        if i % 30 == 0 and i > 0:
                            remaining = sleep_seconds - i
                            if self.logger.isEnabledFor(logging.DEBUG):
                                self.logger.debug(f"🕒 等待中... 剩余 {remaining} 秒")
                            if remaining > 0:
                                print(f"🕒 等待中... 剩余 {remaining // 60}分{remaining % 60}秒")

                except Exception as e:
                    self._handle_error("选股模式循环", e)
                    # 🆕 添加控制台输出
                    print(f"❌ 选股循环出错: {e}")
                    # 错误后等待一段时间再继续
                    time.sleep(60)

            # 循环结束处理
            if cycle_count >= max_cycles:
                self.logger.info(f"🔚 达到最大选股循环次数: {max_cycles}")
                # 🆕 添加控制台输出
                print(f"\n🔚 达到最大选股循环次数: {max_cycles}")
            elif not self.running:
                self.logger.info("🔚 选股模式被停止")
                # 🆕 添加控制台输出
                print("\n🔚 选股模式已停止")
            else:
                self.logger.info("🔚 选股模式正常结束")
                # 🆕 添加控制台输出
                print("\n🔚 选股模式正常结束")

        except Exception as e:
            self.logger.error(f"❌ 选股模式执行失败: {e}")
            # 🆕 添加控制台输出
            print(f"\n❌ 选股模式执行失败: {e}")
            import traceback
            self.logger.error(f"详细堆栈: {traceback.format_exc()}")
        finally:
            # 确保运行状态正确设置
            self.running = False
            self.logger.info("🔚 选股模式资源清理完成")
            # 🆕 添加控制台输出
            print("🔚 系统资源清理完成")

    def _display_console_selection_results(self, selected_stocks: List[Dict]) -> None:
        """
        在控制台显示选股结果 - 用户友好的格式
        """
        print("\n" + "=" * 70)
        print("🎯 量化选股结果")
        print("=" * 70)

        if not selected_stocks:
            # 控制台提示 + 打印 debug 信息，方便直接在终端看到原始候选
            print("❌ 本次选股未找到符合条件的股票")
            print("-" * 70)
            self.logger.warning("控制台显示: 本次选股未找到符合条件的股票")
            # 将最近一次执行的原始候选尝试打印（从 execution_stats 或日志中取）
            try:
                # 如果 execution_stats 中有错误或原始候选样例，打印
                recent_errors = self._execution_stats.get('errors', [])
                print("🔎 调试信息（最近错误条目或候选样例）:")
                if recent_errors:
                    for e in recent_errors[-3:]:
                        print(f"  - {e.get('time')} | {e.get('strategy')} | {e.get('error')}")
                # 若 last_successful_run 有值，提示时间
                if self._execution_stats.get('last_successful_run'):
                    print(f"  上次成功运行时间: {self._execution_stats.get('last_successful_run')}")
                # 在 logger debug 中也输出一次合并前候选（如有）
                self.logger.debug("控制台显示时 selected_stocks 为空，建议检查日志以查看 all_selected_stocks 原始内容。")
            except Exception as _e:
                self.logger.debug(f"打印空结果调试信息失败: {_e}")
            print("=" * 70)
            return

        print(f"📊 共选中 {len(selected_stocks)} 只股票:")
        print("-" * 70)

        for i, stock in enumerate(selected_stocks, 1):
            symbol = stock.get('symbol', 'N/A')
            name = stock.get('name', 'N/A')
            # 兼容性：score 可能存在于不同字段
            score = stock.get('score', stock.get('composite_score', stock.get('final_score', 0)))
            current_price = stock.get('current_price', stock.get('snapshot', {}).get('last_price', 0))
            change_rate = stock.get('change_rate', stock.get('snapshot', {}).get('change_rate', 0))
            reason = stock.get('reason', '') or stock.get('technical_analysis', {}).get('conditions_detail',
                                                                                        {}) if isinstance(
                stock.get('technical_analysis', {}), dict) else ''
            sector = stock.get('sector', '')

            # 格式化
            try:
                change_display = f"+{change_rate:.2f}%" if float(change_rate) > 0 else f"{float(change_rate):.2f}%"
            except Exception:
                change_display = f"{change_rate}"
            try:
                price_display = f"{float(current_price):.2f}"
            except Exception:
                price_display = str(current_price)
            sector_display = f"[{sector}]" if sector else ""

            if score >= 90:
                score_emoji = "🔥"
            elif score >= 80:
                score_emoji = "⭐"
            elif score >= 70:
                score_emoji = "✅"
            else:
                score_emoji = "📈"

            print(f"{i}. {symbol} {name} {sector_display}")
            print(f"   {score_emoji} 评分: {score:.1f} | 💰 价格: {price_display} ({change_display})")
            # 简化显示理由
            if isinstance(reason, str) and reason:
                print(f"   💡 理由: {reason}")
            elif isinstance(reason, dict) and reason:
                # 显示 conditions_detail 的简短描述
                conds = reason.get('conditions_detail') if 'conditions_detail' in reason else reason
                if isinstance(conds, dict):
                    keys = [k for k, v in conds.items() if v]
                    if keys:
                        print(f"   💡 符合条件: {', '.join(keys)}")
            # 显示技术指标简要
            technical_analysis = stock.get('technical_analysis', stock.get('indicators', {}))
            if technical_analysis and isinstance(technical_analysis, dict):
                cond_count = technical_analysis.get('condition_count') or technical_analysis.get(
                    'conditions_count') or 0
                final_score = technical_analysis.get('final_score') or technical_analysis.get('total_score') or 0
                if cond_count:
                    print(f"   🔧 技术条件: {cond_count}个 | 综合分: {final_score:.1f}")

            print()

        print("=" * 70)

        # 统计信息
        total_stocks = len(selected_stocks)
        avg_score = sum((stock.get('score', stock.get('composite_score', 0)) or 0) for stock in
                        selected_stocks) / total_stocks if total_stocks else 0
        high_score_stocks = [s for s in selected_stocks if (s.get('score', s.get('composite_score', 0)) or 0) >= 80]

        print(f"📈 统计信息:")
        print(f"   • 平均评分: {avg_score:.1f}")
        print(f"   • 高分股票(≥80): {len(high_score_stocks)}只")
        print(f"   • 选股时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

    def _show_current_status(self):
        """显示当前系统状态"""
        try:
            self.logger.info("🔍 状态显示: 开始获取系统状态")
            status = self.get_system_status()
            self.logger.info("📊 当前系统状态:")
            self.logger.info(f"   - 运行状态: {'运行中' if self.running else '已停止'}")
            self.logger.info(f"   - 工作模式: {status['mode']}")
            self.logger.info(f"   - 交易市场: {status['current_market']}")
            self.logger.info(f"   - 选股次数: {status['execution_stats']['selection_count']}")
            self.logger.info(f"   - 最后选股: {status['last_selection_time']}")

            # 检查连接状态
            if hasattr(self.broker, 'is_connected'):
                conn_status = "已连接" if self.broker.is_connected() else "已断开"
                self.logger.info(f"   - Broker状态: {conn_status}")
            else:
                self.logger.info(f"   - Broker状态: 未知")

        except Exception as e:
            self.logger.error(f"获取系统状态失败: {e}")

    def _ensure_broker_connection(self) -> bool:
        """
        确保broker连接正常 - 添加调试信息
        """
        try:
            self.logger.info("🔍 连接检查: 开始检查Broker连接")

            # 检查连接状态
            if hasattr(self.broker, 'is_connected'):
                self.logger.info("🔍 连接检查: 使用 is_connected 方法")
                if not self.broker.is_connected():
                    self.logger.warning("🔄 Broker连接已断开，尝试重新连接...")
                    if hasattr(self.broker, 'connect'):
                        success = self.broker.connect()
                        self.logger.info(f"🔍 连接检查: 重新连接结果 = {success}")
                        return success
                    else:
                        self.logger.error("❌ Broker没有connect方法")
                        return False
                else:
                    self.logger.debug("🔗 Broker连接正常")
                    return True
            else:
                # 如果没有is_connected方法，尝试获取账户信息来测试连接
                self.logger.debug("🔍 连接检查: 通过账户信息测试Broker连接...")
                try:
                    account_info = self.broker.get_account_info()
                    has_info = account_info and len(account_info) > 0
                    self.logger.info(f"🔍 连接检查: 账户信息测试结果 = {has_info}")
                    return has_info
                except Exception as e:
                    self.logger.error(f"❌ Broker连接测试失败: {e}")
                    return False

        except Exception as e:
            self.logger.error(f"❌ Broker连接检查失败: {e}")
            return False

    def _run_risk_management_mode(self) -> None:
        """
        运行风控模式

        在此模式下，系统只执行风控策略，监控持仓风险。
        即使不在交易时间，也能执行风控检查并读取持仓情况。
        """
        self.logger.info("🛡️ 进入风控模式 - 专注风险监控和管理")
        
        # 设置运行状态，确保循环能够执行
        self.running = True
        self._stop_event.clear()

        enabled_strategies = self.config.system.get_enabled_risk_strategies()
        if not enabled_strategies:
            self.logger.warning("⚠️ 没有启用的风控策略，风控模式将不会执行任何操作")
            print("\n❌ 没有启用的风控策略，无法执行风控检查")
            try:
                input("按回车键退出...")
            except KeyboardInterrupt:
                self.logger.info("用户中断程序")
            return

        self.logger.info(f"启用风控策略: {enabled_strategies}")

        # 显示持仓和资金信息
        self._display_portfolio_info()
        last_portfolio_display = datetime.now()
        last_risk_result: Optional[Dict[str, Any]] = None
        
        # 立即执行一次风控检查（不等待交易时间）
        self.logger.info("🔍 立即执行首次风险检查...")
        try:
            risk_result = self._execute_selected_risk_strategies(enabled_strategies)
            self._execute_risk_actions_safe(risk_result)
            self._execution_stats['risk_check_count'] += 1
            self._execution_stats['last_successful_run'] = datetime.now()
            self.last_risk_check_time = datetime.now()
            last_risk_result = risk_result
        except Exception as e:
            self.logger.error(f"首次风控检查失败: {e}")
            self._handle_error("风控模式", e)
            last_risk_result = {'risk_level': 'UNKNOWN', 'actions': [], 'strategies': [], 'timestamp': datetime.now().isoformat()}

        # 设置风控检查间隔为30秒
        check_interval = 30  # 30秒检查一次
        status_interval = 60  # 每分钟显示一次风险状态摘要
        portfolio_interval = 600  # 每10分钟输出一次资金/持仓状态
        last_status_display = datetime.now()
        self.logger.info(f"⏱️ 风控检查间隔: {check_interval}秒，状态摘要间隔: {status_interval}秒，资金/持仓间隔: {portfolio_interval}秒")
        
        # 主循环（持续监控）
        print("\n" + "=" * 70)
        print("🔄 风控监控模式已启动")
        print(f"⏱️ 检查间隔: {check_interval}秒")
        print("💡 提示: 输入 'q' 或 'quit' 退出监控，或按 Ctrl+C 退出")
        print("=" * 70)
        
        import threading
        import queue
        
        # 创建输入队列用于非阻塞输入
        input_queue = queue.Queue()
        input_thread_running = True
        
        def input_thread():
            """后台线程处理用户输入"""
            while input_thread_running:
                try:
                    user_input = input().strip().lower()
                    if user_input in ['q', 'quit', 'exit']:
                        input_queue.put('quit')
                        break
                except (EOFError, KeyboardInterrupt):
                    input_queue.put('quit')
                    break
                except Exception:
                    pass
        
        input_thread_obj = threading.Thread(target=input_thread, daemon=True)
        input_thread_obj.start()
        
        check_count = 0
        while self.running and not self._stop_event.is_set():
            try:
                # 检查用户输入
                try:
                    user_cmd = input_queue.get_nowait()
                    if user_cmd == 'quit':
                        print("\n🛑 用户请求退出风控监控...")
                        break
                except queue.Empty:
                    pass
                
                current_time = datetime.now()

                # 每分钟显示一次风控状态摘要
                if last_risk_result and (current_time - last_status_display).total_seconds() >= status_interval:
                    self._display_risk_status_summary(last_risk_result)
                    last_status_display = current_time

                # 每10分钟显示一次资金和持仓信息
                if (current_time - last_portfolio_display).total_seconds() >= portfolio_interval:
                    self._display_portfolio_info()
                    last_portfolio_display = current_time

                # 检查是否应该执行风控检查（不依赖交易时间）
                if self._should_run_risk_check():
                    check_count += 1
                    print(f"\n{'='*70}")
                    print(f"🔍 执行第 {check_count} 次风险检查 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"{'='*70}")
                    
                    # 执行风控检查
                    risk_result = self._execute_selected_risk_strategies(enabled_strategies)
                    self._execute_risk_actions_safe(risk_result)
                    self._execution_stats['risk_check_count'] += 1
                    self._execution_stats['last_successful_run'] = current_time
                    self.last_risk_check_time = current_time
                    last_risk_result = risk_result
                    
                    # 显示下次检查倒计时
                    next_check_time = current_time + timedelta(seconds=check_interval)
                    print(f"\n⏰ 下次检查时间: {next_check_time.strftime('%H:%M:%S')} (约{check_interval}秒后)")
                    print(f"💡 输入 'q' 退出监控")
                    print(f"{'='*70}\n")

                # 等待下一次检查（分段等待，以便响应退出命令）
                wait_time = check_interval
                segment = 1  # 每秒检查一次用户输入
                while wait_time > 0 and self.running and not self._stop_event.is_set():
                    time.sleep(min(segment, wait_time))
                    wait_time -= segment
                    
                    # 检查用户输入
                    try:
                        user_cmd = input_queue.get_nowait()
                        if user_cmd == 'quit':
                            print("\n🛑 用户请求退出风控监控...")
                            break
                    except queue.Empty:
                        pass

            except KeyboardInterrupt:
                print("\n🛑 用户中断风控监控")
                self.logger.info("🛑 用户中断风控监控")
                break
            except Exception as e:
                self._handle_error("风控模式", e)
                time.sleep(10)  # 错误后等待一段时间再继续
        
        input_thread_running = False
        self.logger.info("✅ 风控模式正常结束")
        print("\n✅ 风控监控已停止")

    def _run_full_automation_mode(self) -> None:
        """
        运行全自动模式

        在此模式下，系统同时执行选股和风控策略，并进行自动化交易。
        这是最复杂的运行模式，需要特别注意错误处理。
        """
        self.logger.info("🤖 进入全自动模式 - 自动化选股、交易和风控")

        # 确保运行状态已设置（与风控模式保持一致）
        self.running = True
        self._stop_event.clear()

        # 获取启用的策略
        selection_strategies = self.config.system.get_enabled_selection_strategies()
        risk_strategies = self.config.system.get_enabled_risk_strategies()

        self.logger.info(f"全自动模式配置 - 选股策略: {selection_strategies}, 风控策略: {risk_strategies}")

        # 检查是否有启用的策略
        if not selection_strategies and not risk_strategies:
            self.logger.warning("⚠️ 没有启用的选股或风控策略，全自动模式将不会执行任何操作")
            print("\n❌ 没有启用的选股或风控策略，无法执行全自动模式")
            try:
                input("按回车键退出...")
            except KeyboardInterrupt:
                self.logger.info("用户中断程序")
            self.running = False
            return

        # 设置选股间隔为30分钟（1800秒）
        original_selection_interval = self.config.system.selection_interval_minutes
        self.config.system.selection_interval_minutes = 30
        self.logger.info(f"📅 全自动模式：选股间隔设置为30分钟")

        # 初始化时读取持仓和可用资金
        try:
            self._display_account_status()
            self.last_account_update_time = datetime.now()
        except Exception as e:
            self.logger.error(f"读取账户信息失败: {e}")

        # 主循环
        while self.running and not self._stop_event.is_set():
            try:
                current_time = datetime.now()

                # 每5分钟更新一次持仓状态
                if self._should_update_account_status():
                    try:
                        self.logger.info("📊 自动更新持仓状态...")
                        self._display_account_status()
                        self.last_account_update_time = current_time
                    except Exception as e:
                        self.logger.error(f"更新持仓状态失败: {e}")

                # 选股逻辑
                if self._should_run_selection() and selection_strategies:
                    self.logger.info("🔍 执行选股分析...")
                    print("\n" + "=" * 70)
                    print("🔍 开始执行选股分析...".center(70))
                    print("=" * 70)
                    
                    selected_stocks = self._execute_selected_selection_strategies(selection_strategies)
                    self._execute_trading_decisions(selected_stocks)
                    self.last_selection_time = current_time
                    self._execution_stats['selection_count'] += 1

                # 风控逻辑
                if self._should_run_risk_check() and risk_strategies:
                    self.logger.info("🛡️ 执行风险检查...")
                    risk_result = self._execute_selected_risk_strategies(risk_strategies)
                    self._execute_risk_actions_safe(risk_result)
                    self.last_risk_check_time = current_time
                    self._execution_stats['risk_check_count'] += 1

                self._execution_stats['last_successful_run'] = current_time

                # 等待下一次检查
                time.sleep(self.config.system.trading_check_interval_seconds)

            except Exception as e:
                self._handle_error("全自动模式", e)
                time.sleep(10)  # 错误后等待一段时间再继续
        
        # 恢复原始选股间隔
        self.config.system.selection_interval_minutes = original_selection_interval

    def _run_backtest_mode(self) -> None:
        """
        运行回测模式

        在此模式下，系统使用历史数据测试交易策略。
        """
        self.logger.info("📊 进入回测模式 - 使用历史数据验证策略")

        try:
            # 动态导入回测用例，避免循环依赖
            from .use_cases.backtest_use_case import BacktestUseCase

            # 创建回测用例
            backtest_use_case = BacktestUseCase(self.config, self.strategy_factory)

            # 交互式回测配置
            self._configure_backtest(backtest_use_case)

            # 注意：回测模式执行完成后会自动停止
            self.running = False

        except ImportError:
            self.logger.error("❌ 回测模块未找到，请确保 backtest_use_case 模块存在")
            self.running = False
        except Exception as e:
            self.logger.error(f"回测模式执行异常: {e}")
            self.running = False

    def _configure_backtest(self, backtest_use_case: Any) -> None:
        """
        配置回测参数

        Args:
            backtest_use_case: 回测用例实例
        """
        print("\n🎯 回测配置选项:")
        print("1. 快速测试 (3只股票，近期数据)")
        print("2. 完整回测 (默认股票池，完整周期)")
        print("3. 自定义股票池")
        print("4. 压力测试 (极端市场情况)")
        print("5. 退出回测")

        try:
            choice = input("请选择回测类型 (1-5): ").strip()

            if choice == '1':
                self.logger.info("选择快速测试模式")
                backtest_use_case.run_quick_test()
            elif choice == '2':
                self.logger.info("选择完整回测模式")
                backtest_use_case.run()
            elif choice == '3':
                symbols = self._get_custom_stocks()
                if symbols:
                    backtest_use_case.run(symbols=symbols)
                else:
                    self.logger.warning("未输入有效股票代码，使用完整回测")
                    backtest_use_case.run()
            elif choice == '4':
                self.logger.info("选择压力测试模式")
                backtest_use_case.run_stress_test()
            elif choice == '5':
                self.logger.info("用户退出回测模式")
            else:
                self.logger.info("使用默认完整回测")
                backtest_use_case.run()

        except Exception as e:
            self.logger.error(f"回测配置异常: {e}")

    def _execute_selected_selection_strategies(self, selected_strategies: List[str]) -> List[Dict[str, Any]]:
        """
        执行选定的选股策略 - 添加详细调试和返回结构规范化
        """
        self.logger.info(f"🔍 开始执行 {len(selected_strategies)} 个选股策略...")
        # 获取股票池时详细记录
        self.logger.info("📊 正在获取股票池...")
        stock_universe = self._get_stock_universe()
        self.logger.info(f"✅ 获取到股票池: {len(stock_universe)} 只股票")

        if len(stock_universe) > 0:
            # 股票池样例改为DEBUG级别，减少日志噪音
            self.logger.debug(f"📋 股票池样例 (前10只): {stock_universe[:10]}")
        else:
            self.logger.warning("⚠️ 股票池为空，选股策略需要自行获取全市场数据")

        self.logger.debug(f"📋 策略列表: {selected_strategies}")

        all_selected_stocks = []
        successful_strategies = 0

        for strategy_name in selected_strategies:
            try:
                self.logger.info(f"🎯 正在执行策略: {strategy_name}")

                # 从工厂获取策略实例
                strategy = self.strategy_factory.get_selection_strategy(strategy_name)
                if not strategy:
                    self.logger.error(f"❌ 选股策略未找到: {strategy_name}")
                    continue

                self.logger.info(f"✅ 获取策略实例: {type(strategy).__name__}")

                # 临时为 technical selection 打开 debug_relax_screening 以便调试（非破坏性）
                try:
                    if hasattr(strategy, 'parameters') and isinstance(strategy.parameters, dict):
                        if 'debug_relax_screening' in strategy.parameters:
                            # strategy.parameters['debug_relax_screening'] = True
                            self.logger.debug(f"已为策略 {strategy_name} 设置 debug_relax_screening=True")
                except Exception as _e:
                    self.logger.debug(f"设置 debug_relax_screening 失败: {_e}")

                # 获取股票池并执行选股
                stock_universe = self._get_stock_universe()
                self.logger.info(f"📊 获取股票池: {len(stock_universe)} 只股票")
                self.logger.debug(f"股票池详情（前20）: {stock_universe[:20]}")

                if not stock_universe:
                    self.logger.warning("⚠️ 股票池为空，跳过选股")
                    continue

                # 修复：确保策略有 select_stocks 方法
                if hasattr(strategy, 'select_stocks'):
                    self.logger.info(f"🚀 开始执行 {strategy_name} 的选股逻辑...")

                    # 🎯 关键优化：优先使用无K线选股方法
                    if hasattr(strategy, 'select_stocks_no_kline'):
                        self.logger.info(f"🎯 使用无K线选股方法: {strategy_name}")
                        selected = strategy.select_stocks_no_kline(stock_universe) or []
                    else:
                        # 回退到传统选股方法
                        self.logger.info(f"⚠️ 使用传统选股方法（需要K线）: {strategy_name}")
                        selected = strategy.select_stocks(stock_universe) or []

                    self.logger.info(f"✅ {strategy_name} 选股完成: {len(selected)} 只股票")

                    # 规范化每个返回项，容错不同字段名
                    normed = []
                    for item in selected:
                        if not isinstance(item, dict):
                            self.logger.debug(f"策略返回非 dict 项，尝试忽略或转换: {item}")
                            continue
                        # 规范 symbol 字段 (兼容 code)
                        if 'symbol' not in item and 'code' in item:
                            item['symbol'] = item.get('code')
                        # 规范 score 字段 (兼容 composite_score / final_score)
                        if 'score' not in item:
                            if 'composite_score' in item:
                                item['score'] = item.get('composite_score')
                            elif 'final_score' in item:
                                item['score'] = item.get('final_score')
                            elif 'multi_score' in item:
                                item['score'] = item.get('multi_score')
                            else:
                                # 尝试从 indicators.total_score 取值
                                ind = item.get('indicators') or item.get('technical_analysis') or {}
                                item['score'] = float(ind.get('total_score', ind.get('final_score', 0)) or 0)
                        # 确保 numeric
                        try:
                            item['score'] = float(item.get('score') or 0.0)
                        except Exception:
                            item['score'] = 0.0

                        # 规范化名称字段
                        if 'name' not in item and 'snapshot' in item and isinstance(item['snapshot'], dict):
                            item['name'] = item['snapshot'].get('name', item.get('symbol'))

                        normed.append(item)

                    if normed:
                        self.logger.debug(f"规范化后样例项: {normed[0]}")
                    else:
                        self.logger.debug(f"{strategy_name} 返回空或无有效项")

                    all_selected_stocks.extend(normed)
                    successful_strategies += 1
                else:
                    self.logger.error(f"❌ 策略 {strategy_name} 缺少 select_stocks 方法")
                    continue

            except Exception as e:
                self.logger.error(f"❌ 选股策略 {strategy_name} 执行失败: {e}")
                import traceback
                self.logger.error(f"详细堆栈: {traceback.format_exc()}")
                self._execution_stats['errors'].append({
                    'time': datetime.now(),
                    'strategy': strategy_name,
                    'error': str(e),
                    'type': 'selection'
                })

        # 合并和去重选股结果（注意：在合并前打印 debug 信息）
        self.logger.debug(f"合并前总候选数: {len(all_selected_stocks)}")
        final_stocks = self._merge_selection_results(all_selected_stocks)
        self.last_selection_time = datetime.now()

        self.logger.info(f"🎯 选股完成总结: {successful_strategies}/{len(selected_strategies)} 个策略成功, "
                         f"合并后选中 {len(final_stocks)} 只股票")

        if final_stocks:
            self.logger.info(f"🏆 最终选股结果: {[stock.get('symbol', 'N/A') for stock in final_stocks]}")
        else:
            # 打印合并前的原始候选，便于定位问题
            self.logger.warning("📭 所有策略都没有选中股票，打印原始候选以便调试")
            self.logger.debug(f"原始候选样例（最多50条）: {all_selected_stocks[:50]}")

        return final_stocks

    def _execute_selected_risk_strategies(self, selected_strategies: List[str]) -> Dict[str, Any]:
        """
        执行选定的风控策略

        Args:
            selected_strategies: 要执行的风控策略名称列表

        Returns:
            Dict[str, Any]: 风控检查结果
        """
        combined_risk_result: Dict[str, Any] = {
            'risk_level': 'LOW',
            'actions': [],
            'strategies': [],
            'timestamp': datetime.now().isoformat(),
            'portfolio_snapshot': None
        }

        if not selected_strategies:
            self.logger.warning("没有启用的风控策略")
            return combined_risk_result

        successful_strategies = 0

        for strategy_name in selected_strategies:
            try:
                strategy = self.strategy_factory.get_risk_strategy(strategy_name)
                if not strategy:
                    self.logger.warning(f"⚠️ 风控策略未找到: {strategy_name}")
                    continue

                # 安全获取投资组合和市场数据
                portfolio = self._get_portfolio_safe()
                market_data = self._get_current_market_data_safe(portfolio)

                # 执行风控策略
                execution_result = strategy.execute({
                    "portfolio": portfolio,
                    "market_data": market_data
                })

                # 处理 ExecutionResult 对象
                if hasattr(execution_result, 'data') and isinstance(execution_result.data, dict):
                    # 从 ExecutionResult 中提取 data 字段
                    risk_result = execution_result.data
                elif isinstance(execution_result, dict):
                    # 如果已经是字典，直接使用
                    risk_result = execution_result
                else:
                    # 尝试转换为字典
                    self.logger.warning(f"风控策略 {strategy_name} 返回了非预期类型: {type(execution_result)}")
                    if hasattr(execution_result, '__dict__'):
                        risk_result = execution_result.__dict__
                    else:
                        risk_result = {'risk_level': 'UNKNOWN', 'actions': []}

                # 记录策略执行结果
                strategy_result: Dict[str, Any] = {
                    'name': strategy.name,
                    'risk_level': risk_result.get('risk_level', 'UNKNOWN'),
                    'timestamp': datetime.now().isoformat()
                }

                # 记录详细的风险信息（如果有）
                if 'risk_metrics' in risk_result:
                    strategy_result['risk_metrics'] = risk_result['risk_metrics']

                combined_risk_result['strategies'].append(strategy_result)
                combined_risk_result['actions'].extend(risk_result.get('actions', []))
                successful_strategies += 1

                self.logger.debug(f"✅ {strategy.name} 风控检查完成: {strategy_result['risk_level']}")

            except Exception as e:
                self.logger.error(f"❌ 风控策略 {strategy_name} 执行失败: {e}")
                self._execution_stats['errors'].append({
                    'time': datetime.now(),
                    'strategy': strategy_name,
                    'error': str(e),
                    'type': 'risk'
                })

                combined_risk_result['strategies'].append({
                    'name': strategy_name,
                    'risk_level': 'ERROR',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        # 确定总体风险等级
        combined_risk_result['risk_level'] = self._determine_overall_risk_level(
            combined_risk_result['strategies'])

        # 记录投资组合快照
        try:
            portfolio = self._get_portfolio_safe()
            combined_risk_result['portfolio_snapshot'] = {
                'total_assets': getattr(portfolio, 'total_assets', 0),
                'available_cash': getattr(portfolio, 'available_cash', 0),
                'position_count': len(getattr(portfolio, 'positions', {})),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.warning(f"无法获取投资组合快照: {e}")

        self.last_risk_check_time = datetime.now()

        self.logger.info(f"🛡️ 风控检查完成: {successful_strategies}/{len(selected_strategies)} 个策略成功, "
                         f"总体风险等级: {combined_risk_result['risk_level']}")
        return combined_risk_result

    def _get_portfolio_safe(self) -> Any:
        """
        安全获取投资组合信息

        Returns:
            Any: 投资组合对象或模拟对象
        """
        try:
            # 优先使用 portfolio_manager
            if (self.portfolio_manager and
                    hasattr(self.portfolio_manager, 'get_current_portfolio')):
                portfolio = self.portfolio_manager.get_current_portfolio()
                if portfolio is not None:
                    return portfolio

            # 备用方案：直接从 broker 获取
            return self._create_simple_portfolio_from_broker()

        except Exception as e:
            self.logger.error(f"获取投资组合失败: {e}")
            return self._create_empty_portfolio()
    
    def _display_account_status(self) -> None:
        """
        显示账户状态（持仓和可用资金）
        """
        try:
            # 获取账户信息
            account_info = self.broker.get_account_info()
            available_cash = account_info.get('available_cash', 0)
            total_assets = account_info.get('total_assets', 0)
            market_value = account_info.get('market_value', 0)
            cash = account_info.get('cash', 0)
            frozen_cash = account_info.get('frozen_cash', 0)

            # 获取持仓
            positions = self.broker.get_positions()
            
            # 计算持仓市值（从持仓数据计算，用于验证）
            calculated_market_value = 0
            if positions:
                symbols = list(positions.keys())
                market_data = self.broker.get_market_snapshot(symbols) if symbols else {}
                for symbol, pos in positions.items():
                    qty = pos.get('quantity', 0)
                    current_price = pos.get('cost_price', 0)  # 默认使用成本价
                    if symbol in market_data:
                        current_price = market_data[symbol].get('last_price', current_price)
                    calculated_market_value += qty * current_price if current_price > 0 else 0
            
            # 验证数据一致性
            cash_plus_market_value = available_cash + calculated_market_value
            data_consistency = abs(total_assets - cash_plus_market_value) < 100  # 允许100 HKD的误差
            
            current_time = datetime.now()
            print("\n" + "=" * 70)
            print("💰 账户状态".center(70))
            print(f"  检查时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 70)
            print(f"  总资产: {total_assets:,.2f} HKD")
            print(f"  可用资金: {available_cash:,.2f} HKD")
            if frozen_cash > 0:
                print(f"  冻结资金: {frozen_cash:,.2f} HKD")
            if cash != available_cash:
                print(f"  总现金: {cash:,.2f} HKD")
            print(f"  持仓市值（Broker）: {market_value:,.2f} HKD")
            print(f"  持仓市值（计算）: {calculated_market_value:,.2f} HKD")
            print(f"  持仓数量: {len(positions)} 只")
            
            # 数据一致性检查
            if not data_consistency:
                print(f"\n  ⚠️  数据一致性检查:")
                print(f"     总资产: {total_assets:,.2f} HKD")
                print(f"     可用资金 + 持仓市值: {cash_plus_market_value:,.2f} HKD")
                print(f"     差异: {total_assets - cash_plus_market_value:,.2f} HKD")
                self.logger.warning(f"数据不一致: 总资产 {total_assets:,.2f} != 可用资金+持仓市值 {cash_plus_market_value:,.2f}")
            else:
                print(f"\n  ✅ 数据一致性检查通过")
                self.logger.debug(f"数据一致性: 总资产 {total_assets:,.2f} ≈ 可用资金+持仓市值 {cash_plus_market_value:,.2f}")
            
            if positions:
                print("\n  📊 当前持仓:")
                # 获取持仓的市场数据以获取现价
                symbols = list(positions.keys())
                market_data = self.broker.get_market_snapshot(symbols) if symbols else {}
                
                for i, (symbol, pos) in enumerate(positions.items(), 1):
                    qty = pos.get('quantity', 0)
                    cost_price = pos.get('cost_price', 0)
                    
                    # 获取现价和股票名称
                    current_price = cost_price  # 默认使用成本价
                    stock_name = symbol  # 默认使用代码
                    if symbol in market_data:
                        market_info = market_data[symbol]
                        current_price = market_info.get('last_price', cost_price)
                        stock_name = market_info.get('name', symbol)  # 获取股票名称
                    
                    # 计算市值和盈亏
                    market_val = qty * current_price if current_price > 0 else 0
                    cost_val = qty * cost_price if cost_price > 0 else 0
                    profit_loss = market_val - cost_val
                    profit_loss_pct = (profit_loss / cost_val * 100) if cost_val > 0 else 0
                    
                    # 格式化显示
                    profit_display = f"+{profit_loss:,.2f}" if profit_loss >= 0 else f"{profit_loss:,.2f}"
                    profit_pct_display = f"+{profit_loss_pct:.2f}%" if profit_loss_pct >= 0 else f"{profit_loss_pct:.2f}%"
                    
                    print(f"    {i}. {symbol:12s} {stock_name}")
                    print(f"        数量: {qty:,} 股 | 成本价: {cost_price:.2f} | 现价: {current_price:.2f} | 市值: {market_val:,.2f} | 盈亏: {profit_display} ({profit_pct_display})")
            else:
                print("\n  📊 当前持仓: 无")
            
            print("=" * 70)
            
            self.logger.info(f"账户状态 - 可用资金: {available_cash:,.2f}, 持仓: {len(positions)} 只, 检查时间: {current_time.isoformat()}")
            
        except Exception as e:
            self.logger.error(f"获取账户状态失败: {e}")
            print(f"\n❌ 获取账户状态失败: {e}")

    def _display_portfolio_info(self) -> None:
        """
        显示持仓和资金信息
        """
        try:
            print("\n" + "=" * 70)
            print("📊 账户持仓和资金信息")
            print("=" * 70)
            
            # 获取账户信息
            account_info = self.broker.get_account_info()
            if account_info:
                total_assets = account_info.get('total_assets', 0) or account_info.get('total_asset_value', 0) or 0
                available_cash = (account_info.get('available_cash', 0) or 
                                 account_info.get('cash', 0) or 
                                 account_info.get('available_funds', 0) or 0)
                frozen_cash = account_info.get('frozen_cash', 0) or 0
                
                print(f"\n💰 资金信息:")
                print(f"   总资产: {total_assets:,.2f} HKD")
                print(f"   可用资金: {available_cash:,.2f} HKD")
                if frozen_cash > 0:
                    print(f"   冻结资金: {frozen_cash:,.2f} HKD")
                print()
            else:
                print("   ⚠️ 无法获取账户信息")
                print()
            
            # 获取持仓信息
            portfolio = self._get_portfolio_safe()
            positions = getattr(portfolio, 'positions', {})
            
            if positions:
                print(f"\n  📈 持仓信息 (共 {len(positions)} 只股票):")
                print("  " + "-" * 66)
                
                # 获取持仓的市场数据
                symbols = list(positions.keys())
                market_data = self._get_current_market_data_safe(portfolio)
                
                for i, (symbol, position) in enumerate(positions.items(), 1):
                    quantity = getattr(position, 'quantity', 0)
                    cost_price = getattr(position, 'cost_price', 0)
                    current_price = getattr(position, 'current_price', 0)
                    
                    # 尝试从市场数据获取当前价格
                    if symbol in market_data:
                        market_info = market_data[symbol]
                        current_price = market_info.get('last_price', current_price)
                        change_rate = market_info.get('change_rate', 0) or 0
                    else:
                        change_rate = 0
                    
                    # 计算持仓市值和盈亏
                    market_value = quantity * current_price if current_price > 0 else 0
                    cost_value = quantity * cost_price if cost_price > 0 else 0
                    profit_loss = market_value - cost_value
                    profit_loss_pct = (profit_loss / cost_value * 100) if cost_value > 0 else 0
                    
                    # 显示持仓信息
                    change_display = f"+{change_rate:.2f}%" if change_rate > 0 else f"{change_rate:.2f}%"
                    profit_display = f"+{profit_loss:,.2f}" if profit_loss > 0 else f"{profit_loss:,.2f}"
                    profit_pct_display = f"+{profit_loss_pct:.2f}%" if profit_loss_pct > 0 else f"{profit_loss_pct:.2f}%"
                    
                    print(f"    {i}. {symbol:12s}")
                    print(f"        数量: {quantity:6,} 股 | 成本价: {cost_price:7.2f} | 现价: {current_price:7.2f} ({change_display})")
                    print(f"        市值: {market_value:12,.2f} HKD | 盈亏: {profit_display:>12s} HKD ({profit_pct_display})")
            else:
                print("\n  📭 当前无持仓")
            
            print("=" * 70)
            
        except Exception as e:
            self.logger.error(f"显示持仓信息失败: {e}")
            print(f"\n⚠️ 无法显示持仓信息: {e}\n")

    def _display_risk_status_summary(self, risk_result: Dict[str, Any]) -> None:
        """
        显示风控状态摘要，每分钟打印一次，便于高度监控。
        """
        try:
            risk_level = risk_result.get('risk_level', 'UNKNOWN')
            actions = risk_result.get('actions', [])
            strategies = risk_result.get('strategies', [])
            snapshot = risk_result.get('portfolio_snapshot', {})
            timestamp = risk_result.get('timestamp', datetime.now().isoformat())

            print("\n" + "-" * 60)
            print("🛡️ 风控状态摘要".center(60))
            print(f"  风险等级: {risk_level}")
            print(f"  策略数量: {len(strategies)} | 行动记录: {len(actions)}条")
            print(f"  总资产: {snapshot.get('total_assets', 'N/A')} | 可用资金: {snapshot.get('available_cash', 'N/A')}")
            if actions:
                preview_actions = ", ".join(str(a) for a in actions[:3])
                print(f"  最近执行动作: {preview_actions}{'...' if len(actions) > 3 else ''}")
            print(f"  更新时间: {timestamp}")
            print("-" * 60 + "\n")
        except Exception as e:
            self.logger.debug(f"风险状态摘要打印异常: {e}")

    def _create_portfolio_from_broker(self) -> Optional['Portfolio']:
        """
        从broker创建Portfolio对象

        Returns:
            Portfolio: 投资组合对象，失败返回None
        """
        try:
            from quant_system.domain.entities.portfolio import Portfolio, Position
            
            # 获取账户信息
            account_info = self.broker.get_account_info()
            if not account_info:
                self.logger.error("无法获取账户信息")
                return None
            
            # 获取持仓
            positions_dict = self.broker.get_positions()
            
            # 创建Portfolio对象
            portfolio = Portfolio(
                account_id=str(account_info.get('account_id', 'default')),
                total_assets=account_info.get('total_assets', 0),
                cash=account_info.get('cash', 0),
                available_cash=account_info.get('available_cash', 0),
                initial_capital=account_info.get('total_assets', 0)
            )
            
            # 更新持仓
            for symbol, position_info in positions_dict.items():
                if isinstance(position_info, dict):
                    quantity = position_info.get('quantity', 0)
                    cost_price = position_info.get('cost_price', 0)
                    if quantity > 0:
                        portfolio.add_position(symbol, quantity, cost_price)
            
            self.logger.debug(f"从Broker创建投资组合: {portfolio.position_count}个持仓")
            return portfolio
            
        except Exception as e:
            self.logger.error(f"创建投资组合失败: {e}")
            return None

    def _create_simple_portfolio_from_broker(self) -> Any:
        """
        从 broker 创建简化版投资组合

        Returns:
            Any: 简化版投资组合对象
        """
        try:
            positions_dict = self.broker.get_positions()
            account_info = self.broker.get_account_info()

            # 简化的投资组合类
            class SimplePosition:
                def __init__(self, symbol: str, quantity: int, cost_price: float = 0.0):
                    self.symbol = symbol
                    self.quantity = quantity
                    self.cost_price = cost_price
                    self.current_price = 0.0

            class SimplePortfolio:
                def __init__(self, positions: Dict, total_assets: float = 0.0,
                             available_cash: float = 0.0):
                    self.positions = positions
                    self.total_assets = total_assets
                    self.available_cash = available_cash
                    self.peak_value = total_assets
                    self.timestamp = datetime.now()

            positions = {}
            for symbol, position_info in positions_dict.items():
                if isinstance(position_info, dict):
                    quantity = position_info.get('quantity', 0)
                    cost_price = position_info.get('cost_price', 0) or position_info.get('avg_price', 0)
                else:
                    quantity = position_info
                    cost_price = 0.0

                if quantity > 0:
                    positions[symbol] = SimplePosition(symbol, quantity, cost_price)

            portfolio = SimplePortfolio(
                positions=positions,
                total_assets=account_info.get('total_assets', 0.0),
                available_cash=(
                        account_info.get('available_cash')
                        or account_info.get('cash')
                        or account_info.get('available_funds')
                        or 0.0
                )
            )

            self.logger.debug(f"从Broker创建投资组合: {len(positions)}个持仓")
            return portfolio

        except Exception as e:
            self.logger.error(f"从Broker创建投资组合失败: {e}")
            return self._create_empty_portfolio()

    def _create_empty_portfolio(self) -> Any:
        """
        创建空投资组合

        Returns:
            Any: 空投资组合对象
        """

        class SimplePortfolio:
            def __init__(self):
                self.positions = {}
                self.total_assets = 0.0
                self.available_cash = 0.0
                self.peak_value = 0.0
                self.timestamp = datetime.now()

        return SimplePortfolio()

    def _get_current_market_data_safe(self, portfolio: Any) -> Dict[str, Any]:
        """
        安全获取当前市场数据

        Args:
            portfolio: 投资组合对象

        Returns:
            Dict[str, Any]: 市场数据字典
        """
        try:
            symbols = list(getattr(portfolio, 'positions', {}).keys())
            if not symbols:
                return {}

            market_data = self.broker.get_market_snapshot(symbols)
            return market_data or {}

        except Exception as e:
            self.logger.error(f"获取市场数据失败: {e}")
            return {}

    def _execute_risk_actions_safe(self, risk_result: Dict[str, Any]) -> None:
        """
        安全执行风控动作

        根据风控检查结果执行相应的交易动作（如卖出、减仓等）

        Args:
            risk_result: 风控检查结果
        """
        try:
            risk_level = risk_result.get('risk_level', 'UNKNOWN')
            actions = risk_result.get('actions', [])
            strategy_count = len(risk_result.get('strategies', []))

            self.logger.info(f"📊 风控检查汇总 - 策略数: {strategy_count}, "
                             f"风险等级: {risk_level}, 建议动作: {len(actions)}个")

            # 根据风险等级采取不同的日志级别
            if risk_level in ['HIGH', 'CRITICAL']:
                self.logger.warning(f"🚨 高风险警报! 等级: {risk_level}")
                for i, action in enumerate(actions, 1):
                    self.logger.warning(f"🛑 建议动作 {i}: {action.get('action')} - "
                                        f"原因: {action.get('reason', '未指定')}")

                # 在监控模式下，可以触发警报
                if self.system_monitor:
                    self.system_monitor.trigger_alert(
                        f"高风险警报: {risk_level}",
                        "risk_management"
                    )

            elif risk_level == 'MEDIUM':
                self.logger.info(f"⚠️ 中等风险提醒: {risk_level}")
                for i, action in enumerate(actions, 1):
                    self.logger.info(f"💡 建议动作 {i}: {action.get('action')} - "
                                     f"原因: {action.get('reason', '未指定')}")

            elif actions:
                self.logger.info("💡 低风险建议:")
                for i, action in enumerate(actions, 1):
                    self.logger.info(f"  建议 {i}: {action.get('action')} - "
                                     f"原因: {action.get('reason', '未指定')}")

            # 执行具体的风控动作
            if actions:
                self._execute_risk_actions(actions, risk_level)

            # 记录风险检查结果（用于分析和监控）
            self._log_risk_result(risk_result)

        except Exception as e:
            self.logger.error(f"处理风控结果失败: {e}")

    def _execute_risk_actions(self, actions: List[Dict[str, Any]], risk_level: str) -> None:
        """
        执行风控动作（卖出、减仓等）

        Args:
            actions: 风控动作列表
            risk_level: 风险等级
        """
        if not self.broker:
            self.logger.warning("Broker不可用，无法执行风控动作")
            return

        try:
            # 获取当前持仓和市场数据
            portfolio = self._get_portfolio_safe()
            if not portfolio:
                self.logger.warning("无法获取投资组合，跳过风控动作执行")
                return

            symbols = list(portfolio.positions.keys())
            if not symbols:
                return

            market_data = self.broker.get_market_snapshot(symbols) if symbols else {}

            executed_count = 0
            for action in actions:
                action_type = action.get('action', '')
                symbol = action.get('symbol')
                
                if not symbol:
                    # 没有指定具体股票的动作，只记录日志
                    self.logger.info(f"风控建议: {action_type} - {action.get('reason', '')}")
                    continue

                # 检查持仓是否存在
                if symbol not in portfolio.positions:
                    self.logger.warning(f"风控动作: {symbol} 不在持仓中，跳过")
                    continue

                position = portfolio.positions[symbol]
                current_quantity = getattr(position, 'quantity', 0)
                
                if current_quantity <= 0:
                    self.logger.warning(f"风控动作: {symbol} 持仓数量为0，跳过")
                    continue

                # 获取当前价格
                if symbol in market_data:
                    current_price = market_data[symbol].get('last_price', 0)
                else:
                    current_price = getattr(position, 'current_price', getattr(position, 'cost_price', 0))

                if current_price <= 0:
                    self.logger.warning(f"风控动作: {symbol} 无法获取有效价格，跳过")
                    continue

                # 根据动作类型执行相应操作
                if action_type in ['REDUCE_POSITION', 'DIVERSIFY']:
                    # 减仓操作
                    sell_quantity = action.get('quantity', 0)
                    
                    # 如果没有指定数量，默认卖出50%
                    if sell_quantity <= 0:
                        sell_quantity = max(100, (current_quantity // 2) // 100 * 100)  # 至少1手，向下取整到整手数
                    
                    # 确保不超过持仓数量
                    sell_quantity = min(sell_quantity, current_quantity)
                    
                    # 确保是整手数（港股100股为1手）
                    lot_size = 100
                    sell_quantity = (sell_quantity // lot_size) * lot_size
                    
                    if sell_quantity < lot_size:
                        self.logger.warning(f"风控动作: {symbol} 计算出的卖出数量 {sell_quantity} 不足1手，跳过")
                        continue

                    # 执行卖出订单
                    self.logger.info(f"🛡️ 执行风控减仓: {symbol} x {sell_quantity} @ {current_price:.2f} - {action.get('reason', '')}")
                    
                    success = self.broker.place_order(
                        symbol=symbol,
                        quantity=sell_quantity,
                        price=current_price,
                        side='SELL',
                        order_type='MARKET',
                        remark=f"风控减仓-{action.get('reason', '')}"
                    )

                    if success:
                        self.logger.info(f"✅ 风控减仓成功: {symbol} x {sell_quantity} @ {current_price:.2f}")
                        executed_count += 1
                        
                        # 更新Portfolio（模拟，实际应该从broker重新获取）
                        if symbol in portfolio.positions:
                            position = portfolio.positions[symbol]
                            remaining_quantity = current_quantity - sell_quantity
                            if remaining_quantity > 0:
                                # 更新持仓数量
                                position.quantity = remaining_quantity
                            else:
                                # 如果全部卖出，移除持仓
                                del portfolio.positions[symbol]
                    else:
                        self.logger.error(f"❌ 风控减仓失败: {symbol} x {sell_quantity}")

                elif action_type in ['STOP_LOSS', 'TRAILING_STOP', 'VOLATILITY_STOP', 'TECHNICAL_EXIT', 'TIME_EXIT']:
                    # 止损相关操作，根据action类型决定卖出数量
                    if action_type in ['STOP_LOSS', 'TRAILING_STOP', 'VOLATILITY_STOP', 'TIME_EXIT']:
                        # 止损或时间退出，卖出全部持仓
                        sell_quantity = action.get('quantity', current_quantity)
                    else:
                        # 技术面退出，可能只卖出部分（如减半仓）
                        sell_quantity = action.get('quantity', current_quantity)
                    
                    # 确保是整手数（港股100股为1手）
                    lot_size = 100
                    sell_quantity = (sell_quantity // lot_size) * lot_size
                    sell_quantity = min(sell_quantity, current_quantity)  # 不超过持仓数量
                    
                    if sell_quantity > 0:
                        action_name_map = {
                            'STOP_LOSS': '止损',
                            'TRAILING_STOP': '移动止损',
                            'VOLATILITY_STOP': '波动率止损',
                            'TECHNICAL_EXIT': '技术面退出',
                            'TIME_EXIT': '时间退出'
                        }
                        action_name = action_name_map.get(action_type, action_type)
                        
                        self.logger.warning(f"🛑 执行风控{action_name}: {symbol} x {sell_quantity} @ {current_price:.2f} - {action.get('reason', '')}")
                        
                        success = self.broker.place_order(
                            symbol=symbol,
                            quantity=sell_quantity,
                            price=current_price,
                            side='SELL',
                            order_type='MARKET',
                            remark=f"风控{action_name}-{action.get('reason', '')}"
                        )

                        if success:
                            self.logger.info(f"✅ 风控{action_name}成功: {symbol} x {sell_quantity} @ {current_price:.2f}")
                            executed_count += 1
                            
                            # 更新持仓
                            if symbol in portfolio.positions:
                                position = portfolio.positions[symbol]
                                remaining_quantity = current_quantity - sell_quantity
                                if remaining_quantity > 0:
                                    # 更新持仓数量
                                    position.quantity = remaining_quantity
                                else:
                                    # 如果全部卖出，移除持仓
                                    del portfolio.positions[symbol]
                        else:
                            self.logger.error(f"❌ 风控{action_name}失败: {symbol} x {sell_quantity}")

            if executed_count > 0:
                self.logger.info(f"✅ 风控动作执行完成: 成功执行 {executed_count} 个动作")

        except Exception as e:
            self.logger.error(f"执行风控动作失败: {e}")
            import traceback
            self.logger.error(f"详细错误: {traceback.format_exc()}")

    def _log_risk_result(self, risk_result: Dict[str, Any]) -> None:
        """
        记录风控检查结果

        Args:
            risk_result: 风控检查结果
        """
        try:
            # 这里可以扩展为将风险结果保存到数据库或文件
            risk_level = risk_result.get('risk_level', 'UNKNOWN')
            strategy_count = len(risk_result.get('strategies', []))

            self.logger.debug(f"风控结果记录 - 等级: {risk_level}, 策略数: {strategy_count}")

        except Exception as e:
            self.logger.error(f"记录风控结果失败: {e}")

    def _should_update_account_status(self) -> bool:
        """
        判断是否应该更新账户状态（持仓和可用资金）
        
        每5分钟更新一次
        
        Returns:
            bool: 是否应该更新账户状态
        """
        if not self.last_account_update_time:
            return True
        
        time_diff = datetime.now() - self.last_account_update_time
        update_interval_seconds = 5 * 60  # 5分钟 = 300秒
        
        return time_diff.total_seconds() >= update_interval_seconds

    def _should_run_selection(self) -> bool:
        """
        判断是否应该执行选股

        Returns:
            bool: 是否应该执行选股
        """
        if not self.last_selection_time:
            return True

        time_diff = datetime.now() - self.last_selection_time
        interval_seconds = self.config.system.selection_interval_minutes * 60

        # 如果配置允许非交易时间，就不检查交易时间
        if self.config.system.allow_non_trading_hours:
            return time_diff.total_seconds() >= interval_seconds
        else:
            # 原有逻辑：检查交易时间
            return (time_diff.total_seconds() >= interval_seconds and
                    self._is_trading_hours())

    def _should_run_risk_check(self) -> bool:
        """
        判断是否应该执行风控检查
        
        风控检查不依赖交易时间，可以随时执行。

        Returns:
            bool: 是否应该执行风控检查
        """
        if not self.last_risk_check_time:
            return True

        time_diff = datetime.now() - self.last_risk_check_time
        return time_diff.total_seconds() >= self.config.system.risk_check_interval_seconds

    def _is_trading_hours(self) -> bool:
        """
        判断当前是否在交易时间内

        Returns:
            bool: 是否在交易时间内
        """
        try:
            # 获取当前市场配置
            market_config = self.config.get_current_market_config()
            return market_config.is_market_open()
        except Exception as e:
            self.logger.warning(f"检查交易时间失败: {e}，默认返回True")
            return True

    def _get_stock_universe(self) -> List[str]:
        """
        获取全市场股票池 - 修复版本
        支持选股模式和全自动模式的全市场选股
        """
        try:
            self.logger.info("🌍 开始获取全市场股票池...")

            # 方法1：优先使用技术选股策略的全市场获取能力
            technical_strategy = self.strategy_factory.get_selection_strategy("technical_analysis")
            if technical_strategy and hasattr(technical_strategy, '_get_full_market_universe'):
                self.logger.info("🎯 调用技术选股策略的全市场获取方法")
                full_universe = technical_strategy._get_full_market_universe()
                if full_universe and len(full_universe) > 0:
                    self.logger.info(f"✅ 技术策略返回全市场股票: {len(full_universe)} 只")
                    return full_universe
                else:
                    self.logger.warning("⚠️ 技术策略返回空股票列表")

            # 方法2：直接从broker获取港股主板股票
            self.logger.info("🔧 备用方案：从broker获取港股主板股票")
            if self.broker and hasattr(self.broker, 'get_stock_basicinfo'):
                try:
                    from futu import Market, SecurityType, RET_OK

                    # 获取港股主板股票
                    ret, df = self.broker.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
                    if ret == RET_OK and df is not None and not df.empty:
                        codes = df['code'].astype(str).tolist()
                        codes = [c for c in codes if isinstance(c, str) and c.strip()]
                        # 标准化代码格式
                        normalized = [c if c.startswith('HK.') else f"HK.{c}" for c in codes]
                        self.logger.info(f"📈 从broker获取港股主板股票: {len(normalized)} 只")

                        # 限制数量避免内存问题（可根据需要调整）
                        max_stocks = 4000  # 港股主板大约1500-2000只
                        if len(normalized) > max_stocks:
                            normalized = normalized[:max_stocks]
                            self.logger.info(f"📊 限制分析数量为前 {max_stocks} 只股票")

                        return normalized
                    else:
                        self.logger.warning("broker返回空数据")
                except Exception as e:
                    self.logger.warning(f"从broker获取股票失败: {e}")

            # 方法3：返回空列表，让选股策略自行处理
            self.logger.info("📋 返回空列表，让选股策略使用内置的全市场获取逻辑")
            return []

        except Exception as e:
            self.logger.error(f"❌ 获取股票池失败: {e}")
            # 出错时返回空，让策略自行处理
            return []

    def _merge_selection_results(self, all_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        合并选股结果

        Args:
            all_stocks: 所有选股结果

        Returns:
            List[Dict[str, Any]]: 合并后的选股结果
        """
        seen_symbols = set()
        merged = []

        # 按评分排序
        for stock in sorted(all_stocks, key=lambda x: x.get('score', 0), reverse=True):
            symbol = stock.get('symbol')
            if symbol and symbol not in seen_symbols:
                merged.append(stock)
                seen_symbols.add(symbol)

        # 限制最大股票数量
        max_stocks = getattr(self.config.trading, 'max_stocks', 5)
        final_result = merged[:max_stocks]

        self.logger.debug(f"选股结果合并: {len(all_stocks)} -> {len(final_result)} 只股票")
        return final_result

    def _determine_overall_risk_level(self, strategy_risks: List[Dict[str, Any]]) -> str:
        """
        确定总体风险等级

        Args:
            strategy_risks: 各策略风险结果

        Returns:
            str: 总体风险等级
        """
        if not strategy_risks:
            return 'LOW'

        risk_levels = [s.get('risk_level', 'LOW') for s in strategy_risks]
        error_count = sum(1 for r in risk_levels if r == 'ERROR')

        # 如果有策略出错，视为高风险
        if error_count > 0:
            return 'HIGH'

        # 风险等级优先级: CRITICAL > HIGH > MEDIUM > LOW
        if any(r == 'CRITICAL' for r in risk_levels):
            return 'CRITICAL'
        elif any(r == 'HIGH' for r in risk_levels):
            return 'HIGH'
        elif any(r == 'MEDIUM' for r in risk_levels):
            return 'MEDIUM'
        else:
            return 'LOW'

    def _display_selection_results(self, selected_stocks: List[Dict[str, Any]]) -> None:
        """
        显示选股结果

        Args:
            selected_stocks: 选中的股票列表
        """
        if not selected_stocks:
            self.logger.info("📭 本次选股未选中任何股票")
            return

        self.logger.info("🎯 选股结果详情:")
        for i, stock in enumerate(selected_stocks, 1):
            symbol = stock.get('symbol', 'N/A')
            name = stock.get('name', '')
            score = stock.get('score', 0)
            reason = stock.get('reason', '')
            price = stock.get('current_price', 0)
            change = stock.get('change_rate', 0)

            self.logger.info(f"  {i}. {symbol} {name} - "
                             f"评分: {score:.1f} - "
                             f"价格: {price:.2f} ({change:+.2f}%) - "
                             f"{reason}")

    def _get_custom_stocks(self) -> List[str]:
        """
        获取用户自定义股票列表

        Returns:
            List[str]: 股票代码列表
        """
        try:
            print("\n📋 请输入股票代码 (港股代码，如: 00700,02318,00941)")
            print("多个股票用逗号或空格分隔")
            print("输入 'exit' 退出")

            stock_input = input("股票代码: ").strip()
            if not stock_input or stock_input.lower() == 'exit':
                return []

            stocks = []
            # 修复：避免名称隐藏，使用 code 而不是 symbol
            for code in stock_input.replace('，', ',').replace(' ', ',').split(','):
                code = code.strip()
                if code:
                    # 标准化股票代码格式
                    if not code.startswith('HK.'):
                        stocks.append(f"HK.{code}")
                    else:
                        stocks.append(code)

            self.logger.info(f"自定义股票池: {stocks}")
            return stocks

        except Exception as e:
            self.logger.error(f"获取自定义股票失败: {e}")
            return []

    def _execute_trading_decisions(self, selected_stocks: List[Dict[str, Any]]) -> None:
        """
        执行交易决策 - 全自动模式（整合PositionManagementService）

        根据选股结果自动执行买入操作：
        1. 使用PositionManagementService计算安全仓位
        2. 从配置读取最大持仓数量
        3. 确保持仓不超过限制
        4. 按优先级买入

        Args:
            selected_stocks: 选中的股票列表（已按评分排序）
        """
        try:
            if not selected_stocks:
                self.logger.info("没有选中的股票，跳过交易决策")
                print("\n  ❌ 没有选中的股票，跳过交易决策")
                print("\n" + "=" * 70)
                print("🚀 Jeter的全自动量化交易系统正在运行中".center(70))
                print("=" * 70)
                return

            # 从配置读取最大持仓数量（默认3只）- 提前读取，用于显示提示信息
            max_stocks = getattr(self.config.trading.position_config, 'max_stocks', 3) if hasattr(self.config.trading, 'position_config') else 3

            # 显示选股结果（显示前10只）
            print("\n" + "=" * 70)
            print("📊 选股结果（显示前10只）".center(70))
            print("=" * 70)
            
            # 确保显示前10只，即使selected_stocks少于10只
            display_count = min(len(selected_stocks), 10)
            for i, stock in enumerate(selected_stocks[:display_count], 1):
                symbol = stock.get('symbol', '')
                name = stock.get('name', '')
                score = stock.get('score', 0)
                price = stock.get('current_price', 0)
                change_rate = stock.get('change_rate', 0) * 100
                print(f"  {i:2d}. {symbol:12s} {name:20s}")
                print(f"      评分: {score:5.1f} | 价格: {price:7.2f} ({change_rate:+6.2f}%)")
            
            if len(selected_stocks) < 10:
                print(f"\n  💡 本次选股共选出 {len(selected_stocks)} 只股票（少于10只）")
            
            # 提示交易规则
            if len(selected_stocks) > 0:
                print(f"\n  💡 提示: 选股结果共 {len(selected_stocks)} 只，将根据持仓限制选择前 {max_stocks} 只进行交易")
            
            print("=" * 70)

            # 创建Portfolio对象
            portfolio = self._create_portfolio_from_broker()
            if not portfolio:
                self.logger.error("无法创建投资组合对象，跳过交易决策")
                print("❌ 无法创建投资组合对象，跳过交易决策")
                return

            # 获取当前持仓数量
            current_position_count = portfolio.position_count
            current_position_symbols = set(portfolio.positions.keys())
            available_slots = max_stocks - current_position_count

            if available_slots <= 0:
                print(f"\n  ⚠️ 当前持仓已满 ({current_position_count}/{max_stocks})，无法买入新股票")
                self.logger.info(f"持仓已满 ({current_position_count}/{max_stocks})，跳过买入")
                print("\n" + "=" * 70)
                print("🚀 Jeter的全自动量化交易系统正在运行中".center(70))
                print("=" * 70)
                return

            # 显示账户信息
            print(f"\n  💰 账户信息:")
            print(f"    总资产: {portfolio.total_assets:,.2f} HKD")
            print(f"    可用资金: {portfolio.available_cash:,.2f} HKD")
            print(f"    当前持仓: {current_position_count} 只")
            print(f"    可买入数量: {available_slots} 只")

            # 选择股票（排除已持仓的），但不超过可用仓位
            # 注意：选股结果显示10只，但交易时最多买入max_stocks只（默认3只）
            stocks_to_buy = []
            max_stocks_to_buy = available_slots  # 最多买入数量 = 可用仓位数量（不超过max_stocks）

            for stock in selected_stocks:
                symbol = stock.get('symbol', '')
                if symbol not in current_position_symbols:
                    stocks_to_buy.append(stock)
                    if len(stocks_to_buy) >= max_stocks_to_buy:
                        break

            if not stocks_to_buy:
                print("\n  ✅ 所有选中的股票都已持仓，无需买入")
                self.logger.info("所有选中的股票都已持仓，无需买入")
                print("\n" + "=" * 70)
                print("🚀 Jeter的全自动量化交易系统正在运行中".center(70))
                print("=" * 70)
                return

            # 执行买入操作
            print(f"\n  🛒 准备买入 {len(stocks_to_buy)} 只股票:")
            print("  " + "-" * 66)
            
            successful_trades = 0
            failed_trades = 0
            
            for i, stock in enumerate(stocks_to_buy, 1):
                symbol = stock.get('symbol', '')
                name = stock.get('name', '')
                score = stock.get('score', 0)
                current_price = stock.get('current_price', 0)
                
                if current_price <= 0:
                    self.logger.warning(f"股票 {symbol} 价格无效，跳过")
                    continue

                # 使用PositionManagementService计算安全仓位
                try:
                    # 检查是否已有持仓
                    is_initial = symbol not in portfolio.positions
                    
                    # 计算安全仓位
                    position_suggestion = self.portfolio_manager.calculate_safe_position_size(
                        symbol=symbol,
                        price=current_price,
                        portfolio=portfolio,
                        is_initial=is_initial
                    )
                    
                    if position_suggestion.suggested_quantity <= 0:
                        self.logger.warning(f"股票 {symbol} 仓位计算失败: {position_suggestion.reason}")
                        print(f"  {i}. {symbol} {name} - {position_suggestion.reason}")
                        failed_trades += 1
                        continue

                    quantity = position_suggestion.suggested_quantity
                    
                    # 验证订单
                    validation_result = self.portfolio_manager.validate_order(
                        symbol=symbol,
                        quantity=quantity,
                        price=current_price,
                        portfolio=portfolio
                    )
                    
                    # 如果验证失败但提供了建议数量（如整手数调整），使用建议数量
                    if not validation_result.get('valid', False):
                        suggested_qty = validation_result.get('suggested_quantity')
                        if suggested_qty and suggested_qty > 0:
                            self.logger.info(f"股票 {symbol} 数量调整为整手数: {quantity} -> {suggested_qty}")
                            quantity = suggested_qty
                            # 使用调整后的数量重新验证
                            validation_result = self.portfolio_manager.validate_order(
                                symbol=symbol,
                                quantity=quantity,
                                price=current_price,
                                portfolio=portfolio
                            )
                    
                    # 如果验证仍然失败，跳过该股票
                    if not validation_result.get('valid', False):
                        self.logger.warning(f"股票 {symbol} 订单验证失败: {validation_result.get('message', '未知错误')}")
                        print(f"  {i}. {symbol} {name} - 验证失败: {validation_result.get('message', '未知错误')}")
                        failed_trades += 1
                        continue
                    
                    # 最终检查：确保数量大于0且是整手数
                    if quantity <= 0:
                        self.logger.warning(f"股票 {symbol} 调整后数量无效: {quantity}")
                        print(f"  {i}. {symbol} {name} - 数量无效: {quantity}")
                        failed_trades += 1
                        continue

                    # 显示买入信息
                    print(f"    {i}. {symbol:12s} {name:20s}")
                    print(f"        评分: {score:5.1f} | 价格: {current_price:7.2f} | 数量: {quantity:6d} 股")
                    print(f"        预计金额: {current_price * quantity:,.2f} HKD")
                    print(f"        风险等级: {position_suggestion.risk_level.value}")
                    print(f"        建议理由: {position_suggestion.reason}")
                    
                    # 执行买入（使用市价单）
                    success = self.broker.place_order(
                        symbol=symbol,
                        quantity=quantity,
                        price=current_price,
                        side='BUY',
                        order_type='MARKET',
                        remark=f"全自动选股买入-评分{score:.1f}"
                    )
                    
                    if success:
                        print(f"        ✅ 买入订单提交成功")
                        self.logger.info(f"✅ 买入订单提交成功: {symbol} x {quantity} @ {current_price:.2f}")
                        successful_trades += 1
                        
                        # 更新Portfolio（模拟，实际应该从broker重新获取）
                        portfolio.add_position(symbol, quantity, current_price)
                        
                        # 更新可用资金（扣除买入金额）
                        trade_value = quantity * current_price
                        portfolio.available_cash = max(0, portfolio.available_cash - trade_value)
                        portfolio.cash = max(0, portfolio.cash - trade_value)
                        
                        self.logger.debug(f"更新Portfolio: 买入 {symbol} {quantity}股 @ {current_price:.2f}, "
                                        f"扣除 {trade_value:,.2f} HKD, 剩余可用资金: {portfolio.available_cash:,.2f} HKD")
                    else:
                        print(f"        ❌ 买入订单提交失败")
                        self.logger.error(f"❌ 买入订单提交失败: {symbol}")
                        failed_trades += 1
                        
                except Exception as e:
                    print(f"        ❌ 买入失败: {e}")
                    self.logger.error(f"买入 {symbol} 失败: {e}")
                    failed_trades += 1

            print("  " + "-" * 66)
            print(f"  ✅ 交易决策执行完成 - 成功: {successful_trades}, 失败: {failed_trades}")
            
            # 显示运行状态
            print("\n" + "=" * 70)
            print("🚀 Jeter的全自动量化交易系统正在运行中".center(70))
            print("=" * 70)

        except Exception as e:
            self.logger.error(f"交易决策执行失败: {e}")
            print(f"\n  ❌ 交易决策执行失败: {e}")
            print("\n" + "=" * 70)
            print("🚀 Jeter的全自动量化交易系统正在运行中".center(70))
            print("=" * 70)

    def _handle_error(self, context: str, error: Exception) -> None:
        """
        统一错误处理

        Args:
            context: 错误发生的上下文
            error: 异常对象
        """
        error_msg = f"{context} 执行异常: {error}"
        self.logger.error(error_msg)

        # 记录错误统计
        self._execution_stats['errors'].append({
            'time': datetime.now(),
            'context': context,
            'error': str(error),
            'type': 'runtime'
        })

        # 在监控模式下，报告错误
        if self.system_monitor:
            self.system_monitor.report_error(context, error)