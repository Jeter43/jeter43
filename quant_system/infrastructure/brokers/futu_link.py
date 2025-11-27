"""
quant_system/infrastructure/brokers/futu_link.py
修复版 — 增强股票类型识别和频率限制控制
"""

import sys
import os
import time
import socket
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from functools import wraps
import pandas as pd
from threading import Lock

# 将项目根加入路径，确保相对导入生效
current_file = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# futu SDK
try:
    from futu import *
except Exception:
    # 在没有 futu 环境下仍允许导入模块以便静态分析/测试
    pass

from dataclasses import dataclass

from quant_system.infrastructure.brokers.base import Broker
from quant_system.core.config import ConfigManager, TradingEnvironment
from quant_system.core.exceptions import (
    BrokerConnectionError,
    BrokerOperationError,
    OrderExecutionError
)
from quant_system.core.events import Event, EventType, event_bus
from quant_system.infrastructure.data.manager import MarketData, PositionData
from quant_system.utils.logger import get_logger
from quant_system.utils.monitoring import performance_monitor


@dataclass
class FutuConfig:
    host: str
    port: int
    market: str = "HK"
    trading_password: Optional[str] = None
    unlock_required: bool = False


class RateLimiter:
    """频率限制器，用于控制API调用频率"""

    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = Lock()

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self.lock:
                now = time.time()
                # 移除过期的调用记录
                self.calls = [call_time for call_time in self.calls
                            if now - call_time < self.period]

                # 检查是否超过限制
                if len(self.calls) >= self.max_calls:
                    oldest_call = self.calls[0]
                    sleep_time = self.period - (now - oldest_call)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        # 睡眠后重新计算
                        now = time.time()
                        self.calls = [call_time for call_time in self.calls
                                    if now - call_time < self.period]

                # 记录本次调用
                self.calls.append(now)

            return func(*args, **kwargs)
        return wrapper


# 创建频率限制器
# 富途API限制：每30秒最多60次调用
quote_limiter = RateLimiter(max_calls=55, period=30.0)  # 留5次余量
trade_limiter = RateLimiter(max_calls=25, period=30.0)  # 交易API限制更严格


