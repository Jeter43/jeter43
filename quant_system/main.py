#/quant_system/main.py
"""
交易系统主程序模块 - Trading System Main Program Module

这是量化交易系统的核心入口点，负责：
1. 系统初始化和配置管理
2. 用户交互和模式选择
3. 服务依赖注入和生命周期管理
4. 异常处理和优雅关闭
5. 系统监控和状态报告

版本重大改进：
- 完整的异常处理链和错误恢复机制
- 严格的配置验证和预检查
- 优雅的生命周期管理
- 集成的健康检查和性能监控
- 增强的用户交互体验
- 完整的类型安全和文档

核心功能：
1. 多市场选择和管理
2. 多模式运行支持
3. 策略动态配置
4. 系统状态监控
5. 优雅关闭和资源清理

┌───────────────────────────────────────────┐
│              TradingSystem (主控中心)       │
│───────────────────────────────────────────│
│  负责系统初始化、模块调度、运行与关闭     │
└───────────────────────────────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ ConfigManager     │
        │ 系统配置加载器     │
        └──────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ MultiMarketBroker │
        │ 多市场交易接口管理 │
        └──────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ StrategyFactory   │
        │ 策略工厂 - 动态加载│
        │ 风控/选股/混合策略 │
        └──────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ SystemRunner      │
        │ 系统运行器 - 调度逻辑│
        │ 负责策略执行与信号分发│
        └──────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ SystemMonitor     │
        │ 性能监控/健康状态 │
        └──────────────────┘
                │
                ▼
        ┌──────────────────┐
        │ Logger (日志系统) │
        │ 结构化日志 + 轮转 │
        └──────────────────┘
"""

import sys
import os
import time
import signal
import logging
from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
from pathlib import Path
import threading
from enum import Enum
import yaml
from dataclasses import fields

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入项目内部模块
from quant_system.core.config import ConfigManager, SystemMode, MarketType, Environment
from quant_system.core.trading_config import (TradingConfig, RiskConfig, PositionConfig,
                                              BrokerConfig, BacktestConfig)
from quant_system.infrastructure.multi_market_broker import MultiMarketBroker
from quant_system.infrastructure.brokers.base import Broker
from quant_system.domain.strategies.strategy_factory import StrategyFactory
from quant_system.application.system_runner import SystemRunner
from quant_system.utils.logger import setup_logger, log_info, log_error, log_warning, log_debug
from quant_system.application.system_monitor import SystemMonitor
from quant_system.core.exceptions import (
    ConfigValidationError,
    BrokerConnectionError,
    SystemInitializationError
)
from quant_system.utils.monitoring import performance_monitor, Timer, get_performance_summary
from quant_system.domain.services.position_management import PositionManagementService


class SystemState(Enum):
    """系统状态枚举"""
    UNINITIALIZED = "uninitialized"  # 未初始化
    INITIALIZING = "initializing"  # 初始化中
    INITIALIZED = "initialized"  # 已初始化
    RUNNING = "running"  # 运行中
    STOPPING = "stopping"  # 停止中
    STOPPED = "stopped"  # 已停止
    ERROR = "error"  # 错误状态


