# quant_system/domain/strategies/selection_priority.py
"""
自选股策略模块 - Priority Stocks Selection Strategy（兼容 StrategyFactory，优先使用 broker）
调整要点：
- 统一 __init__ 签名（name, config, broker, stock_pool_manager），兼容 StrategyFactory 的实例化方式
- 优先使用 broker / stock_pool_manager；只有当 config.allow_mock_market_data=True 时才使用回退池
- 统一 self.config 与 self.strategy_config，增强健壮性与日志级别调整
"""

from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from .base import SelectionStrategy, StrategyConfig
# 若项目中确实有这些模块，保留；否则期望外部注入兼容 broker/stock_pool_manager
# from quant_system.infrastructure.brokers.base import Broker
# from quant_system.core.config import ConfigManager


class PriorityStocksStrategy(SelectionStrategy):
    """
    自选股策略 - 基于用户自选池 + 技术与基本面评分
    """

    def __init__(self,
                 name: str = "priority_stocks",
                 config: Optional[Any] = None,
                 broker: Optional[Any] = None,
                 stock_pool_manager: Optional[Any] = None,
                 strategy_config: Optional[StrategyConfig] = None):
        """
        初始化自选股策略
        注意：顺序与 StrategyFactory 中对选股策略的实例化约定一致
        Args:
            name: 策略名称
            config: 系统/全局配置（保存为 self.config）
            broker: 券商接口（必须优先使用）
            stock_pool_manager: 外部股票池管理器（可选）
            strategy_config: 策略特定配置（可选）
        """
        # 标准化策略配置
        if strategy_config is None:
            strategy_config = StrategyConfig(enabled=True)

        # 调用基类构造（保持基类初始化行为）
        super().__init__(name, strategy_config, broker, stock_pool_manager)

        self.name = name
        self.config = config
        self.broker = broker
        self.stock_pool_manager = stock_pool_manager
        self.strategy_config = strategy_config

        self.logger = logging.getLogger(__name__)

        # 策略参数（保持原有默认值）
        self.min_volume = int(getattr(self.strategy_config, 'min_volume', 1_000_000))
        self.min_price = float(getattr(self.strategy_config, 'min_price', 1.0))
        self.max_price = float(getattr(self.strategy_config, 'max_price', 1000.0))

        # 默认股票池 id（若 stock_pool_manager 可用会使用）
        self.default_stock_pool = getattr(self.strategy_config, 'default_stock_pool', 'hk_main')

        self.logger.info(f"PriorityStocksStrategy 初始化: name={self.name}, default_pool={self.default_stock_pool}")

    def select_stocks(self, stock_universe: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        执行自选股策略选股
        优先使用传入的 stock_universe -> stock_pool_manager -> broker 提供的自选池
        仅在 config.allow_mock_market_data=True 时才使用硬编码回退池
        """
        self.logger.info("🎯 开始执行自选股策略选股")

        try:
            # 强烈优先使用 broker 与 stock_pool_manager
            if not self.broker:
                self.logger.error("❌ Broker 不可用，无法获取市场数据，若确实要在无 broker 下运行，请设置 config.allow_mock_market_data=True")
                # 如果允许 mock，则使用回退池并生成模拟数据；否则返回空
                if bool(self.config and getattr(self.config, 'allow_mock_market_data', False)):
                    self.logger.warning("config.allow_mock_market_data=True，使用回退池进行测试")
                    target_stocks = self._get_fallback_stocks()
                else:
                    return []
            else:
                # 获取股票池优先级：传入 > 股票池管理器 > broker（如果 broker 提供自选列表接口）
                if stock_universe:
                    target_stocks = stock_universe
                    self.logger.info(f"使用传入股票列表: {len(target_stocks)} 只")
                elif self.stock_pool_manager:
                    try:
                        # 尝试从股票池管理器获取
                        pool = self.stock_pool_manager.get_stock_pool(self.default_stock_pool)
                        target_stocks = pool if pool else []
                        self.logger.info(f"使用股票池管理器池 '{self.default_stock_pool}': {len(target_stocks)} 只")
                    except Exception as e:
                        self.logger.warning(f"获取股票池失败: {e}")
                        target_stocks = []
                else:
                    # 如果没有 stock_pool_manager，部分 broker 提供基础信息接口，可尝试从 broker 获取自选/关注列表（若实现）
                    # 这里保持兼容，先尝试使用 broker 的 get_watchlist / get_stock_basicinfo 等（若实现）
                    try:
                        if hasattr(self.broker, 'get_watchlist'):
                            target_stocks = self.broker.get_watchlist()
                            self.logger.info(f"从 broker.get_watchlist 获取 股票池: {len(target_stocks)} 只")
                        else:
                            # 如果 broker 无此接口，则默认空，让后面根据 config 决定是否 fallback
                            target_stocks = []
                    except Exception as e:
                        self.logger.warning(f"broker 获取自选池失败: {e}")
                        target_stocks = []

                    if not target_stocks and bool(self.config and getattr(self.config, 'allow_mock_market_data', False)):
                        self.logger.warning("未能从 stock_pool_manager 或 broker 获取池，使用回退池（config 允许）")
                        target_stocks = self._get_fallback_stocks()

            if not target_stocks:
                self.logger.warning("⚠️ 最终目标股票池为空，返回空结果")
                return []

            # 获取市场数据（必须用 broker 获取 snapshot）
            if not self.broker or not hasattr(self.broker, 'get_market_snapshot'):
                self.logger.error("❌ Broker 不支持 get_market_snapshot 或不可用")
                if bool(self.config and getattr(self.config, 'allow_mock_market_data', False)):
                    self.logger.warning("使用回退的模拟市场数据（config.allow_mock_market_data=True）")
                    market_data = self._generate_mock_market_data(target_stocks)
                else:
                    return []
            else:
                market_data = self.broker.get_market_snapshot(target_stocks)
                if not market_data:
                    self.logger.error("❌ broker.get_market_snapshot 返回空或 None")
                    if bool(self.config and getattr(self.config, 'allow_mock_market_data', False)):
                        self.logger.warning("使用回退的模拟市场数据（config.allow_mock_market_data=True）")
                        market_data = self._generate_mock_market_data(target_stocks)
                    else:
                        return []

            selected_stocks: List[Dict[str, Any]] = []
            successful_analysis = 0

            for symbol in target_stocks:
                try:
                    if symbol not in market_data:
                        self.logger.debug(f"跳过 {symbol} - 无市场数据")
                        continue

                    stock_info = market_data[symbol]

                    # 基础数据验证
                    if not self._validate_stock_data(stock_info):
                        continue

                    tech_score = self._technical_analysis(symbol, stock_info)
                    fundamental_score = self._fundamental_analysis(symbol, stock_info)
                    total_score = tech_score * 0.6 + fundamental_score * 0.4
                    risk_adjusted_score = self._risk_adjustment(total_score, stock_info)

                    if risk_adjusted_score >= 60:
                        selected_stocks.append({
                            'symbol': symbol,
                            'name': stock_info.get('name', symbol),
                            'score': risk_adjusted_score,
                            'current_price': stock_info.get('last_price', 0),
                            'change_rate': stock_info.get('change_rate', 0),
                            'volume': stock_info.get('volume', 0),
                            'reason': self._generate_selection_reason(tech_score, fundamental_score),
                            'timestamp': datetime.now().isoformat(),
                            'strategy': self.name
                        })
                        successful_analysis += 1

                except Exception as e:
                    self.logger.error(f"分析股票 {symbol} 失败: {e}")
                    self.logger.debug(e, exc_info=True)
                    continue

            selected_stocks.sort(key=lambda x: x['score'], reverse=True)
            self.logger.info(f"✅ 自选股策略完成: {successful_analysis}/{len(target_stocks)} 分析成功, 选中 {len(selected_stocks)} 只")

            return selected_stocks

        except Exception as e:
            self.logger.error(f"❌ 自选股策略执行失败: {e}")
            self.logger.debug(e, exc_info=True)
            return []

    def _get_fallback_stocks(self) -> List[str]:
        """
        回退股票池（仅在 config.allow_mock_market_data=True 时使用）
        """
        return [
            'HK.00700', 'HK.09988', 'HK.03690', 'HK.02318', 'HK.00941',
            'HK.00883', 'HK.00388', 'HK.01299', 'HK.00005', 'HK.01093',
        ]

    def set_stock_pool(self, pool_id: str):
        """
        设置使用的股票池（安全检测）
        """
        if not self.stock_pool_manager:
            self.logger.warning("stock_pool_manager 未设置，无法设置池")
            return

        try:
            pool = self.stock_pool_manager.get_stock_pool(pool_id)
            if pool:
                self.default_stock_pool = pool_id
                self.logger.info(f"✅ 设置股票池为: {pool_id}")
            else:
                self.logger.warning(f"⚠️ 股票池不存在或为空: {pool_id}")
        except Exception as e:
            self.logger.warning(f"设置股票池失败: {e}")

    def get_available_stock_pools(self) -> Dict[str, Any]:
        if self.stock_pool_manager:
            try:
                return self.stock_pool_manager.list_available_pools()
            except Exception as e:
                self.logger.warning(f"获取可用股票池失败: {e}")
                return {}
        else:
            return {'default': {'name': '默认股票池', 'stock_count': len(self._get_fallback_stocks())}}

    def _validate_stock_data(self, stock_info: Dict[str, Any]) -> bool:
        try:
            price = stock_info.get('last_price', 0)
            volume = stock_info.get('volume', 0)

            if price <= 0 or price < self.min_price or price > self.max_price:
                return False
            if volume < self.min_volume:
                return False
            if stock_info.get('trade_status') == 'SUSPENDED':
                return False
            return True
        except Exception as e:
            self.logger.debug(f"股票数据验证失败: {e}")
            return False

    def _technical_analysis(self, symbol: str, stock_info: Dict[str, Any]) -> float:
        try:
            score = 50.0
            change_rate = abs(stock_info.get('change_rate', 0))
            if 0 < change_rate <= 5:
                score += 20
            elif change_rate > 10:
                score -= 10

            volume_ratio = stock_info.get('volume_ratio', 1)
            if volume_ratio > 1.2:
                score += 15
            elif volume_ratio < 0.8:
                score -= 10

            return max(0, min(100, score))
        except Exception as e:
            self.logger.debug(f"技术分析失败 {symbol}: {e}")
            return 50.0

    def _fundamental_analysis(self, symbol: str, stock_info: Dict[str, Any]) -> float:
        try:
            score = 50.0
            market_cap = stock_info.get('market_cap', 0)
            if market_cap > 100e9:
                score += 15
            elif market_cap > 10e9:
                score += 10
            else:
                score += 5
            return max(0, min(100, score))
        except Exception as e:
            self.logger.debug(f"基本面分析失败 {symbol}: {e}")
            return 50.0

    def _risk_adjustment(self, base_score: float, stock_info: Dict[str, Any]) -> float:
        try:
            adjusted_score = base_score
            volatility = stock_info.get('amplitude', 0)
            if volatility > 10:
                adjusted_score -= 10
            elif volatility < 2:
                adjusted_score += 5
            return max(0, min(100, adjusted_score))
        except Exception as e:
            self.logger.debug(f"风险调整失败: {e}")
            return base_score

    def _generate_selection_reason(self, tech_score: float, fundamental_score: float) -> str:
        reasons = []
        if tech_score > 60:
            reasons.append("技术面良好")
        if fundamental_score > 60:
            reasons.append("基本面稳健")
        if not reasons:
            reasons.append("综合评分达标")
        return "，".join(reasons)

    def _generate_mock_market_data(self, universe: List[str]) -> Dict[str, Any]:
        """
        简单模拟市场数据，仅用于测试（config.allow_mock_market_data=True）
        """
        import random
        mock = {}
        for sym in universe:
            base = random.uniform(10, 100)
            mock[sym] = {
                'last_price': base,
                'volume': random.randint(1_000_000, 50_000_000),
                'market_cap': random.uniform(1e9, 1e11),
                'change_rate': random.uniform(-0.05, 0.05),
                'volume_ratio': random.uniform(0.5, 2.0),
                'amplitude': random.uniform(0.5, 12),
                'name': sym
            }
        return mock

    def get_strategy_info(self) -> Dict[str, Any]:
        stock_pool_info = self.get_available_stock_pools()
        return {
            'name': self.name,
            'description': getattr(self, 'description', '自选股策略'),
            'current_stock_pool': self.default_stock_pool,
            'available_stock_pools': list(stock_pool_info.keys()),
            'parameters': {
                'min_volume': self.min_volume,
                'min_price': self.min_price,
                'max_price': self.max_price
            }
        }


__all__ = ['PriorityStocksStrategy']