def handle_futu_errors(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            self._operation_count += 1
            return func(self, *args, **kwargs)
        except Exception as e:
            self.logger.error(f"富途操作失败 [{func.__name__}]: {e}")
            # 根据函数名做出更明确的异常类型
            if "connect" in func.__name__:
                raise BrokerConnectionError(str(e)) from e
            if "order" in func.__name__ or "place" in func.__name__:
                raise OrderExecutionError(str(e)) from e
            raise BrokerOperationError(str(e)) from e

    return wrapper


class FutuBroker(Broker):
    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = get_logger(__name__)

        self.futu_config = self._load_futu_config()

        self.quote_context = None
        self.trade_context = None
        self.trading_environment = TrdEnv.SIMULATE if 'TrdEnv' in globals() else None
        self.connected = False

        self.quote_handler = None
        self.trade_handler = None

        self._connection_time = None
        self._operation_count = 0

        # 频率控制相关 - 使用滑动窗口
        self._api_call_times = []  # 存储最近30秒内的调用时间戳
        self._rate_limit_lock = Lock()
        self._batch_delay = 0.1  # 批次间延迟（秒）

        self._market_map = {
            "HK": TrdMarket.HK if 'TrdMarket' in globals() else None,
            "US": TrdMarket.US if 'TrdMarket' in globals() else None,
            "CN": TrdMarket.CN if 'TrdMarket' in globals() else None
        }

        # 衍生品代码前缀（用于过滤）
        self._derivative_prefixes = ['810', '441', '457', '458', '459', '883', '884']

    def _check_rate_limit(self):
        """
        检查并遵守API频率限制 - 使用严格的滑动窗口算法
        
        富途API限制：每30秒最多60次调用
        使用滑动窗口确保严格遵守限制，避免并发请求时超限
        """
        with self._rate_limit_lock:
            current_time = time.time()
            
            # 移除30秒前的调用记录（滑动窗口）
            self._api_call_times = [t for t in self._api_call_times if current_time - t < 30.0]
            
            # 更严格的限制：每30秒最多55次（留5次余量，避免边界情况和并发超限）
            max_calls = 55  # 留5次余量，更安全
            
            if len(self._api_call_times) >= max_calls:
                # 计算需要等待的时间（等待最老的调用超过30秒）
                oldest_call = self._api_call_times[0]
                sleep_time = 30.0 - (current_time - oldest_call) + 0.1  # 加0.1秒缓冲
                
                if sleep_time > 0:
                    self.logger.warning(f"📊 API频率限制，等待 {sleep_time:.1f} 秒（已调用 {len(self._api_call_times)} 次/30秒）")
                    time.sleep(sleep_time)
                    # 等待后重新计算
                    current_time = time.time()
                    self._api_call_times = [t for t in self._api_call_times if current_time - t < 30.0]
            
            # 记录本次调用
            self._api_call_times.append(current_time)

    def _batch_process_symbols(self, symbols: List[str], batch_size: int = 50) -> List[List[str]]:
        """将股票列表分批处理"""
        batches = []
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            batches.append(batch)
        return batches

    def _load_futu_config(self) -> FutuConfig:
        try:
            market_config = self.config.get_current_market_config()
            return FutuConfig(
                host=self.config.broker.host,
                port=self.config.broker.port,
                market=getattr(market_config, 'market_type', getattr(market_config, 'market', 'HK')).value
                if market_config is not None else 'HK',
                trading_password=getattr(self.config.trading, 'trading_password', None),
                unlock_required=(getattr(self.config.trading, 'environment', None) == TradingEnvironment.REAL)
            )
        except Exception as e:
            self.logger.warning(f"加载富途配置失败，使用默认: {e}")
            return FutuConfig(host="127.0.0.1", port=11111, market="HK")

    def _is_derivative_product(self, symbol: str, stock_data: Dict[str, Any]) -> bool:
        """
        判断是否为衍生品（权证、指数等），这些应该被过滤掉
        """
        # 通过代码前缀识别
        code_only = symbol.replace('HK.', '') if symbol.startswith('HK.') else symbol

        if any(code_only.startswith(prefix) for prefix in self._derivative_prefixes):
            return True

        # 通过股票类型识别（如果数据中有类型字段）
        stock_type = stock_data.get('stock_type', '')
        stock_name = stock_data.get('name', '')

        if stock_type and stock_type.upper() in ['WARRANT', 'IDX', 'FUTURE', 'OPTION', 'TRUST', 'BOND']:
            return True

        # 通过名称识别衍生品
        if stock_name and any(keyword in stock_name.upper() for keyword in ['权证', '窝轮', '牛熊证', '指数', 'ETF', '基金']):
            return True

        # 通过价格和市值特征识别
        price = stock_data.get('last_price', 0)
        market_cap = self._get_effective_market_cap(stock_data)

        # 价格极低且市值为0的通常是衍生品
        if price < 0.01 and market_cap == 0:
            return True

        return False

    def _get_effective_market_cap(self, stock_data: Dict[str, Any]) -> float:
        """
        获取有效的市值数据，优先使用流通市值
        """
        # 优先级：流通市值 > 总市值 > 其他市值字段
        circulating_market_val = stock_data.get('circulating_market_val', 0)
        if circulating_market_val > 0:
            return circulating_market_val

        total_market_val = stock_data.get('total_market_val', 0)
        if total_market_val > 0:
            return total_market_val

        market_cap = stock_data.get('market_cap', 0)
        if market_cap > 0:
            return market_cap

        # 尝试其他可能的市值字段
        for field in ['total_market_cap', 'market_value', 'capitalization']:
            value = stock_data.get(field, 0)
            if value > 0:
                return value

        return 0.0

    def is_connected(self) -> bool:
        if not self.connected or not self.quote_context:
            return False
        try:
            ret, state = self.quote_context.get_global_state()
            return ret == RET_OK
        except Exception:
            return False

    def _diagnose_connection(self) -> Dict[str, Any]:
        """
        诊断连接问题，返回诊断信息
        
        Returns:
            Dict[str, Any]: 诊断结果
        """
        diagnosis = {
            'host': self.futu_config.host,
            'port': self.futu_config.port,
            'futu_available': 'OpenQuoteContext' in globals(),
            'can_import_futu': False,
            'connection_test': None,
            'suggestions': []
        }
        
        # 检查futu模块是否可用
        try:
            import futu
            diagnosis['can_import_futu'] = True
        except ImportError:
            diagnosis['suggestions'].append("❌ futu模块未安装，请运行: pip install futu")
            return diagnosis
        
        # 检查端口是否可访问
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)  # 2秒超时
            result = sock.connect_ex((self.futu_config.host, self.futu_config.port))
            sock.close()
            if result == 0:
                diagnosis['connection_test'] = '端口可访问'
            else:
                diagnosis['connection_test'] = f'端口不可访问 (错误码: {result})'
                diagnosis['suggestions'].append(f"❌ 无法连接到 {self.futu_config.host}:{self.futu_config.port}")
                diagnosis['suggestions'].append("   请检查：")
                diagnosis['suggestions'].append("   1. 富途客户端是否已启动")
                diagnosis['suggestions'].append("   2. 富途客户端是否已登录")
                diagnosis['suggestions'].append("   3. 富途客户端 -> 设置 -> API设置 -> 是否已开启API接口")
                diagnosis['suggestions'].append("   4. 端口号是否正确（默认: 11111）")
        except Exception as e:
            diagnosis['connection_test'] = f'端口测试失败: {e}'
            diagnosis['suggestions'].append(f"❌ 端口测试异常: {e}")
        
        return diagnosis

    @performance_monitor("futu_connect")
    @handle_futu_errors
    def connect(self) -> bool:
        self.logger.info("开始连接富途...")
        if self.connected and self.quote_context and self.trade_context:
            self.logger.info("富途已连接，跳过")
            return True
        
        # 先进行连接诊断
        diagnosis = self._diagnose_connection()
        self.logger.info(f"连接诊断: {diagnosis}")
        
        try:
            # 清理旧连接
            self._cleanup_contexts()

            # 创建上下文（当 futu 可用）
            if 'OpenQuoteContext' in globals():
                self.quote_context = OpenQuoteContext(host=self.futu_config.host, port=self.futu_config.port)
            else:
                self.quote_context = None
                self.logger.error("❌ OpenQuoteContext 不可用，futu模块可能未正确导入")
                return False

            if 'OpenSecTradeContext' in globals():
                self.trade_context = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host=self.futu_config.host, port=self.futu_config.port)
            else:
                self.trade_context = None
                self.logger.warning("⚠️ OpenSecTradeContext 不可用，交易功能可能受限")

            # 设置环境
            self.trading_environment = TrdEnv.SIMULATE if 'TrdEnv' in globals() else None
            try:
                if getattr(self.config, 'trading', None) and getattr(self.config.trading, 'environment', None) == TradingEnvironment.REAL:
                    self.trading_environment = TrdEnv.REAL
            except Exception:
                pass

            # 基本检测
            if self.quote_context:
                ret, state = self.quote_context.get_global_state()
                if ret != RET_OK:
                    self.logger.error(f"行情连接测试失败: {state}")
                    self._cleanup_contexts()
                    return False

            # 交易上下文可选
            if self.trade_context:
                try:
                    ret, acc = self.trade_context.accinfo_query(trd_env=self.trading_environment)
                    # 不强制要求成功
                except Exception as e:
                    self.logger.warning(f"交易上下文测试异常: {e}")

            self.connected = True
            self._connection_time = datetime.now()
            self._operation_count = 0

            # 发布连接事件（如果失败不影响连接）
            try:
                event_bus.publish(Event(event_type=EventType.BROKER_CONNECTED, data={'broker': 'futu', 'timestamp': datetime.now()}))
            except Exception as e:
                self.logger.warning(f"⚠️ 发布Broker连接事件失败: {e}，但不影响连接")
            
            self.logger.info("富途连接成功")
            # 详细日志已移至日志文件，控制台不显示
            return True

        except Exception as e:
            self.connected = False
            self._cleanup_contexts()
            try:
                event_bus.publish(Event(event_type=EventType.BROKER_CONNECTION_FAILED, data={'broker': 'futu', 'error': str(e)}))
            except Exception:
                pass
            error_msg = str(e)
            self.logger.error(f"连接富途失败: {error_msg}")
            
            # 显示详细的错误信息和诊断结果
            print("\n" + "=" * 70)
            print("❌ 富途连接失败".center(70))
            print("=" * 70)
            print(f"  错误信息: {error_msg}")
            print(f"  连接地址: {self.futu_config.host}:{self.futu_config.port}")
            print()
            
            # 显示诊断信息
            if diagnosis.get('suggestions'):
                print("  诊断结果:")
                for suggestion in diagnosis['suggestions']:
                    print(f"  {suggestion}")
            else:
                print("  请检查以下事项：")
                print("  1. 富途客户端是否已启动")
                print("  2. 富途客户端是否已登录账户")
                print("  3. 富途客户端 -> 设置 -> API设置 -> 是否已开启API接口")
                print("  4. 端口号是否正确（默认: 11111）")
                print("  5. 防火墙是否阻止了连接")
            
            print()
            print("  详细步骤：")
            print("  1. 打开富途牛牛客户端")
            print("  2. 登录您的账户")
            print("  3. 点击 设置 -> 其他设置 -> API设置")
            print("  4. 勾选 '启用API' 选项")
            print("  5. 确认端口号为 11111（或您自定义的端口）")
            print("  6. 重新运行程序")
            print("=" * 70)
            
            return False

    def _cleanup_contexts(self):
        try:
            if self.quote_context and hasattr(self.quote_context, 'close'):
                try:
                    self.quote_context.close()
                except Exception:
                    pass
                self.quote_context = None
            if self.trade_context and hasattr(self.trade_context, 'close'):
                try:
                    self.trade_context.close()
                except Exception:
                    pass
                self.trade_context = None
        except Exception as e:
            self.logger.debug(f"清理上下文异常: {e}")

    @handle_futu_errors
    def _unlock_trade(self) -> bool:
        if not self.futu_config.trading_password:
            self.logger.warning("未配置交易密码")
            return False
        if not self.trade_context:
            self.logger.warning("交易上下文不可用")
            return False
        try:
            ret, data = self.trade_context.unlock_trade(self.futu_config.trading_password)
            return ret == RET_OK
        except Exception as e:
            self.logger.error(f"解锁交易异常: {e}")
            return False

    @handle_futu_errors
    def disconnect(self):
        self.logger.info("断开富途连接...")
        duration = 0.0
        if self._connection_time:
            duration = (datetime.now() - self._connection_time).total_seconds()
        self.connected = False
        self._cleanup_contexts()
        event_bus.publish(Event(event_type=EventType.BROKER_DISCONNECTED, data={'broker': 'futu', 'timestamp': datetime.now(), 'duration': duration}))
        self.logger.info("已断开")

    @performance_monitor("futu_get_account_info")
    @handle_futu_errors
    def get_account_info(self) -> Dict[str, float]:
        if not self.connected or not self.trade_context:
            self.logger.warning("未连接交易上下文，返回回退账户信息")
            return self._get_fallback_account_info()
        try:
            self._check_rate_limit()
            ret, data = self.trade_context.accinfo_query(trd_env=self.trading_environment)
            # data 可能为 DataFrame 或 dict
            if ret != RET_OK:
                self.logger.warning("accinfo_query 返回错误，使用回退信息")
                return self._get_fallback_account_info()
            # 支持 DataFrame
            if isinstance(data, pd.DataFrame) and not data.empty:
                row = data.iloc[0]
                total_assets = float(row.get('total_assets', row.get('total_asset', 0)))
                cash = float(row.get('cash', row.get('available_cash', 0)))
                frozen = float(row.get('frozen_cash', 0)) if 'frozen_cash' in row else 0.0
                market_val = float(row.get('market_val', row.get('market_value', 0)))
                avail = cash - frozen
                return {'total_assets': total_assets, 'cash': cash, 'available_cash': avail, 'market_value': market_val, 'frozen_cash': frozen}
            # 支持 dict
            if isinstance(data, dict):
                total_assets = float(data.get('total_assets', data.get('total_asset', 0)))
                cash = float(data.get('cash', data.get('available_cash', 0)))
                frozen = float(data.get('frozen_cash', 0))
                market_val = float(data.get('market_val', data.get('market_value', 0)))
                avail = cash - frozen
                return {'total_assets': total_assets, 'cash': cash, 'available_cash': avail, 'market_value': market_val, 'frozen_cash': frozen}
            # 未知格式
            return self._get_fallback_account_info()
        except Exception as e:
            self.logger.error(f"获取账户信息异常: {e}")
            return self._get_fallback_account_info()

    def _get_fallback_account_info(self) -> Dict[str, float]:
        self.logger.info("使用回退账户信息")
        return {'total_assets': 1000000.0, 'cash': 1000000.0, 'available_cash': 1000000.0, 'market_value': 0.0, 'frozen_cash': 0.0}

    @performance_monitor("futu_get_positions")
    @handle_futu_errors
    def get_positions(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        positions = {}
        if not self.connected or not self.trade_context:
            self.logger.warning("未连接交易上下文，返回空持仓")
            return {}
        try:
            self._check_rate_limit()
            ret, data = self.trade_context.position_list_query(trd_env=self.trading_environment)
            if ret == RET_OK and isinstance(data, pd.DataFrame) and not data.empty:
                for _, row in data.iterrows():
                    code = str(row.get('code', '')).strip()
                    if not code:
                        continue
                    qty = int(row.get('qty', 0))
                    if qty <= 0:
                        continue
                    positions[code] = {
                        'quantity': qty,
                        'cost_price': float(row.get('cost_price', 0)),
                        'market_value': float(row.get('market_val', 0)),
                        'avg_price': float(row.get('cost_price', 0)),
                        'profit_loss': float(row.get('pl_ratio', 0))
                    }
            else:
                self.logger.debug("position_list_query 返回空或非DataFrame")
        except Exception as e:
            self.logger.error(f"获取持仓异常: {e}")
        return positions

    @performance_monitor("futu_get_market_snapshot")
    @handle_futu_errors
    def get_market_snapshot(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        if not symbols:
            self.logger.debug("get_market_snapshot: symbols 为空")
            return {}
        if not self.connected or not self.quote_context:
            self.logger.warning("行情上下文不可用，无法获取快照")
            return {}

        try:
            # 分批处理大量股票
            if len(symbols) > 50:
                self.logger.info(f"📦 分批获取快照数据，共 {len(symbols)} 只股票")
                return self._get_market_snapshot_batch(symbols)

            # 单批次处理
            self._check_rate_limit()
            ret, data = self.quote_context.get_market_snapshot(symbols)
            if ret != RET_OK:
                self.logger.warning(f"get_market_snapshot 返回错误: {data}")
                return {}
            return self._process_snapshot_data(data)

        except Exception as e:
            self.logger.error(f"获取快照异常: {e}")
            return {}

    def _get_market_snapshot_batch(self, symbols: List[str], batch_size: int = 50) -> Dict[str, Dict[str, Any]]:
        """分批获取市场快照数据"""
        batches = self._batch_process_symbols(symbols, batch_size)
        all_results = {}

        self.logger.info(f"🔄 开始分批获取快照，共 {len(batches)} 个批次")

        for i, batch in enumerate(batches):
            self.logger.debug(f"📡 获取快照批次 {i+1}/{len(batches)}: {len(batch)} 只")

            try:
                self._check_rate_limit()
                ret, data = self.quote_context.get_market_snapshot(batch)

                if ret == RET_OK:
                    batch_results = self._process_snapshot_data(data)
                    all_results.update(batch_results)
                else:
                    self.logger.warning(f"批次 {i+1} 获取失败: {data}")

                # 批次间延迟，避免频率限制
                if i < len(batches) - 1:
                    time.sleep(self._batch_delay)

            except Exception as e:
                self.logger.error(f"批次 {i+1} 处理异常: {e}")
                continue

        self.logger.info(f"✅ 分批获取完成，成功获取 {len(all_results)} 只股票数据")
        return all_results

    def _process_snapshot_data(self, data) -> Dict[str, Dict[str, Any]]:
        """处理快照数据并过滤衍生品"""
        result = {}

        if isinstance(data, pd.DataFrame):
            for _, row in data.iterrows():
                raw_code = row.get('code', '') or row.get('stock_code', '') or ''
                code_str = str(raw_code).strip()
                if code_str == '':
                    continue
                if not code_str.startswith('HK.') and not code_str.startswith('US.') and '.' not in code_str:
                    norm_symbol = f'HK.{code_str}'
                else:
                    norm_symbol = code_str

                stock_data = {
                    'last_price': self._safe_float(row, 'last_price'),
                    'open_price': self._safe_float(row, 'open_price'),
                    'high_price': self._safe_float(row, 'high_price'),
                    'low_price': self._safe_float(row, 'low_price'),
                    'prev_close_price': self._safe_float(row, 'prev_close_price'),
                    'volume': self._safe_int(row, 'volume'),
                    'turnover': self._safe_float(row, 'turnover'),
                    'change_rate': self._safe_float(row, 'change_rate'),
                    'amplitude': self._safe_float(row, 'amplitude'),
                    'bid_price': self._safe_float(row, 'bid_price'),
                    'ask_price': self._safe_float(row, 'ask_price'),
                    'market_cap': self._safe_float(row, 'market_cap'),
                    'total_market_val': self._safe_float(row, 'total_market_val'),
                    'circulating_market_val': self._safe_float(row, 'circulating_market_val'),
                    'net_asset': self._safe_float(row, 'net_asset'),
                    'pe_ratio': self._safe_float(row, 'pe_ratio'),
                    'pb_ratio': self._safe_float(row, 'pb_ratio'),
                    'pe_ttm': self._safe_float(row, 'pe_ttm'),
                    'eps': self._safe_float(row, 'eps'),
                    'total_market_cap': self._safe_float(row, 'total_market_cap'),
                    'market_value': self._safe_float(row, 'market_value'),
                    'capitalization': self._safe_float(row, 'capitalization'),
                    'lot_size': self._safe_int(row, 'lot_size'),
                    'deal_unit': self._safe_int(row, 'deal_unit'),
                    'trade_unit': self._safe_int(row, 'trade_unit'),
                    'order_unit': self._safe_int(row, 'order_unit'),
                    'min_trade_quantity': self._safe_int(row, 'min_trade_quantity'),
                    'raw_code': raw_code,
                    'name': row.get('name', row.get('stock_name', norm_symbol))
                }

                result[norm_symbol] = stock_data

        elif isinstance(data, dict):
            for code, item in data.items():
                stock_data = {
                    'last_price': float(item.get('last_price', 0) or 0),
                    'open_price': float(item.get('open_price', 0) or 0),
                    'high_price': float(item.get('high_price', 0) or 0),
                    'low_price': float(item.get('low_price', 0) or 0),
                    'prev_close_price': float(item.get('prev_close_price', 0) or 0),
                    'volume': int(item.get('volume', 0) or 0),
                    'turnover': float(item.get('turnover', 0) or 0),
                    'change_rate': float(item.get('change_rate', 0) or 0),
                    'amplitude': float(item.get('amplitude', 0) or 0),
                    'bid_price': float(item.get('bid_price', 0) or 0),
                    'ask_price': float(item.get('ask_price', 0) or 0),
                    'market_cap': float(item.get('market_cap', 0) or 0),
                    'total_market_val': float(item.get('total_market_val', 0) or 0),
                    'circulating_market_val': float(item.get('circulating_market_val', 0) or 0),
                    'net_asset': float(item.get('net_asset', 0) or 0),
                    'pe_ratio': float(item.get('pe_ratio', 0) or 0),
                    'pb_ratio': float(item.get('pb_ratio', 0) or 0),
                    'pe_ttm': float(item.get('pe_ttm', 0) or 0),
                    'eps': float(item.get('eps', 0) or 0),
                    'lot_size': int(item.get('lot_size', 0) or 0),
                    'deal_unit': int(item.get('deal_unit', 0) or 0),
                    'trade_unit': int(item.get('trade_unit', 0) or 0),
                    'order_unit': int(item.get('order_unit', 0) or 0),
                    'min_trade_quantity': int(item.get('min_trade_quantity', 0) or 0),
                    'name': item.get('name', code)
                }
                result[code] = stock_data

        # 过滤衍生品
        filtered_result = {}
        derivative_count = 0
        zero_market_cap_count = 0

        for symbol, data in result.items():
            if self._is_derivative_product(symbol, data):
                derivative_count += 1
                continue

            effective_market_cap = self._get_effective_market_cap(data)
            data['effective_market_cap'] = effective_market_cap

            if effective_market_cap == 0:
                zero_market_cap_count += 1

            filtered_result[symbol] = data

        if derivative_count > 0 or zero_market_cap_count > 0:
            self.logger.info(
                f"📊 快照过滤统计 - 总股票: {len(result)}, "
                f"衍生品过滤: {derivative_count}, "
                f"零市值: {zero_market_cap_count}, "
                f"剩余正股: {len(filtered_result)}"
            )

        return filtered_result

    def _safe_float(self, row: pd.Series, field: str) -> float:
        try:
            return float(row.get(field, 0) or 0)
        except Exception:
            return 0.0

    def _safe_int(self, row: pd.Series, field: str) -> int:
        try:
            return int(row.get(field, 0) or 0)
        except Exception:
            return 0

    @performance_monitor("futu_get_stock_basicinfo")
    @handle_futu_errors
    def get_stock_basicinfo(self, market, code_list=None):
        """获取股票基本信息 - 增强版本，过滤衍生品"""
        if not self.connected or not self.quote_context:
            self.logger.warning("行情上下文不可用，无法获取股票基本信息")
            return RET_ERROR, "Broker not connected"

        try:
            self._check_rate_limit()
            market_map = {
                "HK": "HK",
                "US": "US",
                "CN": "SH"
            }
            futu_market = market_map.get(market.upper(), "HK")

            ret, data = self.quote_context.get_stock_basicinfo(market=futu_market)

            if ret != RET_OK:
                self.logger.warning(f"get_stock_basicinfo 返回错误: {data}")
                return ret, data

            if isinstance(data, pd.DataFrame):
                # 过滤衍生品
                original_count = len(data)

                if 'code' in data.columns:
                    mask = ~data['code'].astype(str).str.startswith(tuple(self._derivative_prefixes))
                    valid_stocks = data[mask]
                else:
                    valid_stocks = data

                if 'stock_type' in valid_stocks.columns:
                    stock_types_to_keep = ['STOCK', 'EQUITY', 'COMMON']
                    valid_stocks = valid_stocks[
                        valid_stocks['stock_type'].isin(stock_types_to_keep) |
                        valid_stocks['stock_type'].isna()
                    ]

                filtered_count = len(valid_stocks)
                if filtered_count < original_count:
                    self.logger.info(
                        f"✅ 股票基本信息过滤 - 原始: {original_count}, "
                        f"过滤后: {filtered_count}, "
                        f"移除衍生品: {original_count - filtered_count}"
                    )

                return RET_OK, valid_stocks
            else:
                self.logger.warning(f"返回数据不是DataFrame: {type(data)}")
                return RET_ERROR, "Unexpected data format"

        except Exception as e:
            self.logger.error(f"获取股票基本信息异常: {e}")
            return RET_ERROR, str(e)

    @performance_monitor("futu_get_stock_pool")
    @handle_futu_errors
    def get_stock_pool(self, market: str = "HK") -> List[str]:
        """
        专门用于选股策略的股票池获取方法
        只返回适合技术分析的正股
        """
        try:
            ret, data = self.get_stock_basicinfo(market)
            if ret != RET_OK:
                self.logger.error("获取股票基本信息失败")
                return []

            if isinstance(data, pd.DataFrame) and not data.empty:
                stock_codes = []
                for _, row in data.iterrows():
                    code = str(row.get('code', '')).strip()
                    if code and not code.startswith(tuple(self._derivative_prefixes)):
                        stock_code = f"{market}.{code}" if '.' not in code else code
                        stock_codes.append(stock_code)

                self.logger.info(f"🎯 获取正股股票池: {len(stock_codes)} 只股票")
                return stock_codes
            else:
                self.logger.warning("股票基本信息为空")
                return []

        except Exception as e:
            self.logger.error(f"获取股票池异常: {e}")
            return []

    @performance_monitor("futu_get_history_kline")
    @handle_futu_errors
    def get_history_kline(self, symbol: str, start_date: str = None, end_date: str = None, ktype: str = "K_DAY", max_count: int = 1000) -> Optional[pd.DataFrame]:
        """
        获取历史K线数据 - 增强版，处理额度不足和频率限制
        """
        ktype_map = {
            "K_DAY": KLType.K_DAY if 'KLType' in globals() else None,
            "K_1M": KLType.K_1M if 'KLType' in globals() else None,
            "K_5M": KLType.K_5M if 'KLType' in globals() else None,
            "K_15M": KLType.K_15M if 'KLType' in globals() else None,
            "K_60M": KLType.K_60M if 'KLType' in globals() else None,
            "K_WEEK": KLType.K_WEEK if 'KLType' in globals() else None,
            "K_MON": KLType.K_MON if 'KLType' in globals() else None
        }
        futu_ktype = ktype_map.get(ktype, KLType.K_DAY if 'KLType' in globals() else None)
        if not self.quote_context:
            self.logger.warning("请求历史K线但 quote_context 不可用")
            return None
        
        # 检查速率限制
        self._check_rate_limit()
        
        try:
            ret, data, page_key = self.quote_context.request_history_kline(symbol, start=start_date, end=end_date, ktype=futu_ktype, max_count=max_count)
            
            if ret == RET_OK:
                return data
            else:
                error_msg = str(data) if data else "未知错误"
                
                # 处理历史K线额度不足
                if "额度不足" in error_msg or "额度会滚动释放" in error_msg:
                    self.logger.warning(f"⚠️ 历史K线额度不足: {symbol} - {error_msg}")
                    # 返回None，让调用方处理（可以使用缓存或其他数据源）
                    return None
                
                # 处理频率限制
                if "频率太高" in error_msg or "每30秒最多60次" in error_msg:
                    self.logger.warning(f"⚠️ API频率限制: {symbol} - {error_msg}")
                    # 等待一段时间后重试（但这里不重试，让调用方决定）
                    # 避免无限重试导致更多问题
                    return None
                
                # 其他错误
                self.logger.debug(f"request_history_kline 返回错误: {symbol} - {error_msg}")
                return None
                
        except Exception as e:
            error_msg = str(e)
            
            # 检查是否是额度或频率相关错误
            if "额度" in error_msg or "频率" in error_msg:
                self.logger.warning(f"⚠️ 历史K线请求异常: {symbol} - {error_msg}")
            else:
                self.logger.error(f"请求历史K线异常: {symbol} - {error_msg}")
            
            return None

    @performance_monitor("futu_place_order")
    @handle_futu_errors
    def place_order(self, symbol: str, quantity: int, price: float, side: str, order_type: str = "MARKET", remark: str = "") -> bool:
        if quantity <= 0:
            raise OrderExecutionError("数量必须大于0")
        if order_type.upper() == 'LIMIT' and price <= 0:
            raise OrderExecutionError("限价单需要提供价格")
        side_upper = side.upper()
        if side_upper == 'BUY':
            trd_side = TrdSide.BUY if 'TrdSide' in globals() else None
        elif side_upper == 'SELL':
            trd_side = TrdSide.SELL if 'TrdSide' in globals() else None
        else:
            raise OrderExecutionError("无效交易方向")
        if order_type.upper() == 'MARKET':
            order_type_enum = OrderType.MARKET if 'OrderType' in globals() else None
            price_arg = 0
        else:
            order_type_enum = OrderType.NORMAL if 'OrderType' in globals() else None
            price_arg = price
        try:
            self._check_rate_limit()
            ret, data = self.trade_context.place_order(price=price_arg, qty=quantity, code=symbol, trd_side=trd_side, trd_env=self.trading_environment, order_type=order_type_enum, remark=remark)
            if ret == RET_OK:
                event_bus.publish(Event(event_type=EventType.ORDER_PLACED, data={'symbol': symbol, 'quantity': quantity, 'price': price, 'side': side, 'timestamp': datetime.now()}))
                return True
            raise OrderExecutionError(f"下单失败: {data}")
        except Exception as e:
            self.logger.error(f"下单异常: {e}")
            raise

    @performance_monitor("futu_subscribe")
    @handle_futu_errors
    def subscribe(self, symbols: List[str], subtypes: List[str]) -> bool:
        if not symbols:
            return False
        subtype_map = {
            "QUOTE": SubType.QUOTE if 'SubType' in globals() else None,
            "K_1M": SubType.K_1M if 'SubType' in globals() else None,
            "K_5M": SubType.K_5M if 'SubType' in globals() else None,
            "K_15M": SubType.K_15M if 'SubType' in globals() else None,
            "K_DAY": SubType.K_DAY if 'SubType' in globals() else None,
            "BROKER": SubType.BROKER if 'SubType' in globals() else None,
        }
        enums = [subtype_map.get(s.upper()) for s in subtypes if subtype_map.get(s.upper()) is not None]
        if not enums:
            self.logger.warning("无效订阅类型")
            return False
        try:
            self._check_rate_limit()
            ret, data = self.quote_context.subscribe(symbols, enums)
            return ret == RET_OK
        except Exception as e:
            self.logger.error(f"订阅异常: {e}")
            return False

    def set_quote_handler(self, handler):
        self.quote_handler = handler
        if self.quote_context and handler:
            try:
                self.quote_context.set_handler(handler)
            except Exception:
                pass

    def set_trade_handler(self, handler):
        self.trade_handler = handler
        if self.trade_context and handler:
            try:
                self.trade_context.set_handler(handler)
            except Exception:
                pass

    def health_check(self) -> Dict[str, Any]:
        status = {'connected': self.connected, 'operation_count': self._operation_count}
        if self._connection_time:
            status['connection_time'] = self._connection_time.isoformat()
            status['uptime_seconds'] = (datetime.now() - self._connection_time).total_seconds()
        try:
            if self.connected and self.quote_context:
                ret, state = self.quote_context.get_global_state()
                status['quote_connected'] = (ret == RET_OK)
        except Exception as e:
            status['quote_connected'] = False
            status['quote_error'] = str(e)
        return status

    def get_performance_stats(self) -> Dict[str, Any]:
        return {'connected': self.connected, 'operation_count': self._operation_count, 'connection_time': self._connection_time}

    def __del__(self):
        try:
            if self.connected:
                self.disconnect()
        except Exception:
            pass


__all__ = ['FutuBroker']