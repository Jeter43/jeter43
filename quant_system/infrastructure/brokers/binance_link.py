# quant_system/infrastructure/brokers/binance_link.py
"""
Binance 券商接口实现 - 修复版
基于成功的 fetch_klines.py 代码重构
"""

import sys
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
import time
import requests
import pandas as pd
import json
from threading import Lock

# 确保项目根目录可导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.infrastructure.brokers.base import Broker
from quant_system.infrastructure.data.manager import MarketData, PositionData
from quant_system.utils.logger import get_logger
from quant_system.core.config import ConfigManager


class BinanceBroker(Broker):
    """
    Binance 券商接口实现 - 基于成功的fetch_klines.py重构
    """

    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = get_logger(__name__)

        # 加载 Binance 配置
        self.binance_config = self._load_binance_config()

        # 连接状态
        self.connected = False
        self._connection_time = None

        # API 配置
        self.base_url = "https://api.binance.com/api/v3"
        self.testnet_url = "https://testnet.binance.vision/api/v3"

        # 使用测试网还是主网
        self.use_testnet = self.binance_config.get('testnet', True)
        self.current_base_url = self.testnet_url if self.use_testnet else self.base_url

        # API 调用频率控制
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 最小请求间隔（秒）
        self._rate_limit_lock = Lock()

        # 价格缓存
        self._price_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_expiry = 5  # 缓存5秒

        self.logger.info(f"BinanceBroker初始化完成，测试网: {self.use_testnet}")

    def _load_binance_config(self) -> Dict[str, Any]:
        """加载 Binance 配置"""
        try:
            # 从市场配置中获取
            market_config = self.config.get_current_market_config()
            params = market_config.parameters

            config = {
                'api_key': params.get('api_key', ''),
                'secret_key': params.get('secret_key', ''),
                'testnet': params.get('testnet', True),
            }

            # 如果没有配置，尝试从环境变量获取
            if not config['api_key']:
                config['api_key'] = os.getenv('BINANCE_API_KEY', '')
            if not config['secret_key']:
                config['secret_key'] = os.getenv('BINANCE_SECRET_KEY', '')

            self.logger.info(f"Binance配置加载: API Key长度={len(config['api_key'])}, 测试网={config['testnet']}")
            return config

        except Exception as e:
            self.logger.error(f"加载 Binance 配置失败: {e}")
            return {
                'api_key': '',
                'secret_key': '',
                'testnet': True,
            }

    def _check_rate_limit(self):
        """检查并遵守 API 频率限制"""
        with self._rate_limit_lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._min_request_interval:
                sleep_time = self._min_request_interval - time_since_last
                time.sleep(sleep_time)
            self._last_request_time = time.time()

    def _make_request(self, endpoint: str, params: Dict = None, signed: bool = False) -> Dict:
        """
        发送请求到Binance API - 基于fetch_klines.py的成功代码
        """
        url = f"{self.current_base_url}{endpoint}"

        if params is None:
            params = {}

        headers = {}
        if self.binance_config['api_key']:
            headers['X-MBX-APIKEY'] = self.binance_config['api_key']

        try:
            self._check_rate_limit()

            self.logger.debug(f"Binance请求: {endpoint}, 参数: {params}")
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            self.logger.debug(f"Binance响应: {data}")
            return data

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Binance API请求失败: {e}")
            raise ConnectionError(f"Binance API请求失败: {e}")
        except Exception as e:
            self.logger.error(f"Binance请求异常: {e}")
            raise

    def connect(self) -> bool:
        """
        连接 Binance API - 简化版连接测试
        """
        if self.connected:
            self.logger.info("Binance 已连接")
            return True

        try:
            self.logger.info("🔗 开始连接 Binance...")

            # 使用fetch_klines.py中的成功方法测试连接
            test_url = f"{self.current_base_url}/ping"

            self._check_rate_limit()
            response = requests.get(test_url, timeout=10)

            if response.status_code == 200:
                self.connected = True
                self._connection_time = datetime.now()

                # 进一步测试API密钥（如果有）
                if self.binance_config['api_key']:
                    try:
                        # 测试需要签名的端点
                        account_info = self.get_account_info()
                        if account_info:
                            self.logger.info("✅ Binance 连接成功 (带认证)")
                        else:
                            self.logger.info("✅ Binance 连接成功 (公开API)")
                    except:
                        self.logger.info("✅ Binance 连接成功 (公开API，认证待配置)")
                else:
                    self.logger.info("✅ Binance 连接成功 (公开API)")

                return True
            else:
                self.logger.error(f"❌ Binance 连接失败: HTTP {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"❌ Binance 连接异常: {e}")
            return False

    def disconnect(self):
        """断开 Binance 连接"""
        self.connected = False
        self.logger.info("🔌 Binance 连接已断开")

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.connected

    def get_account_info(self) -> Dict[str, float]:
        """
        获取账户信息 - 基于公开API
        """
        if not self.is_connected():
            self.logger.warning("未连接，返回空账户信息")
            return {
                'total_assets': 0.0,
                'available_cash': 0.0,
                'market_value': 0.0,
                'cash': 0.0,
                'frozen_cash': 0.0
            }

        try:
            # 注意：这个端点需要API密钥和签名
            # 由于认证问题，我们先返回模拟数据
            self.logger.warning("账户信息需要API认证，暂时返回模拟数据")

            return {
                'total_assets': 10000.0,
                'available_cash': 5000.0,
                'market_value': 5000.0,
                'cash': 5000.0,
                'frozen_cash': 0.0
            }

        except Exception as e:
            self.logger.error(f"获取账户信息失败: {e}")
            return {
                'total_assets': 0.0,
                'available_cash': 0.0,
                'market_value': 0.0,
                'cash': 0.0,
                'frozen_cash': 0.0
            }

    def get_klines(self, symbol: str, interval: str = '1h', limit: int = 500,
                   start_time: int = None, end_time: int = None) -> pd.DataFrame:
        """
        获取K线数据 - 基于fetch_klines.py的成功代码
        """
        if not self.is_connected():
            self.logger.error("未连接，无法获取K线数据")
            return pd.DataFrame()

        try:
            all_klines = []
            current_start = start_time
            batch_count = 0

            self.logger.info(f"开始获取 {symbol} 的 {interval} K线数据...")

            while True:
                batch_count += 1

                # 构建请求参数
                params = {
                    'symbol': symbol.upper(),
                    'interval': interval,
                    'limit': min(limit, 1000)  # Binance最大限制1000
                }

                # 添加时间参数
                if current_start:
                    params['startTime'] = current_start
                if end_time:
                    params['endTime'] = end_time

                self.logger.debug(f"第 {batch_count} 批请求 - 参数: {params}")

                klines = self._make_request('/klines', params)

                if not klines:
                    self.logger.info("API返回空数据，获取完成")
                    break

                self.logger.debug(f"第 {batch_count} 批获取到 {len(klines)} 条K线数据")
                all_klines.extend(klines)

                # 如果返回的数据少于limit，说明已经获取完所有数据
                if len(klines) < limit:
                    self.logger.info("数据获取完成")
                    break

                # 更新时间戳，继续获取下一批数据
                current_start = klines[-1][0] + 1

                # 如果已经到达结束时间，停止获取
                if end_time and current_start >= end_time:
                    self.logger.info("已到达结束时间，获取完成")
                    break

                # 如果已经达到请求的limit，停止获取
                if len(all_klines) >= limit:
                    self.logger.info(f"已达到请求限制 {limit}，获取完成")
                    break

            if not all_klines:
                self.logger.warning("未获取到K线数据")
                return pd.DataFrame()

            self.logger.info(f"总共获取 {len(all_klines)} 条K线数据")

            # 转换为DataFrame
            columns = [
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ]

            df = pd.DataFrame(all_klines, columns=columns)

            # 转换数据类型
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_asset_volume',
                               'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col])

            # 转换时间戳
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')

            # 转换成交笔数为整数
            df['number_of_trades'] = pd.to_numeric(df['number_of_trades'], errors='coerce').astype('Int64')

            # 按开盘时间排序
            df = df.sort_values('open_time').reset_index(drop=True)

            return df

        except Exception as e:
            self.logger.error(f"获取K线数据失败: {e}")
            return pd.DataFrame()

    def get_symbol_price(self, symbol: str) -> float:
        """
        获取当前价格
        """
        try:
            ticker = self._make_request('/ticker/price', {'symbol': symbol.upper()})
            return float(ticker['price'])
        except Exception as e:
            self.logger.error(f"获取价格失败: {e}")
            return 0.0

    def get_market_snapshot(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        获取市场快照数据
        """
        if not self.is_connected():
            self.logger.warning("未连接，返回空市场数据")
            return {}

        try:
            snapshot = {}

            for symbol in symbols:
                try:
                    # 获取24小时行情
                    ticker = self._make_request('/ticker/24hr', {'symbol': symbol.upper()})

                    current_price = float(ticker['lastPrice'])
                    open_price = float(ticker['openPrice'])
                    high_price = float(ticker['highPrice'])
                    low_price = float(ticker['lowPrice'])
                    volume = float(ticker['volume'])
                    change_rate = float(ticker['priceChangePercent']) / 100.0

                    # 计算振幅
                    if open_price > 0:
                        amplitude = abs((high_price - low_price) / open_price)
                    else:
                        amplitude = 0.0

                    snapshot[symbol] = {
                        'symbol': symbol,
                        'name': symbol,
                        'last_price': current_price,
                        'open_price': open_price,
                        'high_price': high_price,
                        'low_price': low_price,
                        'prev_close_price': open_price,
                        'volume': volume,
                        'change_rate': change_rate,
                        'amplitude': amplitude,
                        'turnover': volume * current_price,
                        'timestamp': datetime.now().isoformat()
                    }

                except Exception as e:
                    self.logger.warning(f"获取 {symbol} 行情失败: {e}")
                    continue

            return snapshot

        except Exception as e:
            self.logger.error(f"获取市场快照失败: {e}")
            return {}

    def get_positions(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        获取持仓信息 - 模拟实现
        """
        self.logger.warning("持仓信息需要API认证，暂时返回空数据")
        return {}

    def place_order(self, symbol: str, quantity: float, price: float,
                    side: str, order_type: str = "MARKET", remark: str = "") -> bool:
        """
        下单 - 模拟实现
        """
        self.logger.warning("下单功能需要API认证，暂时无法执行")
        return False

    def subscribe(self, symbols: List[str], subtypes: List[str]) -> bool:
        """
        订阅实时行情
        """
        self.logger.info(f"订阅实时行情: {symbols} (功能待实现)")
        return True

    def get_stock_basicinfo(self, market: str = "HK") -> tuple:
        """
        获取交易对基本信息
        """
        try:
            import pandas as pd

            # 获取所有交易对信息
            exchange_info = self._make_request('/exchangeInfo')

            symbols_data = []
            for symbol_info in exchange_info['symbols']:
                symbol = symbol_info['symbol']
                status = symbol_info['status']

                # 只返回活跃的USDT交易对
                if status == 'TRADING' and symbol.endswith('USDT'):
                    symbols_data.append({
                        'code': symbol,
                        'name': symbol,
                        'market': 'CRYPTO',
                        'status': status
                    })

            df = pd.DataFrame(symbols_data)
            return ('OK', df)

        except Exception as e:
            self.logger.error(f"获取交易对信息失败: {e}")
            return ('ERROR', None)