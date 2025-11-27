# quant_system/domain/strategies/selection_mixed.py
"""
混合策略模块 - Mixed Selection Strategy

功能概述：
    结合多种选股策略的优点，通过权重组合生成综合选股结果。
    提高选股的稳定性和多样性。

本文件的调整要点：
- __init__ 签名与其它策略保持一致：name, config, broker, stock_pool_manager, strategy_config
- 子策略实例化放到单独方法并做容错（实例化失败不影响主策略初始化）
- 保持原有评分与合并逻辑不变
"""

from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

from .base import SelectionStrategy, StrategyConfig
from .selection_technical import TechnicalSelectionStrategy
from .selection_priority import PriorityStocksStrategy


class MixedStrategy(SelectionStrategy):
    """
    混合选股策略

    结合技术分析和自选股策略，通过权重组合生成综合选股结果。
    """

    def __init__(self,
                 name: str = "mixed_strategy",
                 config: Optional[Any] = None,
                 broker: Optional[Any] = None,
                 stock_pool_manager: Optional[Any] = None,
                 strategy_config: Optional[StrategyConfig] = None):
        """
        初始化混合策略
        Args:
            name: 策略名称
            config: 系统/全局配置
            broker: 券商接口
            stock_pool_manager: 股票池管理器（可选）
            strategy_config: 策略特定配置（可选）
        """
        if strategy_config is None:
            strategy_config = StrategyConfig(enabled=True)

        super().__init__(name, strategy_config, broker, stock_pool_manager)

        # 统一命名
        self.name = name
        self.config = config
        self.broker = broker
        self.stock_pool_manager = stock_pool_manager
        self.strategy_config = strategy_config

        self.description = "混合选股策略 - 结合技术和自选股策略"
        self.logger = logging.getLogger(__name__)

        # 最低共识分数（保持原有默认）
        self.min_consensus_score = getattr(self.strategy_config, 'min_consensus_score', 70)

        # 子策略元配置（仅存元数据，实例化在 _init_sub_strategies）
        self._sub_strategy_defs = {
            'technical': {
                'class': TechnicalSelectionStrategy,
                'name': 'technical_analysis',
                'weight': 0.6
            },
            'priority': {
                'class': PriorityStocksStrategy,
                'name': 'priority_stocks',
                'weight': 0.4
            }
        }

        # 实际子策略实例（可能含部分 None，当实例化失败时保留 None）
        self.sub_strategies: Dict[str, Dict[str, Any]] = {}

        # 延迟并容错地初始化子策略实例
        self._init_sub_strategies()

        self.logger.info("✅ MixedStrategy 初始化完成")

    def _init_sub_strategies(self):
        """
        初始化子策略实例（容错，不抛出异常）
        """
        for key, defn in self._sub_strategy_defs.items():
            cls = defn.get('class')
            strat_name = defn.get('name')
            weight = defn.get('weight', 1.0)
            try:
                # 采用兼容的关键字参数实例化（各子策略已按之前调整支持 name, config, broker, stock_pool_manager）
                instance = cls(name=strat_name, config=self.config, broker=self.broker, stock_pool_manager=self.stock_pool_manager)
                self.sub_strategies[key] = {
                    'strategy': instance,
                    'weight': weight
                }
                self.logger.debug(f"子策略实例化成功: {key} -> {cls.__name__}")
            except Exception as e:
                # 记录但不抛出，允许部分子策略不可用
                self.logger.error(f"子策略 {key} ({cls.__name__}) 实例化失败: {e}")
                self.sub_strategies[key] = {
                    'strategy': None,
                    'weight': weight
                }

    def select_stocks(self, stock_universe: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        执行混合策略选股
        Args:
            stock_universe: 股票池（可选）
        Returns:
            List[Dict[str, Any]]: 选股结果列表
        """
        self.logger.info("🎯 开始执行混合策略选股")

        try:
            all_strategy_results: Dict[str, Dict[str, Any]] = {}

            # 运行每个可用子策略
            for strategy_key, cfg in self.sub_strategies.items():
                strat = cfg.get('strategy')
                weight = cfg.get('weight', 1.0)

                if strat is None:
                    self.logger.warning(f"跳过子策略 {strategy_key}（实例不可用）")
                    continue

                try:
                    self.logger.info(f"运行子策略: {strategy_key}")
                    # 将 stock_universe 直接传给子策略（子策略自行决定如何使用）
                    strategy_results = strat.select_stocks(stock_universe)

                    if not strategy_results:
                        self.logger.warning(f"子策略 {strategy_key} 返回空结果")
                        continue

                    for stock in strategy_results:
                        symbol = stock.get('symbol')
                        if not symbol:
                            continue
                        if symbol not in all_strategy_results:
                            all_strategy_results[symbol] = {
                                'symbol': symbol,
                                'scores': {},
                                'details': stock
                            }
                        # 记录该子策略对该股票的评分与权重
                        all_strategy_results[symbol]['scores'][strategy_key] = {
                            'score': stock.get('score', 0),
                            'weight': weight
                        }

                    self.logger.info(f"✅ 子策略 {strategy_key} 完成: {len(strategy_results)} 只股票")

                except Exception as e:
                    self.logger.error(f"❌ 子策略 {strategy_key} 执行失败: {e}")
                    self.logger.debug("子策略异常堆栈：", exc_info=True)
                    continue

            if not all_strategy_results:
                self.logger.warning("⚠️ 所有子策略均未产出可用结果，返回空")
                return []

            # 计算综合评分并返回最终列表
            final_stocks = self._calculate_composite_scores(all_strategy_results)
            final_stocks.sort(key=lambda x: x['composite_score'], reverse=True)

            self.logger.info(f"✅ 混合策略完成: 分析 {len(all_strategy_results)} 支股票, 选中 {len(final_stocks)} 支")
            return final_stocks

        except Exception as e:
            self.logger.error(f"❌ 混合策略执行失败: {e}")
            self.logger.debug("执行异常堆栈：", exc_info=True)
            return []

    def _calculate_composite_scores(self, strategy_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """计算综合评分（保持原逻辑）"""
        composite_stocks = []

        for symbol, stock_data in strategy_results.items():
            try:
                scores = stock_data.get('scores', {})
                details = stock_data.get('details', {})

                total_weight = 0.0
                weighted_score = 0.0
                for strategy_name, score_info in scores.items():
                    weight = float(score_info.get('weight', 1.0))
                    score = float(score_info.get('score', 0.0))
                    weighted_score += score * weight
                    total_weight += weight

                composite_score = (weighted_score / total_weight) if total_weight > 0 else 0.0

                if composite_score >= float(self.min_consensus_score):
                    composite_stocks.append({
                        'symbol': symbol,
                        'name': details.get('name', symbol),
                        'composite_score': composite_score,
                        'strategy_scores': scores,
                        'current_price': details.get('current_price', 0),
                        'change_rate': details.get('change_rate', 0),
                        'reason': self._generate_composite_reason(scores, composite_score),
                        'timestamp': datetime.now().isoformat(),
                        'strategy': self.name
                    })

            except Exception as e:
                self.logger.error(f"计算综合评分失败 {symbol}: {e}")
                self.logger.debug("计算异常堆栈：", exc_info=True)
                continue

        return composite_stocks

    def _generate_composite_reason(self, strategy_scores: Dict[str, Any], composite_score: float) -> str:
        """生成综合选股理由（保持原逻辑）"""
        reasons = []
        for strategy_name, score_info in strategy_scores.items():
            score = float(score_info.get('score', 0))
            if score > 70:
                strategy_display = {
                    'technical': '技术分析',
                    'priority': '自选股'
                }.get(strategy_name, strategy_name)
                reasons.append(f"{strategy_display}评分{score:.1f}")

        if not reasons:
            reasons.append(f"综合评分{composite_score:.1f}")

        return " + ".join(reasons)

    def get_strategy_info(self) -> Dict[str, Any]:
        """获取策略信息（子策略信息包含是否实例化）"""
        sub_strategy_info = {}
        for name, config in self.sub_strategies.items():
            strat = config.get('strategy')
            sub_strategy_info[name] = {
                'weight': config.get('weight', 1.0),
                'description': getattr(strat, 'description', None) if strat else None,
                'instantiated': strat is not None
            }

        return {
            'name': self.name,
            'description': self.description,
            'sub_strategies': sub_strategy_info,
            'min_consensus_score': self.min_consensus_score
        }


__all__ = ['MixedStrategy']