class TradingSystem:
    """
    交易系统主类 - 优化版本

    负责整个量化交易系统的生命周期管理，包括初始化、运行、监控和关闭。
    这个类采用单例模式设计，确保系统中只有一个主程序实例。

    Attributes:
        config (ConfigManager): 配置管理器实例
        logger: 日志记录器实例
        multi_market_broker (MultiMarketBroker): 多市场Broker管理器
        strategy_factory (StrategyFactory): 策略工厂实例
        system_runner (SystemRunner): 系统运行器实例
        system_monitor (SystemMonitor): 系统监控器实例
        state (SystemState): 当前系统状态
        shutdown_hooks (List[Callable]): 关闭钩子函数列表
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式实现"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        """内部初始化方法"""
        self.config = None
        self.logger = None
        self.multi_market_broker = None
        self.strategy_factory = None
        self.system_runner = None
        self.system_monitor = None
        self.portfolio_manager = None  # 添加仓位管理器
        self.service_integrator = None  # 新增：服务集成器
        self.state = SystemState.UNINITIALIZED
        self.shutdown_hooks = []
        self._start_time = None
        self._shutdown_requested = False
        self.stock_pool_manager = None   #20251120新增
        # 注册信号处理器
        #self._register_signal_handlers()

    def _register_signal_handlers(self):
        """
        注册信号处理器

        捕获系统信号以实现优雅关闭，避免数据丢失或状态不一致。
        """

        def signal_handler(signum, frame):
            """信号处理函数"""
            signal_name = {
                signal.SIGINT: "SIGINT",
                signal.SIGTERM: "SIGTERM"
            }.get(signum, str(signum))

            log_info(f"接收到信号 {signal_name}，正在优雅关闭系统...")
            self._shutdown_requested = True


        # 注册常见的中断信号
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            print("✅ 信号处理器注册成功")
        except Exception as e:
            print(f"⚠️ 信号处理器注册失败: {e}")

    def _load_user_configuration(self) -> None:
        """
        加载用户自定义的 trading.yaml 配置，并合并到 ConfigManager 里。
        """
        config_path = Path(__file__).resolve().parent / "config" / "trading.yaml"
        if not config_path.exists():
            log_info("🔍 未发现 user trading.yaml，使用默认配置")
            return

        try:
            raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not isinstance(raw_data, dict):
                log_warning("🔍 trading.yaml 内容格式无效，需为 YAML 映射，已忽略")
                return

            trading_patch = dict(raw_data.get("trading", {}))
            leftover_extra: Dict[str, Dict[str, Any]] = {}

            section_map = {
                "risk_config": RiskConfig,
                "position_config": PositionConfig,
                "broker_config": BrokerConfig,
                "backtest_config": BacktestConfig
            }

            for section, section_cls in section_map.items():
                section_data = raw_data.get(section)
                if isinstance(section_data, dict):
                    filtered, leftover = self._filter_section_data(section_data, section_cls)
                    if filtered:
                        trading_patch.setdefault(section, {}).update(filtered)
                    if leftover:
                        leftover_extra.setdefault(section, {}).update(leftover)

            merged = self.config.trading.to_dict()
            merged.update(trading_patch)
            self.config.trading = TradingConfig.from_dict(merged)

            if leftover_extra:
                for section, extras in leftover_extra.items():
                    self.config.trading.extra.setdefault(section, {}).update(extras)

            for extra_section in ("monitoring", "advanced_trading"):
                if extra_section in raw_data and isinstance(raw_data[extra_section], dict):
                    self.config.trading.extra.setdefault(extra_section, {}).update(raw_data[extra_section])

            log_info(f"✅ 已加载用户配置: {config_path}")
        except Exception as e:
            log_warning(f"❌ 加载 trading.yaml 失败: {e}")

    @staticmethod
    def _filter_section_data(section_data: Dict[str, Any], section_cls: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        过滤出 dataclass 定义的字段，其余归为 extra。
        """
        field_names = {f.name for f in fields(section_cls)}
        filtered = {k: v for k, v in section_data.items() if k in field_names}
        leftover = {k: v for k, v in section_data.items() if k not in field_names}
        return filtered, leftover

    @performance_monitor("system_initialize")
    def initialize(self) -> bool:
        """初始化交易系统 - 增强版本，支持分级仓位"""
        try:
            self.state = SystemState.INITIALIZING
            self._start_time = datetime.now()

            log_info("🚀 开始初始化交易系统...")

            # 1-2. 初始化配置和日志系统
            self.config = ConfigManager()
            self._load_user_configuration()

            # 根据配置设置日志级别
            log_level_str = getattr(self.config.system, 'log_level', 'INFO').upper()

            # 如果是开发环境且未明确指定，默认使用DEBUG级别
            if self.config.environment == Environment.DEVELOPMENT and not hasattr(self.config.system, 'log_level'):
                log_level_str = 'DEBUG'

            # 设置日志器（通过level参数，可以是字符串）
            self.logger = setup_logger(level=log_level_str)
            log_info(f"✅ 系统配置和日志初始化完成 - 模式: {self.config.system.mode}, 日志级别: {log_level_str}")

            # 检查分级仓位配置
            scaling_enabled = self._check_scaling_config()
            log_info(f"📊 分级仓位功能: {'启用' if scaling_enabled else '禁用'}")

            # 3. 验证系统环境
            if not self._validate_environment():
                raise SystemInitializationError("系统环境验证失败")
            log_info("✅ 环境验证通过")

            # 4-5. 用户交互：选择市场和模式
            if not self._select_market():
                raise SystemInitializationError("市场选择失败或用户取消")
            if not self._select_work_mode():
                raise SystemInitializationError("工作模式选择失败或用户取消")
            log_info(
                f"✅ 市场和模式配置完成 - 市场: {self.config.current_market.value}, 模式: {self.config.system.mode.value}")

            # 注意：策略选择将在策略工厂初始化后执行（见下方）

            # 6-8. 初始化并连接Broker
            log_info("🔗 开始初始化多市场Broker...")
            try:
                self.multi_market_broker = MultiMarketBroker(self.config)
                log_info("🔗 开始连接Broker...")
                connection_result = self.multi_market_broker.connect()
                if not connection_result:
                    log_error("❌ Broker连接返回False")
                    raise BrokerConnectionError("多市场Broker连接失败")
                log_info("✅ Broker连接成功")
            except BrokerConnectionError:
                raise  # 重新抛出BrokerConnectionError
            except Exception as e:
                log_error(f"❌ Broker连接过程出错: {e}")
                import traceback
                error_traceback = traceback.format_exc()
                log_error(f"详细堆栈: {error_traceback}")
                print(f"❌ Broker连接过程出错: {e}")  # 同时输出到控制台
                print(f"详细堆栈: {error_traceback}")  # 同时输出到控制台
                raise BrokerConnectionError(f"多市场Broker连接失败: {e}") from e

            # 获取当前broker实例（在验证之前）
            log_info("🔍 获取当前Broker实例...")
            try:
                current_broker = self.multi_market_broker.get_current_broker()
                if not current_broker:
                    raise SystemInitializationError("无法获取当前Broker实例")
                log_info(f"✅ 已获取Broker实例: {type(current_broker).__name__}")
            except Exception as e:
                log_error(f"❌ 获取Broker实例失败: {e}")
                import traceback
                log_error(f"详细堆栈: {traceback.format_exc()}")
                print(f"\n❌ 无法获取Broker实例: {e}")
                raise

            # 验证连接（如果验证失败，只记录警告，不中断初始化）
            log_info("🔍 验证Broker连接...")
            try:
                if not self._verify_broker_connection():
                    log_warning("⚠️ Broker连接验证失败，但继续初始化（可能是交易上下文未连接）")
                    print("\n⚠️ 警告: Broker连接验证失败，请确保富途客户端已启动并登录")
                else:
                    log_info("✅ Broker连接验证通过")
            except Exception as e:
                log_warning(f"⚠️ Broker连接验证异常: {e}，但继续初始化")
                print(f"\n⚠️ 警告: Broker连接验证异常: {e}")

            log_info(f"✅ Broker连接成功 - 类型: {type(current_broker).__name__}")

            # 9. 初始化服务集成器（新增）
            if scaling_enabled:
                log_info("🔄 初始化分级仓位服务集成器...")
                try:
                    from quant_system.application.system_integrator import SystemServiceIntegrator
                    self.service_integrator = SystemServiceIntegrator(current_broker, self.config)
                    if self.service_integrator.initialize_services():
                        log_info("✅ 分级仓位服务集成器初始化成功")

                        # 获取服务状态
                        service_status = self.service_integrator.get_system_status()
                        log_info(f"🔍 分级仓位服务状态: {service_status}")
                    else:
                        log_error("❌ 分级仓位服务集成器初始化失败")
                        # 不中断初始化，继续使用基础功能
                except Exception as e:
                    log_error(f"❌ 分级仓位服务集成器初始化异常: {e}")
                    # 不中断初始化，继续使用基础功能
            else:
                log_info("ℹ️ 分级仓位功能未启用，跳过服务集成器初始化")

            # 10. 初始化股票池管理器和策略工厂
            log_info("📊 开始初始化股票池管理器...")
            try:
                from quant_system.domain.services.stock_pool_manager import StockPoolManager
                self.stock_pool_manager = StockPoolManager()
                log_info("✅ 股票池管理器创建成功")

                pools_info = self.stock_pool_manager.list_available_pools()
                total_stocks = sum(info['stock_count'] for info in pools_info.values())

                # 股票池信息改为DEBUG级别，减少日志噪音
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"📊 股票池信息: {len(pools_info)} 个股票池，共 {total_stocks} 只股票")
                    for pool_id, info in pools_info.items():
                        self.logger.debug(f"   🎯 {info['name']}: {info['stock_count']} 只股票")
            except Exception as e:
                error_msg = f"❌ 股票池管理器初始化失败: {e}"
                log_error(error_msg)
                import traceback
                error_traceback = traceback.format_exc()
                log_error(f"详细堆栈: {error_traceback}")
                print(error_msg)  # 同步输出
                print(f"详细堆栈: {error_traceback}")  # 同步输出
                raise

            log_info("🏭 开始初始化策略工厂...")
            try:
                self.strategy_factory = StrategyFactory(
                    broker=current_broker,
                    config=self.config,
                    stock_pool_manager=self.stock_pool_manager
                )
                log_info("✅ 策略工厂初始化成功")

                # 策略工厂初始化后，执行策略选择
                log_info("🎛️ 开始配置策略选择...")
                self._select_strategies_for_mode(self.config.system.mode)
            except Exception as e:
                error_msg = f"❌ 策略工厂初始化失败: {e}"
                log_error(error_msg)
                import traceback
                error_traceback = traceback.format_exc()
                log_error(f"详细堆栈: {error_traceback}")
                print(error_msg)  # 同步输出
                print(f"详细堆栈: {error_traceback}")  # 同步输出
                raise

            # 11-13. 初始化服务和运行器
            log_info("💰 开始初始化仓位管理服务...")
            try:
                # 如果服务集成器已初始化，使用它提供的仓位管理服务
                if self.service_integrator and self.service_integrator.position_manager:
                    self.portfolio_manager = self.service_integrator.position_manager
                    log_info("✅ 使用分级仓位服务集成器提供的仓位管理服务")
                else:
                    # 回退到基础仓位管理服务
                    from quant_system.domain.services.position_management import PositionManagementService
                    self.portfolio_manager = PositionManagementService(current_broker, self.config)
                    log_info("✅ 基础仓位管理服务初始化成功")
            except Exception as e:
                error_msg = f"❌ 仓位管理服务初始化失败: {e}"
                log_error(error_msg)
                import traceback
                error_traceback = traceback.format_exc()
                log_error(f"详细堆栈: {error_traceback}")
                print(error_msg)  # 同步输出
                print(f"详细堆栈: {error_traceback}")  # 同步输出
                raise

            log_info("📊 开始初始化系统监控...")
            try:
                self.system_monitor = SystemMonitor(self.config)
                log_info("✅ 系统监控初始化成功")
            except Exception as e:
                error_msg = f"❌ 系统监控初始化失败: {e}"
                log_error(error_msg)
                import traceback
                error_traceback = traceback.format_exc()
                log_error(f"详细堆栈: {error_traceback}")
                print(error_msg)  # 同步输出
                print(f"详细堆栈: {error_traceback}")  # 同步输出
                raise

            log_info("⚙️ 开始初始化系统运行器...")
            try:
                # 传递服务集成器给系统运行器
                self.system_runner = SystemRunner(
                    config=self.config,
                    strategy_factory=self.strategy_factory,
                    broker=current_broker,
                    portfolio_manager=self.portfolio_manager,
                    system_monitor=self.system_monitor,
                    service_integrator=self.service_integrator  # 新增参数
                )
                log_info("✅ 系统运行器初始化成功")
            except Exception as e:
                error_msg = f"❌ 系统运行器初始化失败: {e}"
                log_error(error_msg)
                import traceback
                error_traceback = traceback.format_exc()
                log_error(f"详细堆栈: {error_traceback}")
                print(error_msg)  # 同步输出
                print(f"详细堆栈: {error_traceback}")  # 同步输出
                raise

            log_info("✅ 核心服务初始化完成（仓位管理、系统监控、系统运行器）")

            # 14-15. 配置策略和注册关闭钩子
            log_info("🎛️ 开始配置策略和注册关闭钩子...")
            try:
                self._register_shutdown_hooks()
                log_info("✅ 策略配置和关闭钩子注册完成")
            except Exception as e:
                log_error(f"❌ 策略配置和关闭钩子注册失败: {e}")
                import traceback
                log_error(f"详细堆栈: {traceback.format_exc()}")
                raise

            self.state = SystemState.INITIALIZED
            initialization_time = (datetime.now() - self._start_time).total_seconds()

            log_info(f"✅ 系统初始化完成，耗时: {initialization_time:.2f}秒")
            # 强制刷新日志，确保日志被写入
            if hasattr(self.logger, 'flush'):
                self.logger.flush()
            return True

        except Exception as e:
            self.state = SystemState.ERROR
            log_error(f"❌ 系统初始化失败: {e}")
            import traceback
            log_error(f"详细堆栈: {traceback.format_exc()}")

            # 清理已初始化的资源
            self._cleanup_resources()
            raise SystemInitializationError(f"系统初始化失败: {e}") from e

    def _check_scaling_config(self) -> bool:
        """
        检查分级仓位配置

        Returns:
            bool: 是否启用分级仓位
        """
        try:
            # 从配置中检查
            if hasattr(self.config, 'trading') and hasattr(self.config.trading, 'position_scaling_enabled'):
                return self.config.trading.position_scaling_enabled

            # 检查系统配置
            if hasattr(self.config, 'system'):
                system_config = getattr(self.config, 'system', {})
                if isinstance(system_config, dict):
                    trading_config = system_config.get('trading', {})
                    return trading_config.get('enable_position_scaling', False)

                # 如果是对象形式
                if hasattr(system_config, 'trading'):
                    trading_config = getattr(system_config, 'trading', {})
                    if hasattr(trading_config, 'enable_position_scaling'):
                        return trading_config.enable_position_scaling

            # 检查position_scaling配置
            if hasattr(self.config, 'position_scaling'):
                scaling_config = getattr(self.config, 'position_scaling', {})
                if isinstance(scaling_config, dict):
                    return scaling_config.get('enabled', False)
                elif hasattr(scaling_config, 'enabled'):
                    return scaling_config.enabled

            return False

        except Exception as e:
            log_warning(f"检查分级仓位配置失败: {e}")
            return False

    def _verify_broker_connection(self) -> bool:
        """
        验证Broker连接是否仍然有效
        
        注意：此方法用于验证连接，但不会阻止初始化。
        即使验证失败（如交易上下文未连接），只要行情连接正常，初始化仍可继续。

        Returns:
            bool: 连接是否有效
        """
        try:
            if not self.multi_market_broker:
                self.logger.error("❌ MultiMarketBroker未初始化")
                return False

            # 获取当前broker实例
            current_broker = self.multi_market_broker.get_current_broker()
            if not current_broker:
                self.logger.error("❌ 无法获取当前Broker实例")
                return False

            # 检查连接状态
            if hasattr(current_broker, 'is_connected'):
                # 如果有is_connected方法，使用它
                try:
                    is_connected = current_broker.is_connected()
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"🔍 Broker连接状态: {'已连接' if is_connected else '已断开'}")
                    return is_connected
                except Exception as e:
                    self.logger.warning(f"⚠️ 检查Broker连接状态时出错: {e}，但继续初始化")
                    # 即使检查失败，也返回True，因为可能是交易上下文未连接但行情连接正常
                    return True
            else:
                # 如果没有is_connected方法，尝试获取账户信息来测试连接
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug("🔍 通过账户信息查询测试Broker连接...")
                try:
                    account_info = current_broker.get_account_info()
                    if account_info and len(account_info) > 0:
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug("✅ Broker连接验证成功")
                        return True
                    else:
                        # 账户信息为空可能是正常的（模拟环境或交易上下文未连接）
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug("⚠️ Broker连接测试返回空账户信息（可能是模拟环境）")
                        return True  # 返回True，允许继续初始化
                except Exception as e:
                    self.logger.warning(f"⚠️ Broker连接测试失败: {e}，但继续初始化（可能是交易上下文未连接）")
                    # 即使测试失败，也返回True，因为可能是交易上下文未连接但行情连接正常
                    return True

        except Exception as e:
            self.logger.warning(f"⚠️ 验证Broker连接时发生异常: {e}，但继续初始化")
            # 即使验证失败，也返回True，允许继续初始化
            return True

    def _validate_environment(self) -> bool:
        """
        验证系统运行环境 - 完整版本
        """
        log_info("🔍 开始全面的环境验证...")

        validation_passed = True
        validation_issues = []

        try:
            # 1. 检查必要的目录
            log_info("📁 检查目录结构...")
            required_dirs = ['logs', 'data', 'config']
            for dir_name in required_dirs:
                dir_path = Path(dir_name)
                if not dir_path.exists():
                    dir_path.mkdir(parents=True, exist_ok=True)
                    log_info(f"   ✅ 创建目录: {dir_path}")
                else:
                    log_info(f"   ✅ 目录存在: {dir_path}")

            # 2. 检查配置文件
            log_info("📋 检查配置文件...")
            config_files = {
                'config/system.yaml': '系统基础配置',
                'config/market.yaml': '市场配置',
                'config/trading.yaml': '交易与风控参数',
                'config/stocks.yaml': '股票池定义'
            }

            for config_file, description in config_files.items():
                config_path = Path(config_file)
                if not config_path.exists():
                    warning_msg = f"配置文件不存在: {config_file} ({description})"
                    log_warning(f"   ⚠️ {warning_msg}")
                    validation_issues.append(warning_msg)

                    # 在开发环境中，创建示例配置文件
                    if hasattr(self, 'config') and getattr(self.config, 'environment',
                                                           None) and self.config.environment.value == 'development':
                        log_info(f"   🛠️ 开发环境: 将创建示例配置文件 {config_file}")
                        self._create_sample_config_file(config_file)
                else:
                    log_info(f"   ✅ 配置文件存在: {config_file}")

            # 3. 检查Python依赖
            log_info("🐍 检查Python依赖...")
            # 注意：pyyaml包导入时使用yaml模块名
            required_packages = [
                ('pandas', '数据分析', 'pandas'),
                ('numpy', '数值计算', 'numpy'),
                ('pytz', '时区处理', 'pytz'),
                ('pyyaml', 'YAML解析', 'yaml')  # pyyaml包导入时使用yaml模块名
            ]

            optional_packages = [
                ('futu-api', '富途接口', 'futu', False)
            ]

            missing_required = []
            missing_optional = []

            for package, description, import_name in required_packages:
                try:
                    __import__(import_name)
                    log_info(f"   ✅ {description}: {package}")
                except ImportError:
                    missing_required.append(f"{package} ({description})")
                    log_error(f"   ❌ 缺少必要依赖: {package} - {description}")

            for package_info in optional_packages:
                if len(package_info) == 3:
                    package, description, import_name = package_info
                    critical = False
                else:
                    package, description, import_name, critical = package_info
                
                try:
                    __import__(import_name)
                    log_info(f"   ✅ {description}: {package}")
                except ImportError:
                    missing_optional.append(f"{package} ({description})")
                    log_warning(f"   ⚠️ 缺少可选依赖: {package} - {description}")

            # 4. 检查数据目录权限
            log_info("🔐 检查目录权限...")
            try:
                test_dirs = ['logs', 'data']
                for test_dir in test_dirs:
                    test_path = Path(test_dir) / '.permission_test'
                    try:
                        test_path.touch()
                        test_path.unlink()
                        log_info(f"   ✅ 目录可写: {test_dir}")
                    except Exception as e:
                        error_msg = f"目录不可写: {test_dir} - {e}"
                        log_error(f"   ❌ {error_msg}")
                        validation_issues.append(error_msg)
            except Exception as e:
                log_warning(f"   ⚠️ 权限检查异常: {e}")

            # 5. 汇总验证结果
            if missing_required:
                error_msg = f"缺少必要依赖包: {', '.join(missing_required)}"
                log_error(f"❌ {error_msg}")
                validation_issues.append(error_msg)
                validation_passed = False

            if validation_issues and hasattr(self, 'config') and getattr(self.config, 'environment',
                                                                         None) and self.config.environment.value == 'development':
                log_warning("⚠️ 开发环境: 忽略部分验证问题，继续初始化")
                validation_passed = True

            if validation_passed:
                log_info("✅ 环境验证通过")
            else:
                log_error("❌ 环境验证失败")
                log_info("💡 修复建议:")
                for issue in validation_issues:
                    log_info(f"   - {issue}")

                # 提供具体的修复命令
                if missing_required:
                    log_info("📦 安装缺失的依赖:")
                    # 提取包名（去掉括号中的描述）
                    package_names = []
                    for pkg in missing_required:
                        # 格式: "package (description)" -> "package"
                        pkg_name = pkg.split(' (')[0] if ' (' in pkg else pkg
                        package_names.append(pkg_name)
                    log_info(f"   pip install {' '.join(package_names)}")
                    log_info("   或者使用: pip install -r requirements.txt")

            return validation_passed

        except Exception as e:
            log_error(f"❌ 环境验证过程异常: {e}")
            # 在开发环境中，即使有异常也继续
            if hasattr(self, 'config') and getattr(self.config, 'environment',
                                                   None) and self.config.environment.value == 'development':
                log_warning("⚠️ 开发环境: 忽略环境验证异常，继续初始化")
                return True
            return False

    def _create_sample_config_file(self, config_file: str):
        """创建示例配置文件"""
        try:
            config_path = Path(config_file)

            if config_file == 'config/system.yaml':
                sample_content = """# 系统基础配置示例
    system:
      mode: "full_automation"
      environment: "development"
      selection_interval_minutes: 120
      risk_check_interval_seconds: 60
    """
                config_path.write_text(sample_content, encoding='utf-8')
                log_info(f"   ✅ 已创建示例配置文件: {config_file}")

            elif config_file == 'config/market.yaml':
                sample_content = """# 市场配置示例
    default_market: "hk"
    markets:
      hk:
        market_type: "hk"
        broker_type: "futu"
        enabled: true
        currency: "HKD"
    """
                config_path.write_text(sample_content, encoding='utf-8')
                log_info(f"   ✅ 已创建示例配置文件: {config_file}")

        except Exception as e:
            log_error(f"   创建示例配置文件失败 {config_file}: {e}")

    def _select_market(self) -> bool:
        """
        交互式选择交易市场

        提供用户友好的市场选择界面，支持多市场配置。

        Returns:
            bool: 市场选择是否成功
        """
        try:
            print("\n" + "=" * 60)
            print("🌍 交易市场选择")
            print("=" * 60)

            available_markets = self.config.list_available_markets()

            if not available_markets:
                log_error("❌ 没有可用的市场配置")
                return False

            # 显示可用市场选项
            market_options = {}
            print("请选择交易市场:")
            print("-" * 40)

            for i, market_info in enumerate(available_markets, 1):
                market_type = market_info['market_type']
                broker_type = market_info['broker_type']
                currency = market_info['currency']
                is_current = market_info['is_current']

                current_indicator = " [当前]" if is_current else ""
                print(
                    f"{i}. {market_type.value.upper():<6} - {broker_type.value:<10} - {currency:<8}{current_indicator}")
                market_options[str(i)] = market_type

            print("-" * 40)

            while True:
                try:
                    max_choice = len(available_markets)
                    choice = input(f"\n请输入选择 (1-{max_choice}): ").strip()

                    if choice in market_options:
                        selected_market = market_options[choice]
                        if self.config.switch_market(selected_market):
                            log_info(f"🎯 已选择 {selected_market.value.upper()} 市场")
                            return True
                        else:
                            log_error("❌ 市场切换失败，请重新选择")

                    else:
                        log_warning("❌ 输入无效，请重新选择")

                except KeyboardInterrupt:
                    log_info("🛑 用户取消市场选择")
                    return False
                except Exception as e:
                    log_error(f"❌ 市场选择异常: {e}")

        except Exception as e:
            log_error(f"❌ 市场选择过程异常: {e}")
            return False

    def _enable_all_markets(self, available_markets: List[Dict]) -> bool:
        """
        启用所有可用市场

        Args:
            available_markets: 可用市场列表

        Returns:
            bool: 操作是否成功
        """
        try:
            enabled_count = 0
            for market_info in available_markets:
                market_type = market_info['market_type']
                if self.config.enable_market(market_type):
                    enabled_count += 1
                    log_info(f"  ✅ 启用 {market_type.value.upper()} 市场")

            log_info(f"🌐 已启用 {enabled_count}/{len(available_markets)} 个市场")
            return enabled_count > 0

        except Exception as e:
            log_error(f"❌ 启用所有市场失败: {e}")
            return False

    def _manual_market_selection(self) -> bool:
        """
        手动输入市场代码

        Returns:
            bool: 手动选择是否成功
        """
        try:
            print("\n📝 手动输入市场模式")
            print("支持的市场类型: HK, US, CN, FUTURES, CRYPTO")
            print("输入格式: 市场类型 (如: HK, US)")

            market_input = input("请输入市场类型: ").strip().upper()

            try:
                market_type = MarketType(market_input)
                if self.config.switch_market(market_type):
                    log_info(f"🎯 手动选择 {market_type.value.upper()} 市场")
                    return True
                else:
                    log_error("❌ 市场切换失败")
                    return False

            except ValueError:
                log_error(f"❌ 无效的市场类型: {market_input}")
                return False

        except KeyboardInterrupt:
            log_info("🛑 用户取消手动输入")
            return False
        except Exception as e:
            log_error(f"❌ 手动市场选择异常: {e}")
            return False

    def _select_work_mode(self) -> bool:
        """
        交互式选择工作模式

        Returns:
            bool: 模式选择是否成功
        """
        try:
            print("\n" + "=" * 60)
            print("🎯 工作模式选择")
            print("=" * 60)
            print("请选择系统工作模式:")
            print("-" * 40)
            print("1. 📈 只选股模式 - 仅执行股票筛选，不进行交易")
            print("2. 🛡️ 只风控模式 - 仅监控和管理风险，不主动交易")
            print("3. 🤖 全自动模式 - 完整的自动化交易流程")
            print("4. 📊 回测模式 - 使用历史数据进行策略验证")
            print("5. 🔧 调试模式 - 开发调试专用")
            print("-" * 40)

            mode_map = {
                '1': SystemMode.STOCK_SELECTION_ONLY,
                '2': SystemMode.RISK_MANAGEMENT_ONLY,
                '3': SystemMode.FULL_AUTOMATION,
                '4': SystemMode.BACKTEST,
                '5': SystemMode.DEBUG
            }

            while True:
                try:
                    choice = input("\n请输入选择 (1-5): ").strip()

                    if choice in mode_map:
                        selected_mode = mode_map[choice]
                        self.config.update_mode(selected_mode)

                        # 注意：策略选择将在策略工厂初始化后执行
                        # 这里只记录模式选择，策略选择延迟到策略工厂初始化后
                        log_info("📝 模式已选择，策略选择将在初始化后执行")

                        mode_descriptions = {
                            SystemMode.STOCK_SELECTION_ONLY: "选股模式",
                            SystemMode.RISK_MANAGEMENT_ONLY: "风控模式",
                            SystemMode.FULL_AUTOMATION: "全自动模式",
                            SystemMode.BACKTEST: "回测模式",
                            SystemMode.DEBUG: "调试模式"
                        }

                        log_info(f"🎯 已选择 {mode_descriptions[selected_mode]}")
                        return True
                    else:
                        log_warning("❌ 输入无效，请重新选择")

                except KeyboardInterrupt:
                    log_info("🛑 用户取消模式选择")
                    return False
                except Exception as e:
                    log_error(f"❌ 模式选择异常: {e}")

        except Exception as e:
            log_error(f"❌ 工作模式选择过程异常: {e}")
            return False

    def _select_strategies_for_mode(self, mode: SystemMode):
        """根据工作模式选择具体策略"""
        log_info("🎛️ 配置策略选择...")

        if mode == SystemMode.STOCK_SELECTION_ONLY:
            self._select_selection_strategies()
        elif mode == SystemMode.RISK_MANAGEMENT_ONLY:
            self._select_risk_strategies()
        elif mode == SystemMode.FULL_AUTOMATION:
            self._select_full_automation_strategies()
        elif mode == SystemMode.BACKTEST:
            self._select_backtest_strategies()
        elif mode == SystemMode.DEBUG:
            self._select_debug_strategies()

    def _select_selection_strategies(self):
        """选择选股策略 - 动态获取所有可用策略"""
        print("\n" + "=" * 60)
        print("📈 选股策略选择")
        print("=" * 60)
        
        # 从策略工厂动态获取所有选股策略
        if not self.strategy_factory:
            log_error("策略工厂未初始化，无法获取策略列表")
            return False
        
        strategies_info = self.strategy_factory.list_available_strategies()
        selection_strategies = strategies_info.get('selection', [])
        
        if not selection_strategies:
            log_warning("⚠️ 没有可用的选股策略")
            return False
        
        print("请选择要使用的选股策略:")
        print("-" * 40)
        
        # 动态显示所有可用策略
        strategy_map = {}
        strategy_icons = {
            'technical_analysis': '🔧',
            'realtime_monitoring': '⚡',
            'priority_stocks': '⭐',
            'mixed_strategy': '🎯',
        }
        
        for idx, strategy_info in enumerate(selection_strategies, 1):
            strategy_name = strategy_info['name']
            strategy_desc = strategy_info['description']
            icon = strategy_icons.get(strategy_name, '📊')
            print(f"{idx}. {icon} {strategy_desc}")
            strategy_map[str(idx)] = strategy_name
        
        print("-" * 40)

        while True:
            try:
                max_choice = len(selection_strategies)
                choice = input(f"\n请输入选择 (1-{max_choice}): ").strip()

                if choice in strategy_map:
                    selected = strategy_map[choice]
                    # 启用单个策略
                    self._enable_single_selection_strategy(selected)
                    log_info(f"✅ 已启用选股策略: {selected}")
                    return True
                else:
                    log_warning(f"❌ 输入无效，请输入 1-{max_choice} 之间的数字")

            except KeyboardInterrupt:
                log_info("🛑 用户取消策略选择")
                return False
            except Exception as e:
                log_error(f"❌ 策略选择异常: {e}")
                return False

    def _select_risk_strategies(self):
        """选择风控策略"""
        print("\n" + "=" * 60)
        print("🛡️ 风控策略选择")
        print("=" * 60)
        print("请选择要使用的风控策略:")
        print("-" * 40)
        print("1. 🛑 基础止损策略 - 简单止损规则")
        print("2. 🚨 高级风控策略 - 综合风险管理")
        print("-" * 40)

        strategy_map = {
            '1': "basic_stop_loss",
            '2': "advanced_risk_management"
        }

        while True:
            try:
                choice = input("\n请输入选择 (1-2): ").strip()

                if choice in strategy_map:
                    selected = strategy_map[choice]
                    self._enable_single_risk_strategy(selected)
                    log_info(f"✅ 已启用风控策略: {selected}")
                    break
                else:
                    log_warning("❌ 输入无效，请重新选择")

            except KeyboardInterrupt:
                log_info("🛑 用户取消策略选择")
                break
            except Exception as e:
                log_error(f"❌ 策略选择异常: {e}")

    def _select_full_automation_strategies(self):
        """全自动模式策略选择 - 直接进行策略配置"""
        # 直接进入交互式策略选择流程，省略中间步骤
        self._interactive_select_strategies_for_full_automation()

    def _select_backtest_strategies(self):
        """回测模式策略选择"""
        print("\n" + "=" * 60)
        print("📊 回测模式策略配置")
        print("=" * 60)
        print("回测模式将启用所有策略进行历史数据测试")
        self._enable_all_selection_strategies()
        self._enable_all_risk_strategies()
        log_info("✅ 回测模式：已启用所有策略")

    def _select_debug_strategies(self):
        """调试模式策略选择"""
        print("\n" + "=" * 60)
        print("🔧 调试模式策略配置")
        print("=" * 60)
        print("调试模式仅启用基础策略用于开发测试")
        self._enable_basic_strategies_only()
        log_info("✅ 调试模式：仅启用基础策略")

    def _enable_all_selection_strategies(self):
        """启用所有选股策略"""
        selection_config = self.config.system.selection_strategies_config
        for strategy_name in selection_config:
            selection_config[strategy_name].enabled = True
        log_info("📈 已启用所有选股策略")

    def _enable_all_risk_strategies(self):
        """启用所有风控策略"""
        risk_config = self.config.system.risk_strategies_config
        for strategy_name in risk_config:
            risk_config[strategy_name].enabled = True
        log_info("🛡️ 已启用所有风控策略")

    def _enable_single_selection_strategy(self, strategy_name: str):
        """启用单个选股策略"""
        selection_config = self.config.system.selection_strategies_config

        # 禁用所有选股策略
        for name in selection_config:
            selection_config[name].enabled = False

        # 启用指定策略（如果策略不存在，自动创建配置）
        if strategy_name in selection_config:
            selection_config[strategy_name].enabled = True
            log_info(f"✅ 已启用选股策略: {strategy_name}")
        else:
            # 如果策略在工厂中注册但配置中不存在，自动创建配置
            from quant_system.core.config import SelectionStrategyConfig
            # 根据策略类型设置不同的默认值
            if strategy_name == 'realtime_monitoring':
                max_stocks = 10
                min_score = 50.0
            elif strategy_name == 'technical_analysis':
                max_stocks = 10
                min_score = 60.0
            else:
                max_stocks = 50
                min_score = 50.0
            
            selection_config[strategy_name] = SelectionStrategyConfig(
                enabled=True,
                weight=1.0,
                max_stocks=max_stocks,
                min_score=min_score
            )
            log_info(f"✅ 自动为策略 {strategy_name} 创建配置并启用 (max_stocks={max_stocks}, min_score={min_score})")
        
        # 验证配置是否正确更新
        enabled_strategies = self.config.system.get_enabled_selection_strategies()
        if self.logger.isEnabledFor(logging.DEBUG):
            log_debug(f"🔍 验证：当前启用的选股策略: {enabled_strategies}")
        if strategy_name not in enabled_strategies:
            log_warning(f"⚠️ 警告：策略 {strategy_name} 启用后未在配置中找到，可能存在问题")

    def _enable_single_risk_strategy(self, strategy_name: str):
        """启用单个风控策略"""
        risk_config = self.config.system.risk_strategies_config

        # 禁用所有风控策略
        for name in risk_config:
            risk_config[name].enabled = False

        # 启用指定策略
        if strategy_name in risk_config:
            risk_config[strategy_name].enabled = True

    def _enable_basic_strategies_only(self):
        """仅启用基础策略"""
        # 启用基础选股策略
        selection_config = self.config.system.selection_strategies_config
        for name in selection_config:
            selection_config[name].enabled = (name == "technical_analysis")

        # 禁用所有风控策略
        risk_config = self.config.system.risk_strategies_config
        for name in risk_config:
            risk_config[name].enabled = False

        log_info("🔧 已启用基础策略配置")

    def _get_available_selection_strategies(self) -> Dict[str, tuple]:
        """从策略工厂动态获取所有可用选股策略"""
        if not self.strategy_factory:
            # 回退到硬编码列表
            return {
                '1': ("technical_analysis", "技术分析策略"),
                '2': ("realtime_monitoring", "实时数据选股策略"),
                '3': ("priority_stocks", "自选股策略"),
                '4': ("mixed_strategy", "混合策略")
            }
        
        strategies_info = self.strategy_factory.list_available_strategies()
        selection_strategies = strategies_info.get('selection', [])
        
        available_strategies = {}
        for idx, strategy_info in enumerate(selection_strategies, 1):
            strategy_name = strategy_info.get('name', '')
            strategy_desc = strategy_info.get('description', strategy_name)
            available_strategies[str(idx)] = (strategy_name, strategy_desc)
        
        return available_strategies
    
    def _get_available_risk_strategies(self) -> Dict[str, tuple]:
        """从策略工厂动态获取所有可用风控策略"""
        if not self.strategy_factory:
            # 回退到硬编码列表
            return {
                '1': ("basic_stop_loss", "基础止损策略"),
                '2': ("advanced_risk_management", "高级风控策略")
            }
        
        strategies_info = self.strategy_factory.list_available_strategies()
        risk_strategies = strategies_info.get('risk_management', [])
        
        available_strategies = {}
        for idx, strategy_info in enumerate(risk_strategies, 1):
            strategy_name = strategy_info.get('name', '')
            strategy_desc = strategy_info.get('description', strategy_name)
            available_strategies[str(idx)] = (strategy_name, strategy_desc)
        
        return available_strategies
    
    def _custom_select_selection_strategies(self):
        """自定义选择选股策略（保留用于兼容性）"""
        available_strategies = self._get_available_selection_strategies()

        print("\n🛠️ 自定义选股策略选择:")
        print("-" * 40)
        for key, (name, desc) in available_strategies.items():
            print(f"{key}. {desc}")
        print("5. ✅ 完成选择")
        print("-" * 40)

        selected_strategies = []

        while True:
            try:
                choice = input("请选择策略 (输入数字，多选用逗号分隔，5完成): ").strip()

                if choice == '5':
                    break

                choices = [c.strip() for c in choice.split(',')]
                valid_choices = []

                for c in choices:
                    if c in available_strategies:
                        strategy_name, strategy_desc = available_strategies[c]
                        if strategy_name not in selected_strategies:
                            selected_strategies.append(strategy_name)
                            valid_choices.append(strategy_desc)

                if valid_choices:
                    log_info(f"✅ 已选择: {', '.join(valid_choices)}")
                else:
                    log_warning("❌ 没有有效的选择")

            except Exception as e:
                log_error(f"❌ 选择异常: {e}")

        # 应用选择
        if selected_strategies:
            selection_config = self.config.system.selection_strategies_config
            # 先禁用所有
            for name in selection_config:
                selection_config[name].enabled = False
            # 启用选择的
            for strategy_name in selected_strategies:
                if strategy_name in selection_config:
                    selection_config[strategy_name].enabled = True
                else:
                    # 自动创建配置
                    from quant_system.core.config import SelectionStrategyConfig
                    selection_config[strategy_name] = SelectionStrategyConfig(
                        enabled=True,
                        weight=1.0,
                        max_stocks=50,
                        min_score=50.0
                    )
            log_info(f"✅ 已启用选股策略: {selected_strategies}")

    def _custom_select_risk_strategies(self):
        """自定义选择风控策略"""
        available_strategies = {
            '1': ("basic_stop_loss", "基础止损策略"),
            '2': ("advanced_risk_management", "高级风控策略")
        }

        print("\n🛠️ 自定义风控策略选择:")
        print("-" * 40)
        for key, (name, desc) in available_strategies.items():
            print(f"{key}. {desc}")
        print("3. ✅ 完成选择")
        print("-" * 40)

        selected_strategies = []

        while True:
            try:
                choice = input("请选择策略 (输入数字，多选用逗号分隔，3完成): ").strip()

                if choice == '3':
                    break

                choices = [c.strip() for c in choice.split(',')]
                valid_choices = []

                for c in choices:
                    if c in available_strategies:
                        strategy_name, strategy_desc = available_strategies[c]
                        if strategy_name not in selected_strategies:
                            selected_strategies.append(strategy_name)
                            valid_choices.append(strategy_desc)

                if valid_choices:
                    log_info(f"✅ 已选择: {', '.join(valid_choices)}")
                else:
                    log_warning("❌ 没有有效的选择")

            except Exception as e:
                log_error(f"❌ 选择异常: {e}")

        # 应用选择
        if selected_strategies:
            risk_config = self.config.system.risk_strategies_config
            # 先禁用所有
            for name in risk_config:
                risk_config[name].enabled = False
            # 启用选择的
            for strategy_name in selected_strategies:
                if strategy_name in risk_config:
                    risk_config[strategy_name].enabled = True
            log_info(f"✅ 已启用风控策略: {selected_strategies}")

    def _interactive_select_strategies_for_full_automation(self):
        """全自动模式交互式策略选择 - 直接进行选股和风控策略选择"""
        selected_selection_strategies = []
        selected_risk_strategies = []
        
        print("\n" + "=" * 60)
        print("🛠️ 全自动模式策略配置")
        print("=" * 60)
        
        # 第一步：选择选股策略
        print("\n" + "=" * 70)
        print("📈 第一步：选择选股策略".center(70))
        print("=" * 70)
        selected_selection_strategies = self._interactive_select_selection_strategies()
        
        # 第二步：选择风控策略
        print("\n" + "=" * 70)
        print("🛡️ 第二步：选择风控策略".center(70))
        print("=" * 70)
        selected_risk_strategies = self._interactive_select_risk_strategies()
        
        # 显示选择结果并确认
        print("\n" + "=" * 60)
        # 策略名称映射（用于显示友好名称）
        strategy_name_map = {
            'technical_analysis': '技术分析选股策略',
            'realtime_monitoring': '实时数据选股策略',
            'priority_stocks': '自选股策略',
            'mixed_strategy': '混合选股策略',
            'basic_stop_loss': '基础止损策略',
            'advanced_risk_management': '高级风控策略'
        }
        
        # 策略图标映射
        strategy_icons = {
            'technical_analysis': '🔧',
            'realtime_monitoring': '⚡',
            'priority_stocks': '⭐',
            'mixed_strategy': '🎯',
            'basic_stop_loss': '🛑',
            'advanced_risk_management': '🚨'
        }
        
        # 获取策略描述
        def get_strategy_description(strategy_name: str) -> str:
            """获取策略描述"""
            if not self.strategy_factory:
                return ""
            strategies_info = self.strategy_factory.list_available_strategies()
            all_strategies = strategies_info.get('selection', []) + strategies_info.get('risk', [])
            for strategy_info in all_strategies:
                if strategy_info['name'] == strategy_name:
                    return strategy_info.get('description', '')
            return ""
        
        print("\n" + "=" * 70)
        print("📋 策略配置预览".center(70))
        print("=" * 70)
        
        # 显示选股策略
        if selected_selection_strategies:
            print("\n  📈 选股策略:")
            for strategy_name in selected_selection_strategies:
                icon = strategy_icons.get(strategy_name, '📊')
                friendly_name = strategy_name_map.get(strategy_name, strategy_name)
                description = get_strategy_description(strategy_name)
                if description:
                    print(f"    {icon} {friendly_name}")
                    print(f"       {description}")
                else:
                    print(f"    {icon} {friendly_name}")
        else:
            print("\n  📈 选股策略: 无")
        
        # 显示风控策略
        if selected_risk_strategies:
            print("\n  🛡️ 风控策略:")
            for strategy_name in selected_risk_strategies:
                icon = strategy_icons.get(strategy_name, '🛡️')
                friendly_name = strategy_name_map.get(strategy_name, strategy_name)
                description = get_strategy_description(strategy_name)
                if description:
                    print(f"    {icon} {friendly_name}")
                    print(f"       {description}")
                else:
                    print(f"    {icon} {friendly_name}")
        else:
            print("\n  🛡️ 风控策略: 无")
        
        print("=" * 70)
        
        while True:
            try:
                print("\n  💡 请确认:")
                print("    1. ✅ 确认并应用配置")
                print("    2. ❌ 取消配置")
                print("    3. 🔄 重新选择策略")
                confirm = input("\n  请输入选择 (1-3): ").strip()
                
                if confirm == '1' or confirm == '':
                    # 应用配置
                    self._apply_strategy_selection(selected_selection_strategies, selected_risk_strategies)
                    log_info("✅ 策略配置已应用")
                    print("\n  ✅ 策略配置已应用")
                    break
                elif confirm == '2':
                    log_info("❌ 已取消策略配置")
                    print("\n  ❌ 已取消策略配置")
                    break
                elif confirm == '3':
                    # 重新选择
                    return self._interactive_select_strategies_for_full_automation()
                else:
                    print("  ❌ 输入无效，请输入 1-3")
                    log_warning("❌ 输入无效，请输入 1-3")
                    
            except KeyboardInterrupt:
                log_info("🛑 用户取消策略配置")
                break
            except Exception as e:
                log_error(f"❌ 配置确认异常: {e}")
    
    def _interactive_select_selection_strategies(self) -> List[str]:
        """交互式选择选股策略（支持多选和回退）"""
        if not self.strategy_factory:
            log_error("策略工厂未初始化，无法获取策略列表")
            return []
        
        strategies_info = self.strategy_factory.list_available_strategies()
        selection_strategies = strategies_info.get('selection', [])
        
        if not selection_strategies:
            log_warning("⚠️ 没有可用的选股策略")
            return []
        
        selected_strategies = []
        strategy_map = {}
        strategy_icons = {
            'technical_analysis': '🔧',
            'realtime_monitoring': '⚡',
            'priority_stocks': '⭐',
            'mixed_strategy': '🎯',
        }
        
        while True:
            print("\n  请选择选股策略（可多选，用逗号分隔）:")
            print("  " + "-" * 66)
            
            # 显示所有可用策略
            for idx, strategy_info in enumerate(selection_strategies, 1):
                strategy_name = strategy_info['name']
                strategy_desc = strategy_info['description']
                icon = strategy_icons.get(strategy_name, '📊')
                status = "✓" if strategy_name in selected_strategies else " "
                print(f"    {idx}. [{status}] {icon} {strategy_desc}")
                strategy_map[str(idx)] = strategy_name
            
            print("  " + "-" * 66)
            
            # 显示当前选择状态
            if selected_strategies:
                friendly_names = []
                for s in selected_strategies:
                    friendly_name = {
                        'technical_analysis': '技术分析选股策略',
                        'realtime_monitoring': '实时数据选股策略',
                        'priority_stocks': '自选股策略',
                        'mixed_strategy': '混合选股策略'
                    }.get(s, s)
                    friendly_names.append(friendly_name)
                print(f"\n  ✅ 当前已选择: {', '.join(friendly_names)}")
            else:
                print("\n  ⚠️  当前未选择任何策略")
            
            print("\n  💡 操作提示:")
            print("     • 输入数字选择/取消策略（如: 1,2,3），选择后自动进入下一步")
            print("     • 输入 'c' 清除所有选择")
            print("     • 输入 'b' 返回上一步")
            print("  " + "-" * 66)
            
            try:
                choice = input("\n  请输入: ").strip().lower()
                
                if choice == 'b' or choice == 'back':
                    return []
                elif choice == 'c' or choice == 'clear':
                    selected_strategies = []
                    log_info("🔄 已清除所有选择")
                    continue
                elif not choice:
                    # 空输入，如果有已选择的策略，直接进入下一步
                    if selected_strategies:
                        break
                    else:
                        log_warning("⚠️ 请至少选择一个选股策略")
                        continue
                else:
                    # 处理多选
                    choices = [c.strip() for c in choice.split(',')]
                    has_valid_choice = False
                    
                    for c in choices:
                        if c in strategy_map:
                            has_valid_choice = True
                            strategy_name = strategy_map[c]
                            if strategy_name in selected_strategies:
                                # 取消选择
                                selected_strategies.remove(strategy_name)
                                log_info(f"❌ 已取消选择: {strategy_name}")
                            else:
                                # 添加选择
                                selected_strategies.append(strategy_name)
                                log_info(f"✅ 已选择: {strategy_name}")
                        else:
                            log_warning(f"❌ 无效选择: {c}")
                    
                    # 如果有有效选择，自动进入下一步
                    if has_valid_choice and selected_strategies:
                        break
                    elif has_valid_choice and not selected_strategies:
                        log_warning("⚠️ 所有策略已取消，请至少选择一个选股策略")
                            
            except KeyboardInterrupt:
                log_info("🛑 用户取消选择")
                return []
            except Exception as e:
                log_error(f"❌ 选择异常: {e}")
        
        return selected_strategies
    
    def _interactive_select_risk_strategies(self) -> List[str]:
        """交互式选择风控策略（支持多选和回退）"""
        if not self.strategy_factory:
            log_error("策略工厂未初始化，无法获取策略列表")
            return []
        
        strategies_info = self.strategy_factory.list_available_strategies()
        risk_strategies = strategies_info.get('risk_management', [])
        
        if not risk_strategies:
            log_warning("⚠️ 没有可用的风控策略")
            return []
        
        selected_strategies = []
        strategy_map = {}
        strategy_icons = {
            'basic_stop_loss': '🛑',
            'advanced_risk_management': '🚨',
        }
        
        while True:
            print("\n  请选择风控策略（可多选，用逗号分隔）:")
            print("  " + "-" * 66)
            
            # 显示所有可用策略
            for idx, strategy_info in enumerate(risk_strategies, 1):
                strategy_name = strategy_info['name']
                strategy_desc = strategy_info['description']
                icon = strategy_icons.get(strategy_name, '🛡️')
                status = "✓" if strategy_name in selected_strategies else " "
                print(f"    {idx}. [{status}] {icon} {strategy_desc}")
                strategy_map[str(idx)] = strategy_name
            
            print("  " + "-" * 66)
            
            # 显示当前选择状态
            if selected_strategies:
                friendly_names = []
                for s in selected_strategies:
                    friendly_name = {
                        'basic_stop_loss': '基础风控策略',
                        'advanced_risk_management': '高级风控策略'
                    }.get(s, s)
                    friendly_names.append(friendly_name)
                print(f"\n  ✅ 当前已选择: {', '.join(friendly_names)}")
            else:
                print("\n  ⚠️  当前未选择任何策略")
            
            print("\n  💡 操作提示:")
            print("     • 输入数字选择/取消策略（如: 1,2），选择后自动进入下一步")
            print("     • 输入 'c' 清除所有选择")
            print("     • 输入 'b' 返回上一步")
            print("  " + "-" * 66)
            
            try:
                choice = input("\n  请输入: ").strip().lower()
                
                if choice == 'b' or choice == 'back':
                    return []
                elif choice == 'c' or choice == 'clear':
                    selected_strategies = []
                    log_info("🔄 已清除所有选择")
                    continue
                elif not choice:
                    # 空输入，如果有已选择的策略，直接进入下一步
                    if selected_strategies:
                        break
                    else:
                        log_warning("⚠️ 请至少选择一个风控策略")
                        continue
                else:
                    # 处理多选
                    choices = [c.strip() for c in choice.split(',')]
                    has_valid_choice = False
                    
                    for c in choices:
                        if c in strategy_map:
                            has_valid_choice = True
                            strategy_name = strategy_map[c]
                            if strategy_name in selected_strategies:
                                # 取消选择
                                selected_strategies.remove(strategy_name)
                                log_info(f"❌ 已取消选择: {strategy_name}")
                            else:
                                # 添加选择
                                selected_strategies.append(strategy_name)
                                log_info(f"✅ 已选择: {strategy_name}")
                        else:
                            log_warning(f"❌ 无效选择: {c}")
                    
                    # 如果有有效选择，自动进入下一步
                    if has_valid_choice and selected_strategies:
                        break
                    elif has_valid_choice and not selected_strategies:
                        log_warning("⚠️ 所有策略已取消，请至少选择一个风控策略")
                            
            except KeyboardInterrupt:
                log_info("🛑 用户取消选择")
                return []
            except Exception as e:
                log_error(f"❌ 选择异常: {e}")
        
        return selected_strategies
    
    def _apply_strategy_selection(self, selection_strategies: List[str], risk_strategies: List[str]):
        """应用策略选择配置"""
        # 禁用所有策略
        selection_config = self.config.system.selection_strategies_config
        for name in selection_config:
            selection_config[name].enabled = False
        
        risk_config = self.config.system.risk_strategies_config
        for name in risk_config:
            risk_config[name].enabled = False
        
        # 启用选中的选股策略
        for strategy_name in selection_strategies:
            if strategy_name in selection_config:
                selection_config[strategy_name].enabled = True
            else:
                # 自动创建配置
                from quant_system.core.config import SelectionStrategyConfig
                selection_config[strategy_name] = SelectionStrategyConfig(
                    enabled=True,
                    weight=1.0,
                    max_stocks=50,
                    min_score=50.0
                )
        
        # 启用选中的风控策略
        for strategy_name in risk_strategies:
            if strategy_name in risk_config:
                risk_config[strategy_name].enabled = True
            else:
                # 自动创建配置
                from quant_system.core.config import RiskStrategyConfig
                risk_config[strategy_name] = RiskStrategyConfig(
                    enabled=True,
                    weight=1.0,
                    risk_threshold=0.8,
                    auto_execute=False
                )
        
        log_info(f"✅ 已启用选股策略: {selection_strategies}")
        log_info(f"✅ 已启用风控策略: {risk_strategies}")

    def _register_shutdown_hooks(self):
        """注册关闭钩子函数 - 增强版本"""
        # 系统运行器关闭钩子
        if self.system_runner:
            self.shutdown_hooks.append(self.system_runner.stop)

        # 系统监控关闭钩子
        if self.system_monitor:
            self.shutdown_hooks.append(self.system_monitor.stop_monitoring)

        # 服务集成器关闭钩子（新增）
        if self.service_integrator:
            self.shutdown_hooks.append(self.service_integrator.shutdown)

        # Broker断开连接钩子
        if self.multi_market_broker:
            self.shutdown_hooks.append(self.multi_market_broker.disconnect)

        log_info(f"✅ 已注册 {len(self.shutdown_hooks)} 个关闭钩子")

    @performance_monitor("system_run")
    def run(self):
        """
        运行交易系统 - 添加详细调试
        """
        self.logger.info("🔍 TradingSystem.run() 开始执行")

        if self.state != SystemState.INITIALIZED:
            log_error("❌ 系统未正确初始化，无法运行")
            return

        self.logger.info(f"🔍 步骤1: 检查 system_runner = {self.system_runner}")
        self.logger.info(f"🔍 步骤1.1: system_runner 类型 = {type(self.system_runner)}")

        if not self.system_runner:
            log_error("❌ 系统运行器未初始化")
            return

        try:
            self.state = SystemState.RUNNING
            self._display_startup_info()

            # 🔧 关键修复：系统运行器应该阻塞在这里
            log_info("🚀 启动交易系统主循环...")

            # 直接调用运行方法，而不是start()
            mode = self.config.system.mode
            self.logger.info(f"🔍 步骤2: 当前模式 = {mode}")
            self.logger.info(f"🔍 步骤2.1: 模式值 = {mode.value}")

            if mode == SystemMode.STOCK_SELECTION_ONLY:
                self.logger.info("🔍 步骤3: 进入选股模式分支")
                self.logger.info("🔍 步骤3.1: 调用 _run_stock_selection_mode")
                self.system_runner._run_stock_selection_mode()  # 直接调用，确保阻塞
                self.logger.info("🔍 步骤3.2: _run_stock_selection_mode 调用完成")
            elif mode == SystemMode.RISK_MANAGEMENT_ONLY:
                self.logger.info("🔍 进入风控模式分支")
                self.system_runner._run_risk_management_mode()
            elif mode == SystemMode.FULL_AUTOMATION:
                self.logger.info("🔍 进入全自动模式分支")
                self.system_runner._run_full_automation_mode()
            elif mode == SystemMode.BACKTEST:
                self.logger.info("🔍 进入回测模式分支")
                self.system_runner._run_backtest_mode()
            else:
                self.logger.error(f"❌ 不支持的运行模式: {mode}")

            log_info("✅ 系统运行器正常结束")

        except Exception as e:
            self.logger.error(f"💥 系统运行异常: {e}")
            import traceback
            self.logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.state = SystemState.ERROR
        finally:
            self.logger.info("🔍 TradingSystem.run() 执行完成")
            self.shutdown()

    def _main_loop(self):
        """
        系统主循环

        在系统运行期间执行定期检查和状态报告。
        """
        try:
            last_status_report = time.time()
            status_report_interval = 300  # 5分钟报告一次

            while self.state == SystemState.RUNNING and not self._shutdown_requested:
                # 定期报告系统状态
                current_time = time.time()
                if current_time - last_status_report >= status_report_interval:
                    self._report_system_status()
                    last_status_report = current_time

                # 检查系统健康状态
                if not self._check_system_health():
                    log_warning("⚠️ 系统健康检查未通过")

                # 短暂休眠避免CPU占用过高
                time.sleep(1)

        except Exception as e:
            log_error(f"❌ 主循环异常: {e}")

    def _display_startup_info(self):
        """显示系统启动信息 - 增强版本"""
        current_market = self.config.current_market
        market_config = self.config.get_current_market_config()

        # 获取启用的策略信息
        enabled_selection_strategies = self.config.system.get_enabled_selection_strategies()
        enabled_risk_strategies = self.config.system.get_enabled_risk_strategies()

        # 策略名称映射（用于显示友好名称）
        strategy_name_map = {
            'technical_analysis': '技术分析选股',
            'realtime_monitoring': '实时数据选股',
            'priority_stocks': '自选股策略',
            'mixed_strategy': '混合选股策略',
            'basic_stop_loss': '基础止损',
            'advanced_risk_management': '高级风控'
        }

        # 检查分级仓位状态
        scaling_enabled = False
        if self.service_integrator:
            service_status = self.service_integrator.get_system_status()
            scaling_enabled = service_status.get('scaling_enabled', False)

        print("\n" + "=" * 70)
        print("🏁 交易系统启动信息".center(70))
        print("=" * 70)
        print(f"  📊 交易市场: {current_market.value.upper()}")
        print(f"  🎯 工作模式: {self.config.system.mode.value}")
        print(f"  🔗 券商类型: {market_config.broker_type.value}")
        print(f"  💰 交易货币: {market_config.currency}")
        print(f"  🎚️ 分级仓位: {'启用' if scaling_enabled else '禁用'}")

        # 显示选股策略
        if enabled_selection_strategies:
            strategy_names = [strategy_name_map.get(s, s) for s in enabled_selection_strategies]
            print(f"  📈 选股策略: {', '.join(strategy_names)}")
        else:
            print("  📈 选股策略: 无")

        # 显示风控策略
        if enabled_risk_strategies:
            risk_names = [strategy_name_map.get(s, s) for s in enabled_risk_strategies]
            print(f"  🛡️ 风控策略: {', '.join(risk_names)}")
        else:
            print("  🛡️ 风控策略: 无")

        print(f"  🕐 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

    def _report_system_status(self):
        """报告系统状态"""
        try:
            status = self.get_system_status()
            performance = get_performance_summary()

            log_info("📈 系统状态报告:")
            log_info(f"   运行时间: {status.get('uptime', 'N/A')}")
            log_info(f"   连接市场: {', '.join(status.get('connected_markets', []))}")
            log_info(f"   总操作数: {performance.get('total_operations', 0)}")
            log_info(f"   系统负载: {status.get('system_load', 'N/A')}")

        except Exception as e:
            log_error(f"❌ 状态报告异常: {e}")

    def _check_system_health(self) -> bool:
        """
        检查系统健康状态

        Returns:
            bool: 系统是否健康
        """
        try:
            # 检查Broker连接
            if self.multi_market_broker:
                connected_markets = self.multi_market_broker.get_connected_markets()
                if not connected_markets:
                    log_error("❌ 所有市场连接已断开")
                    return False

            # 检查系统运行器状态
            if self.system_runner and not self.system_runner.running:  # 修复：使用 running 属性
                log_error("❌ 系统运行器已停止")
                return False

            return True

        except Exception as e:
            log_error(f"❌ 健康检查异常: {e}")
            return False

    def configure_strategies_for_mode(self):
        """根据工作模式配置策略"""
        mode = self.config.system.mode

        strategy_configurators = {
            SystemMode.STOCK_SELECTION_ONLY: self._configure_selection_mode,
            SystemMode.RISK_MANAGEMENT_ONLY: self._configure_risk_mode,
            SystemMode.FULL_AUTOMATION: self._configure_full_automation_mode,
            SystemMode.BACKTEST: self._configure_backtest_mode,
            SystemMode.DEBUG: self._configure_debug_mode
        }

        configurator = strategy_configurators.get(mode)
        if configurator:
            configurator()
        else:
            log_warning(f"⚠️ 未知的工作模式: {mode}，使用默认配置")

    def _configure_selection_mode(self):
        """配置选股模式"""
        log_info("🎯 配置选股模式策略...")

        # 使用现有的策略配置方法
        selection_config = self.config.system.selection_strategies_config

        # 启用所有选股策略，禁用所有风控策略
        for strategy_name in selection_config:
            selection_config[strategy_name].enabled = True

        risk_config = self.config.system.risk_strategies_config
        for strategy_name in risk_config:
            risk_config[strategy_name].enabled = False

        enabled_strategies = self.config.system.get_enabled_selection_strategies()
        log_info(f"✅ 已启用选股策略: {enabled_strategies}")

    def _configure_risk_mode(self):
        """配置风控模式"""
        log_info("🛡️ 配置风控模式策略...")

        # 启用所有风控策略，禁用所有选股策略
        selection_config = self.config.system.selection_strategies_config
        for strategy_name in selection_config:
            selection_config[strategy_name].enabled = False

        risk_config = self.config.system.risk_strategies_config
        for strategy_name in risk_config:
            risk_config[strategy_name].enabled = True

        enabled_strategies = self.config.system.get_enabled_risk_strategies()
        log_info(f"✅ 已启用风控策略: {enabled_strategies}")

    def _configure_full_automation_mode(self):
        """配置全自动模式"""
        log_info("🤖 配置全自动模式策略...")

        # 启用所有策略
        selection_config = self.config.system.selection_strategies_config
        for strategy_name in selection_config:
            selection_config[strategy_name].enabled = True

        risk_config = self.config.system.risk_strategies_config
        for strategy_name in risk_config:
            risk_config[strategy_name].enabled = True

        enabled_selection = self.config.system.get_enabled_selection_strategies()
        enabled_risk = self.config.system.get_enabled_risk_strategies()

        log_info(f"✅ 选股策略: {enabled_selection}")
        log_info(f"✅ 风控策略: {enabled_risk}")

    def _configure_backtest_mode(self):
        """配置回测模式"""
        log_info("📊 配置回测模式策略...")

        # 启用所有策略进行回测
        selection_config = self.config.system.selection_strategies_config
        for strategy_name in selection_config:
            selection_config[strategy_name].enabled = True

        risk_config = self.config.system.risk_strategies_config
        for strategy_name in risk_config:
            risk_config[strategy_name].enabled = True

        enabled_selection = self.config.system.get_enabled_selection_strategies()
        enabled_risk = self.config.system.get_enabled_risk_strategies()

        log_info(f"✅ 回测模式启用所有策略:")
        log_info(f"   选股策略: {enabled_selection}")
        log_info(f"   风控策略: {enabled_risk}")

    def _configure_debug_mode(self):
        """配置调试模式"""
        log_info("🔧 配置调试模式策略...")

        # 调试模式只启用基础策略
        selection_config = self.config.system.selection_strategies_config
        for strategy_name in selection_config:
            selection_config[strategy_name].enabled = (strategy_name == "technical_analysis")

        risk_config = self.config.system.risk_strategies_config
        for strategy_name in risk_config:
            risk_config[strategy_name].enabled = False

        enabled_strategies = self.config.system.get_enabled_selection_strategies()
        log_info(f"✅ 调试模式启用策略: {enabled_strategies}")

    def get_system_status(self) -> Dict[str, Any]:
        """
        获取完整的系统状态信息 - 增强版本

        Returns:
            Dict[str, Any]: 系统状态字典
        """
        status = {
            'state': self.state.value,
            'current_market': self.config.current_market.value if self.config else 'unknown',
            'current_mode': self.config.system.mode.value if self.config else 'unknown',
            'uptime': self._get_uptime(),
            'initialization_time': self._start_time.isoformat() if self._start_time else 'unknown'
        }

        # Broker状态
        if self.multi_market_broker:
            status['connected_markets'] = [
                market.value for market in self.multi_market_broker.get_connected_markets()
            ]
            status['broker_health'] = self.multi_market_broker.health_check()

        # 服务集成器状态（新增）
        if self.service_integrator:
            service_status = self.service_integrator.get_system_status()
            status['service_integrator'] = service_status
            status['scaling_enabled'] = service_status.get('scaling_enabled', False)
        else:
            status['scaling_enabled'] = False

        # 监控系统状态
        if self.system_monitor:
            status.update(self.system_monitor.get_system_status())

        # 性能统计
        try:
            performance_stats = get_performance_summary()
            status['performance'] = performance_stats
        except Exception as e:
            log_warning(f"获取性能统计失败: {e}")

        return status

    def _get_uptime(self) -> str:
        """获取系统运行时间"""
        if not self._start_time:
            return "0s"

        uptime = datetime.now() - self._start_time
        total_seconds = int(uptime.total_seconds())

        # 格式化运行时间
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @performance_monitor("system_shutdown")
    def shutdown(self):
        """
        优雅关闭系统

        按照注册的关闭钩子顺序执行资源清理，确保数据完整性和状态一致性。
        """
        if self.state in [SystemState.STOPPING, SystemState.STOPPED]:
            return

        self.state = SystemState.STOPPING
        log_info("🔚 开始关闭交易系统...")

        shutdown_start = datetime.now()
        success_count = 0
        total_hooks = len(self.shutdown_hooks)

        # 逆序执行关闭钩子（后进先出）
        for i, hook in enumerate(reversed(self.shutdown_hooks), 1):
            try:
                log_info(f"执行关闭钩子 {i}/{total_hooks}...")
                hook()
                success_count += 1
                log_info(f"✅ 关闭钩子 {i}/{total_hooks} 执行成功")
            except Exception as e:
                log_error(f"❌ 关闭钩子 {i}/{total_hooks} 执行失败: {e}")

        # 清理其他资源
        self._cleanup_resources()

        self.state = SystemState.STOPPED
        shutdown_time = (datetime.now() - shutdown_start).total_seconds()

        log_info(f"✅ 系统关闭完成 - 成功: {success_count}/{total_hooks}, 耗时: {shutdown_time:.2f}秒")

    def _cleanup_resources(self):
        """清理系统资源"""
        # 清理全局变量引用
        self.config = None
        self.multi_market_broker = None
        self.strategy_factory = None
        self.system_runner = None
        self.system_monitor = None
        self.portfolio_manager = None
        self.shutdown_hooks.clear()

        log_info("✅ 系统资源清理完成")


@performance_monitor("main_function")
def main() -> int:
    """
    主函数 - 优化版本

    系统入口点，负责创建交易系统实例并启动运行。

    Returns:
        int: 退出代码 (0表示成功，非0表示错误)
    """
    system = None
    exit_code = 0

    try:
        log_info("🎉 启动量化交易系统")

        # 创建系统实例
        system = TradingSystem()

        # 初始化系统
        if system.initialize():
            # 运行系统
            system.run()
            log_info("✅ 交易系统正常结束")
        else:
            log_error("❌ 系统初始化失败")
            exit_code = 1

    except KeyboardInterrupt:
        log_info("🛑 程序被用户中断")
        exit_code = 0
    except SystemInitializationError as e:
        error_msg = f"❌ 系统初始化错误: {e}"
        log_error(error_msg)
        print(error_msg)  # 同步输出到控制台
        import traceback
        error_traceback = traceback.format_exc()
        log_error(f"详细堆栈: {error_traceback}")
        print(f"详细堆栈: {error_traceback}")  # 同步输出到控制台
        exit_code = 2
    except BrokerConnectionError as e:
        error_msg = f"❌ Broker连接错误: {e}"
        log_error(error_msg)
        print("\n" + "=" * 70)
        print("❌ Broker连接失败".center(70))
        print("=" * 70)
        print(f"  错误信息: {e}")
        print("\n  请检查以下事项：")
        print("  1. 富途客户端是否已启动")
        print("  2. 富途客户端是否已登录账户")
        print("  3. 富途客户端是否开启了API接口（设置 -> API设置）")
        print("  4. 端口号是否正确（默认: 11111）")
        print("=" * 70)
        import traceback
        error_traceback = traceback.format_exc()
        log_error(f"详细堆栈: {error_traceback}")
        exit_code = 3
    except Exception as e:
        log_error(f"💥 未处理的系统异常: {e}")
        exit_code = 4
    finally:
        # 确保系统正确关闭
        if system and system.state != SystemState.STOPPED:
            system.shutdown()

    return exit_code


if __name__ == "__main__":
    """
    程序入口点

    设置全局异常处理并调用主函数。
    """
    try:
        # 设置全局异常处理器
        def global_exception_handler(exc_type, exc_value, exc_traceback):
            """全局异常处理器"""
            if issubclass(exc_type, KeyboardInterrupt):
                # 不处理键盘中断
                return
            log_error(f"💥 未捕获的异常: {exc_value}", exc_info=(exc_type, exc_value, exc_traceback))


        sys.excepthook = global_exception_handler

        # 运行主程序
        exit_code = main()
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n🛑 程序被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 程序启动异常: {e}")
        sys.exit(1)

print("✅ 程序执行完毕，主线程退出")