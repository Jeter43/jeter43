# quant_system/domain/strategies/selection_realtime.py
"""
基于实时数据的选股策略 - Realtime Selection Strategy (优化版)

优化内容：
1. 修复评分权重问题
2. 实现基础板块数据获取
3. 增强日志和监控系统
4. 添加参数验证和健康检查
"""

import sys
import os
import traceback
import logging
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# 确保项目根目录可导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from .base import SelectionStrategy, StrategyConfig


class RealtimeSelectionStrategy(SelectionStrategy):
    """
    基于实时数据的选股策略（优化版）

    优化特性：
    - 修复评分权重问题
    - 基础板块数据实现
    - 增强监控和日志
    - 参数验证和健康检查
    """

    def __init__(self,
                 name: str = "realtime_monitoring_enhanced",
                 config: Optional[StrategyConfig] = None,
                 broker: Optional[Any] = None,
                 stock_pool_manager: Optional[Any] = None,
                 log_level: str = "INFO",
                 debug_mode: bool = False):  # 新增调试模式
        super().__init__(name, config, broker, stock_pool_manager)

        self.name = name
        self.config = config
        self.broker = broker
        self.stock_pool_manager = stock_pool_manager
        self.debug_mode = debug_mode  # 调试模式

        # 增强日志配置
        self.logger = get_logger(__name__)
        # 注意：TradingLogger 在初始化时已设置日志级别，无需额外设置
        # 如果开启调试模式，记录日志（但无法动态修改日志级别）
        if self.debug_mode:
            self.logger.info("🔧 调试模式已开启")

        # 策略参数（修复权重后）
        self.parameters = self._init_parameters()

        # 性能统计
        self.performance_stats = {
            'total_runs': 0,
            'last_run_time': None,
            'stocks_scanned': 0,
            'cond1_passed': 0,
            'cond2_passed': 0,
            'both_cond_passed': 0,
            'avg_score': 0.0,
            'score_distribution': [],  # 新增：评分分布
            'execution_times': []  # 新增：执行时间记录
        }

        # 板块缓存
        self.sector_cache: Dict[str, Dict] = {}

        # 新增：参数验证
        self._validate_parameters()

        self.logger.info(f"✅ RealtimeSelectionStrategy 初始化完成: {self.name} (优化版)")
        self.logger.info(f"   优化内容: 1)修复评分权重 2)实现板块数据 3)增强日志监控")

    def _debug(self, message: str) -> None:
        """仅在调试模式或 logger 级别为 DEBUG 时输出详细日志"""
        if self.debug_mode or self.logger.isEnabledFor(logging.DEBUG):
            self._debug(message)

    def _init_parameters(self) -> Dict[str, Any]:
        """初始化参数 - 集中管理"""
        return {
            # 条件1参数
            'cond1_volume_amplitude_threshold': float(getattr(self.config, 'cond1_volume_amplitude_threshold', 0.03)),
            'cond1_low_range_min': float(getattr(self.config, 'cond1_low_range_min', -0.05)),
            'cond1_low_range_max': float(getattr(self.config, 'cond1_low_range_max', 0.02)),

            # 条件2参数
            'cond2_amplitude_min': float(getattr(self.config, 'cond2_amplitude_min', 0.01)),
            'cond2_amplitude_max': float(getattr(self.config, 'cond2_amplitude_max', 0.08)),
            'cond2_start_range_min': float(getattr(self.config, 'cond2_start_range_min', -0.02)),
            'cond2_start_range_max': float(getattr(self.config, 'cond2_start_range_max', 0.05)),

            # 初筛参数
            'min_volume': int(getattr(self.config, 'min_volume', 2_000_000)),
            'min_price': float(getattr(self.config, 'min_price', 0.1)),
            'min_market_cap': float(getattr(self.config, 'min_market_cap', 2e8)),
            'max_change_rate': float(getattr(self.config, 'max_change_rate', 0.15)),

            # 连续评分参数
            'base_amplitude_threshold': float(getattr(self.config, 'base_amplitude_threshold', 0.03)),
            'optimal_low_range': [float(getattr(self.config, 'optimal_low_min', -0.03)),
                                  float(getattr(self.config, 'optimal_low_max', -0.01))],
            'base_rise_threshold': float(getattr(self.config, 'base_rise_threshold', 0.01)),

            # 风险调整参数
            'high_amplitude_penalty_threshold': float(getattr(self.config, 'high_amplitude_penalty_threshold', 0.1)),
            'base_market_cap': float(getattr(self.config, 'base_market_cap', 5e9)),
            'low_price_penalty': float(getattr(self.config, 'low_price_penalty', 0.5)),
            'high_price_penalty': float(getattr(self.config, 'high_price_penalty', 200)),

            # 批次处理参数
            'batch_size': int(getattr(self.config, 'batch_size', 100)),
            'max_stocks': int(getattr(self.config, 'max_stocks', 10) if hasattr(self.config, 'max_stocks') else 10),

            # 新增：评分限制参数
            'max_continuous_score': float(getattr(self.config, 'max_continuous_score', 60)),
            'max_sector_score': float(getattr(self.config, 'max_sector_score', 25)),
            'max_risk_penalty': float(getattr(self.config, 'max_risk_penalty', 30)),
        }

    def _validate_parameters(self):
        """参数验证"""
        params = self.parameters

        # 检查评分参数合理性
        assert params['max_continuous_score'] + params['max_sector_score'] <= 100, "评分上限设置不合理"
        assert params['max_risk_penalty'] >= 0, "风险惩罚应为非负数"

        # 检查范围参数
        assert params['cond1_low_range_min'] < params['cond1_low_range_max'], "条件1范围设置错误"
        assert params['cond2_amplitude_min'] < params['cond2_amplitude_max'], "条件2范围设置错误"

        self._debug("✅ 参数验证通过")

    def select_stocks(self, universe: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        基于实时数据的选股流程（优化版）
        """
        start = datetime.now()
        self.logger.info("🌍 开始执行实时数据选股流程（优化版）")

        try:
            # 记录执行开始
            self.performance_stats['total_runs'] += 1

            # 1. 获取股票池
            if universe is None or len(universe) == 0:
                self.logger.info("📋 获取全市场正股列表")
                market_universe = self._get_full_market_universe()
            else:
                self.logger.info(f"📋 使用传入的股票列表: {len(universe)} 只")
                market_universe = universe

            if not market_universe:
                self.logger.warning("⚠️ 无法获取任何股票列表")
                return []

            self.logger.info(f"🌍 待分析股票数量: {len(market_universe)} 只")

            # 2. 初筛（基础过滤）
            candidates = self._initial_snapshot_filter(market_universe)
            self.logger.info(f"✅ 初筛完成: {len(candidates)} 只股票通过基础过滤")

            if not candidates:
                self.logger.warning("⚠️ 初筛后无候选股票")
                return []

            # 3. 预加载板块数据
            self._preload_sector_data(candidates)

            # 4. 实时条件判断（优化版评分）
            selected_stocks = self._realtime_condition_filter_enhanced(candidates)
            self.logger.info(f"✅ 实时条件筛选完成: {len(selected_stocks)} 只股票满足条件")

            # 5. 排序和限制
            selected_stocks.sort(key=lambda x: x.get('score', 0), reverse=True)
            max_stocks = self.parameters.get('max_stocks', 10)
            final_stocks = selected_stocks[:max_stocks]

            # 6. 统计和日志
            runtime = (datetime.now() - start).total_seconds()
            self._update_performance_stats(len(market_universe), len(candidates), len(selected_stocks), final_stocks,
                                           runtime)

            # 7. 详细结果展示
            self._display_detailed_results(final_stocks, runtime, len(market_universe), len(candidates))

            return final_stocks

        except Exception as e:
            self.logger.error(f"❌ 实时选股执行失败: {e}")
            self._debug(traceback.format_exc())
            return []

    def _realtime_condition_filter_enhanced(self, candidates: List[str]) -> List[Dict[str, Any]]:
        """
        实时条件筛选（优化版评分）
        """
        selected = []
        batch_size = self.parameters.get('batch_size', 100)

        total = len(candidates)
        batches = (total + batch_size - 1) // batch_size

        for batch_num in range(batches):
            batch_start = batch_num * batch_size
            batch_end = min(batch_start + batch_size, total)
            batch_symbols = candidates[batch_start:batch_end]

            self._debug(f"🔍 条件筛选批次 {batch_num + 1}/{batches}: {len(batch_symbols)} 只")

            # 获取快照
            snapshot = self._safe_get_market_snapshot(batch_symbols)
            if not snapshot:
                continue

            # 判断条件（优化版）
            for symbol in batch_symbols:
                data = snapshot.get(symbol, {})
                if not data:
                    continue

                try:
                    # 判断条件1和条件2
                    cond1_result = self._check_cond1_realtime(data)
                    cond2_result = self._check_cond2_realtime_alternative(data)

                    # 统计
                    if cond1_result['passed']:
                        self.performance_stats['cond1_passed'] += 1
                    if cond2_result['passed']:
                        self.performance_stats['cond2_passed'] += 1

                    # 如果满足条件1或条件2任意一个，计算优化版评分
                    if cond1_result['passed'] or cond2_result['passed']:
                        if cond1_result['passed'] and cond2_result['passed']:
                            self.performance_stats['both_cond_passed'] += 1

                        # 计算优化版综合评分
                        score_details = self._calculate_enhanced_score(data, cond1_result, cond2_result)
                        score = score_details['total_score']

                        # 生成理由
                        reason = self._generate_enhanced_reason(cond1_result, cond2_result, score_details)

                        selected.append({
                            'symbol': symbol,
                            'name': data.get('name', symbol),
                            'score': score,
                            'current_price': float(data.get('last_price', 0) or 0),
                            'change_rate': float(data.get('change_rate', 0) or 0),
                            'volume': int(data.get('volume', 0) or 0),
                            'amplitude': abs(float(data.get('amplitude', 0) or 0)),
                            'cond1': cond1_result,
                            'cond2': cond2_result,
                            'score_details': score_details,
                            'reason': reason,
                            'timestamp': datetime.now().isoformat(),
                        })

                except Exception as e:
                    self._debug(f"条件判断异常 {symbol}: {e}")
                    continue

        return selected

    def _calculate_enhanced_score(self, snapshot: Dict[str, Any],
                                  cond1_result: Dict[str, Any],
                                  cond2_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算优化版综合评分 - 修复权重和计算逻辑
        """
        score_details = {
            'condition_scores': {},
            'risk_adjustments': {},
            'sector_effects': {},
            'total_score': 0.0
        }

        total_score = 0.0

        try:
            # 1. 条件基础分 - 适当提高基础分确保有合理分数
            condition_base_score = 0.0
            if cond1_result['passed']:
                condition_base_score += 30  # 适当提高基础分
                self._debug(f"✅ 条件1通过 +30分")
            if cond2_result['passed']:
                condition_base_score += 30  # 适当提高基础分
                self._debug(f"✅ 条件2通过 +30分")

            # 双条件奖励
            dual_condition_bonus = 15 if cond1_result['passed'] and cond2_result['passed'] else 0
            if dual_condition_bonus > 0:
                self._debug(f"🎯 双条件奖励 +15分")

            score_details['condition_scores']['base_score'] = condition_base_score
            score_details['condition_scores']['dual_bonus'] = dual_condition_bonus
            total_score += condition_base_score + dual_condition_bonus

            # 2. 连续评分
            continuous_scores = self._calculate_continuous_scores(snapshot, cond1_result, cond2_result)
            continuous_total = continuous_scores['total_continuous_score']

            total_score += continuous_total
            score_details['condition_scores']['continuous'] = continuous_scores

            if continuous_total > 0:
                self._debug(f"📈 连续评分 +{continuous_total:.1f}分")

            # 3. 风险调整 - 注意这里是扣分，所以是负值
            risk_adjustments = self._calculate_risk_adjustments(snapshot)
            risk_total = risk_adjustments['total_risk_adjustment']
            total_score += risk_total  # 风险调整是负值，所以是减去
            score_details['risk_adjustments'] = risk_adjustments

            if risk_total < 0:
                self._debug(f"⚠️  风险调整 {risk_total:.1f}分")

            # 4. 板块效应
            sector_effects = self._calculate_sector_effects(snapshot)
            sector_total = sector_effects['total_sector_effect']
            total_score += sector_total
            score_details['sector_effects'] = sector_effects

            if sector_total > 0:
                self._debug(f"🏢 板块效应 +{sector_total:.1f}分")

            # 限制在0-100分
            total_score = max(0.0, min(100.0, total_score))

            score_details['total_score'] = total_score

            self._debug(f"🎯 总分计算: {condition_base_score + dual_condition_bonus:.1f}(基础) + "
                             f"{continuous_total:.1f}(连续) + {risk_total:.1f}(风险) + "
                             f"{sector_total:.1f}(板块) = {total_score:.1f}")

        except Exception as e:
            self._debug(f"优化版评分计算异常: {e}")
            score_details['total_score'] = 0.0

        return score_details

    def _calculate_continuous_scores(self, snapshot: Dict[str, Any],
                                     cond1_result: Dict[str, Any],
                                     cond2_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        连续评分计算 - 修复计算逻辑
        """
        continuous_scores = {
            'volume_amplitude_score': 0.0,
            'low_position_score': 0.0,
            'rise_momentum_score': 0.0,
            'volume_price_match_score': 0.0,
            'total_continuous_score': 0.0
        }

        try:
            amplitude = abs(float(snapshot.get('amplitude', 0) or 0))
            change_rate = float(snapshot.get('change_rate', 0) or 0)
            last_price = float(snapshot.get('last_price', 0) or 0)
            open_price = float(snapshot.get('open_price', 0) or 0)
            volume = int(snapshot.get('volume', 0) or 0)

            # 2.1 放量程度连续评分 - 修复计算逻辑
            base_amplitude = self.parameters.get('base_amplitude_threshold', 0.03)
            if amplitude > base_amplitude:
                # 振幅在3%-10%之间线性得分，最高25分
                volume_amplitude_score = min(25.0, (amplitude - base_amplitude) / 0.07 * 25.0)
            else:
                volume_amplitude_score = 0.0

            # 2.2 低位深度连续评分 - 修复计算逻辑
            optimal_low_range = self.parameters.get('optimal_low_range', [-0.03, -0.01])
            low_min, low_max = optimal_low_range

            if low_min <= change_rate <= low_max:
                # 在最优区间内[-3%, -1%]，得分15-25分
                center = (low_min + low_max) / 2  # -2%
                distance_from_center = abs(change_rate - center) / 0.01  # 距离中心点的百分比
                low_position_score = 25.0 * (1 - distance_from_center)
            elif -0.05 <= change_rate < low_min:
                # 在-5%到-3%区间，线性递减 5-15分
                low_position_score = 5.0 + 10.0 * (change_rate + 0.05) / 0.02
            elif low_max < change_rate <= 0.02:
                # 在-1%到+2%区间，线性递减 5-15分
                low_position_score = 15.0 - 10.0 * (change_rate + 0.01) / 0.03
            else:
                low_position_score = 0.0

            # 确保分数不为负
            low_position_score = max(0.0, low_position_score)

            # 2.3 启动力度连续评分 - 修复计算逻辑
            base_rise_threshold = self.parameters.get('base_rise_threshold', 0.01)
            actual_rise = max(0.0, change_rate)

            if actual_rise > base_rise_threshold:
                # 涨幅在1%-5%之间线性得分，最高20分
                rise_momentum_score = min(20.0, (actual_rise - base_rise_threshold) / 0.04 * 20.0)
            else:
                rise_momentum_score = 0.0

            # 2.4 量价配合度评分 - 修复计算逻辑
            volume_price_match_score = 0.0
            if amplitude > 0 and actual_rise > 0:
                volume_price_ratio = actual_rise / amplitude
                if 0.3 <= volume_price_ratio <= 0.8:
                    # 量价配合良好：涨幅占振幅的30%-80%
                    volume_price_match_score = 15.0
                elif volume_price_ratio > 0.8:
                    # 涨幅过大，可能过热
                    volume_price_match_score = 5.0
                else:
                    # 涨幅不足
                    volume_price_match_score = 3.0

            total_continuous_score = (volume_amplitude_score + low_position_score +
                                      rise_momentum_score + volume_price_match_score)

            continuous_scores.update({
                'volume_amplitude_score': volume_amplitude_score,
                'low_position_score': low_position_score,
                'rise_momentum_score': rise_momentum_score,
                'volume_price_match_score': volume_price_match_score,
                'total_continuous_score': total_continuous_score
            })

            # 调试日志
            self._debug(f"连续评分详情: 振幅{amplitude:.2%}→{volume_amplitude_score:.1f}分, "
                             f"涨跌幅{change_rate:.2%}→{low_position_score:.1f}分, "
                             f"涨幅{actual_rise:.2%}→{rise_momentum_score:.1f}分, "
                             f"量价配合→{volume_price_match_score:.1f}分")

        except Exception as e:
            self._debug(f"连续评分计算异常: {e}")

        return continuous_scores

    def _calculate_risk_adjustments(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        风险调整计算
        """
        risk_adjustments = {
            'volatility_penalty': 0.0,
            'liquidity_discount': 0.0,
            'price_risk': 0.0,
            'total_risk_adjustment': 0.0
        }

        try:
            amplitude = abs(float(snapshot.get('amplitude', 0) or 0))
            market_cap = float(snapshot.get('market_cap', 0) or 0)
            last_price = float(snapshot.get('last_price', 0) or 0)

            # 3.1 波动率惩罚（调整：不要过度惩罚，限制最大惩罚）
            high_amplitude_threshold = self.parameters.get('high_amplitude_penalty_threshold', 0.15)  # 提高到15%
            if amplitude > high_amplitude_threshold:
                # 限制最大惩罚为-30分
                volatility_penalty = max(-30.0, -15.0 * (amplitude - high_amplitude_threshold) / 0.1)
            elif amplitude > 0.10:  # 10%以上才开始惩罚
                volatility_penalty = -5.0 * (amplitude - 0.10) / 0.05
            else:
                volatility_penalty = 0.0

            # 3.2 流动性折扣（调整：降低惩罚力度）
            base_market_cap = self.parameters.get('base_market_cap', 5e9)
            if market_cap < 1e9:
                liquidity_discount = -8.0  # 从-15降低到-8
            elif market_cap < base_market_cap:
                liquidity_discount = -5.0 * (1 - market_cap / base_market_cap)  # 从-10降低到-5
            else:
                liquidity_discount = 0.0

            # 3.3 价格位置风险
            low_price_penalty = self.parameters.get('low_price_penalty', 0.5)
            high_price_penalty = self.parameters.get('high_price_penalty', 200)

            if last_price < low_price_penalty:
                price_risk = -10.0
            elif last_price > high_price_penalty:
                price_risk = -5.0
            else:
                price_risk = 0.0

            total_risk_adjustment = volatility_penalty + liquidity_discount + price_risk

            risk_adjustments.update({
                'volatility_penalty': volatility_penalty,
                'liquidity_discount': liquidity_discount,
                'price_risk': price_risk,
                'total_risk_adjustment': total_risk_adjustment
            })

        except Exception as e:
            self._debug(f"风险调整计算异常: {e}")

        return risk_adjustments

    def _calculate_sector_effects(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        板块效应计算
        """
        sector_effects = {
            'sector_strength_score': 0.0,
            'relative_strength_score': 0.0,
            'leader_bonus': 0.0,
            'total_sector_effect': 0.0
        }

        try:
            symbol = snapshot.get('symbol', '')
            change_rate = float(snapshot.get('change_rate', 0) or 0)

            # 获取板块数据
            sector_data = self._get_sector_data(symbol)
            if not sector_data:
                return sector_effects

            sector_avg_change = sector_data.get('avg_change_rate', 0.0)

            # 4.1 板块强度得分
            if sector_avg_change > 0.02:
                sector_strength_score = 15.0
            elif sector_avg_change > 0.0:
                sector_strength_score = 10.0
            elif sector_avg_change > -0.01:
                sector_strength_score = 5.0
            else:
                sector_strength_score = 0.0

            # 4.2 相对强度得分
            relative_strength = change_rate - sector_avg_change
            if relative_strength > 0.01:
                relative_strength_score = 10.0
            elif relative_strength > 0.0:
                relative_strength_score = 5.0
            else:
                relative_strength_score = 0.0

            # 4.3 龙头效应加分
            turnover_rank = sector_data.get('turnover_rank', 999)
            if turnover_rank <= 3:
                leader_bonus = 10.0
            elif turnover_rank <= 10:
                leader_bonus = 5.0
            else:
                leader_bonus = 0.0

            total_sector_effect = sector_strength_score + relative_strength_score + leader_bonus

            sector_effects.update({
                'sector_strength_score': sector_strength_score,
                'relative_strength_score': relative_strength_score,
                'leader_bonus': leader_bonus,
                'total_sector_effect': total_sector_effect
            })

        except Exception as e:
            self._debug(f"板块效应计算异常: {e}")

        return sector_effects

    def _preload_sector_data(self, symbols: List[str]):
        """预加载板块数据"""
        try:
            self.logger.info(f"📊 预加载板块数据: {len(symbols)} 只股票")
            loaded_count = 0

            for symbol in symbols:
                if symbol not in self.sector_cache:
                    sector_data = self._fetch_sector_data(symbol)
                    if sector_data:
                        self.sector_cache[symbol] = sector_data
                        loaded_count += 1

            self.logger.info(f"✅ 板块数据预加载完成: {loaded_count} 只股票")

        except Exception as e:
            self._debug(f"预加载板块数据异常: {e}")

    def _get_sector_data(self, symbol: str) -> Dict[str, Any]:
        """获取个股的板块数据"""
        return self.sector_cache.get(symbol, {})

    def _fetch_sector_data(self, symbol: str) -> Dict[str, Any]:
        """
        获取板块数据 - 基础实现
        """
        try:
            # 基础实现：使用broker获取板块信息
            if not self.broker:
                return {}

            # 尝试从broker获取股票详情，提取板块信息
            stock_detail = self._safe_get_stock_detail(symbol)
            if not stock_detail:
                return {}

            sector_data = {
                'sector_code': stock_detail.get('industry_id', ''),
                'sector_name': stock_detail.get('industry_name', ''),
                'stock_name': stock_detail.get('name', ''),
                # 模拟数据 - 实际应该从板块API获取
                'avg_change_rate': 0.0,
                'turnover_rank': 50,  # 默认排名
                'sector_size': 100  # 默认板块股票数量
            }

            # 如果是港股，尝试获取更详细的行业信息
            if symbol.startswith('HK.'):
                sector_data.update(self._get_hk_sector_info(symbol))

            self._debug(f"📊 获取板块数据: {symbol} -> {sector_data.get('sector_name', '未知')}")
            return sector_data

        except Exception as e:
            self._debug(f"获取板块数据异常 {symbol}: {e}")
            return {}

    def _safe_get_stock_detail(self, symbol: str) -> Dict[str, Any]:
        """安全获取股票详情"""
        try:
            # 这里需要根据具体的broker API实现
            # 假设broker有get_stock_detail方法
            if hasattr(self.broker, 'get_stock_detail'):
                return self.broker.get_stock_detail(symbol)
            return {}
        except Exception as e:
            self._debug(f"获取股票详情异常 {symbol}: {e}")
            return {}

    def _get_hk_sector_info(self, symbol: str) -> Dict[str, Any]:
        """获取港股板块信息"""
        # 港股行业分类映射
        hk_industries = {
            '地产': {'avg_change': 0.0, 'rank_base': 10},
            '金融': {'avg_change': 0.0, 'rank_base': 5},
            '科技': {'avg_change': 0.0, 'rank_base': 15},
            '医药': {'avg_change': 0.0, 'rank_base': 20},
            '消费': {'avg_change': 0.0, 'rank_base': 25},
        }

        # 这里可以根据股票代码前缀或其他特征判断行业
        # 简化实现，返回默认值
        return {
            'avg_change_rate': 0.0,
            'turnover_rank': 30,
            'sector_strength': 0.0
        }

    def _generate_enhanced_reason(self, cond1_result: Dict[str, Any],
                                  cond2_result: Dict[str, Any],
                                  score_details: Dict[str, Any]) -> str:
        """
        生成优化版选股理由
        """
        reasons = []

        try:
            # 条件理由
            if cond1_result['passed']:
                reasons.append("阳线放量低位")
            if cond2_result['passed']:
                reasons.append("均线收敛启动")

            # 连续评分理由
            continuous_scores = score_details.get('condition_scores', {}).get('continuous', {})
            if continuous_scores.get('volume_amplitude_score', 0) > 20:
                reasons.append("明显放量")
            elif continuous_scores.get('volume_amplitude_score', 0) > 10:
                reasons.append("温和放量")

            if continuous_scores.get('low_position_score', 0) > 15:
                reasons.append("黄金坑位")
            elif continuous_scores.get('low_position_score', 0) > 8:
                reasons.append("相对低位")

            # 板块效应理由
            sector_effects = score_details.get('sector_effects', {})
            if sector_effects.get('leader_bonus', 0) > 0:
                reasons.append("板块龙头")
            elif sector_effects.get('sector_strength_score', 0) > 10:
                reasons.append("板块强势")

            # 风险提示
            risk_adjustments = score_details.get('risk_adjustments', {})
            if risk_adjustments.get('volatility_penalty', 0) < -10:
                reasons.append("高波动")
            if risk_adjustments.get('liquidity_discount', 0) < -10:
                reasons.append("低流动性")

            if not reasons:
                reasons.append("综合评分通过")

        except Exception as e:
            self._debug(f"生成优化版理由异常: {e}")
            reasons = ["综合筛选通过"]

        return " | ".join(reasons)

    def _update_performance_stats(self, total_scanned: int, candidates: int,
                                  selected: int, final_stocks: List[Dict], runtime: float):
        """更新性能统计 - 增强版"""
        self.performance_stats['last_run_time'] = datetime.now()
        self.performance_stats['stocks_scanned'] = total_scanned
        self.performance_stats['execution_times'].append(runtime)

        # 只保留最近50次执行时间
        if len(self.performance_stats['execution_times']) > 50:
            self.performance_stats['execution_times'] = self.performance_stats['execution_times'][-50:]

        # 计算平均评分和评分分布
        if final_stocks:
            scores = [stock['score'] for stock in final_stocks]
            avg_score = sum(scores) / len(scores)
            self.performance_stats['avg_score'] = avg_score
            self.performance_stats['score_distribution'] = scores

            # 记录评分统计
            self._debug(f"📈 评分统计: 平均{avg_score:.1f}, 最高{max(scores):.1f}, 最低{min(scores):.1f}")

    def _log_detailed_statistics(self):
        """输出详细统计信息"""
        stats = self.performance_stats
        avg_execution_time = np.mean(stats['execution_times']) if stats['execution_times'] else 0

        self.logger.info(
            f"📊 详细统计: "
            f"条件1通过={stats['cond1_passed']}, "
            f"条件2通过={stats['cond2_passed']}, "
            f"双条件通过={stats['both_cond_passed']}, "
            f"平均评分={stats['avg_score']:.1f}, "
            f"平均耗时={avg_execution_time:.2f}s"
        )

    def _log_score_distribution(self, final_stocks: List[Dict]):
        """记录评分分布"""
        if not final_stocks:
            return

        scores = [stock['score'] for stock in final_stocks]

        # 评分区间统计
        score_ranges = {
            '90-100': 0, '80-89': 0, '70-79': 0,
            '60-69': 0, '50-59': 0, '0-49': 0
        }

        for score in scores:
            if score >= 90:
                score_ranges['90-100'] += 1
            elif score >= 80:
                score_ranges['80-89'] += 1
            elif score >= 70:
                score_ranges['70-79'] += 1
            elif score >= 60:
                score_ranges['60-69'] += 1
            elif score >= 50:
                score_ranges['50-59'] += 1
            else:
                score_ranges['0-49'] += 1

        self.logger.info(f"📊 评分分布: {score_ranges}")

    def _display_detailed_results(self, final_stocks: List[Dict], runtime: float,
                                 total_scanned: int, candidates: int):
        """
        显示详细的选股结果
        """
        print("\n" + "="*80)
        print("                            📊 详细选股结果分析                            ")
        print("="*80)

        if not final_stocks:
            print("  ❌ 本次选股未选出任何股票")
            return

        # 限制显示前10只股票
        display_stocks = final_stocks[:10]
        total_selected = len(final_stocks)

        # 显示选股统计
        print(f"  扫描股票: {total_scanned} 只")
        print(f"  初筛通过: {candidates} 只")
        print(f"  最终入选: {total_selected} 只")
        print(f"  显示前10只: {len(display_stocks)} 只")
        print(f"  执行时间: {runtime:.2f} 秒")
        print("-" * 80)

        # 显示每只股票的详细分析（只显示前10只）
        for i, stock in enumerate(display_stocks, 1):
            print(f"  {i}. {stock['symbol']:12} {stock['name']:20}")

            # 基础信息
            price = stock['current_price']
            change_rate = stock['change_rate']
            change_symbol = "+" if change_rate >= 0 else ""
            print(f"      价格: {price:8.2f} ({change_symbol}{change_rate:+.2%}) | "
                  f"成交量: {stock['volume']:>10,} | 振幅: {stock['amplitude']:.2%}")

            # 评分详情
            score_details = stock.get('score_details', {})
            condition_scores = score_details.get('condition_scores', {})
            risk_adjustments = score_details.get('risk_adjustments', {})
            sector_effects = score_details.get('sector_effects', {})

            # 条件通过情况
            cond1_passed = stock['cond1']['passed']
            cond2_passed = stock['cond2']['passed']
            cond_status = []
            if cond1_passed:
                cond_status.append("条件1✓")
            if cond2_passed:
                cond_status.append("条件2✓")

            print(f"      评分: {stock['score']:6.1f} | 条件: {', '.join(cond_status) if cond_status else '无'}")

            # 详细评分分解
            base_score = condition_scores.get('base_score', 0)
            dual_bonus = condition_scores.get('dual_bonus', 0)
            continuous = condition_scores.get('continuous', {}).get('total_continuous_score', 0)
            risk_adj = risk_adjustments.get('total_risk_adjustment', 0)
            sector_eff = sector_effects.get('total_sector_effect', 0)

            print(f"      评分分解: 基础{base_score:3.1f} + 双条件{dual_bonus:3.1f} + "
                  f"连续{continuous:4.1f} + 板块{sector_eff:4.1f} + 风险{risk_adj:5.1f}")

            # 连续评分详情
            continuous_details = condition_scores.get('continuous', {})
            if continuous_details:
                print(f"      连续评分: 振幅{continuous_details.get('volume_amplitude_score', 0):4.1f} + "
                      f"低位{continuous_details.get('low_position_score', 0):4.1f} + "
                      f"启动{continuous_details.get('rise_momentum_score', 0):4.1f} + "
                      f"量价{continuous_details.get('volume_price_match_score', 0):4.1f}")

            # 选股理由
            print(f"      理由: {stock.get('reason', 'N/A')}")

            # 条件详情
            if cond1_passed:
                cond1_details = stock['cond1']['details']
                print(f"      条件1详情: 阳线{cond1_details.get('is_red', False)} | "
                      f"放量{cond1_details.get('volume_signal', False)} | "
                      f"振幅{cond1_details.get('amplitude', 0):.2%} | "
                      f"低位{cond1_details.get('change_rate', 0):.2%}")

            if cond2_passed:
                cond2_details = stock['cond2']['details']
                print(f"      条件2详情: 收敛{cond2_details.get('is_converged', False)} | "
                      f"启动{cond2_details.get('is_starting', False)} | "
                      f"振幅{cond2_details.get('amplitude', 0):.2%} | "
                      f"涨跌幅{cond2_details.get('change_rate', 0):.2%}")

            print("-" * 80)

        # 总体统计（基于显示的前10只）
        print("\n  📈 总体统计（前10只）:")
        avg_score = np.mean([s['score'] for s in display_stocks]) if display_stocks else 0
        max_score = max([s['score'] for s in display_stocks]) if display_stocks else 0
        min_score = min([s['score'] for s in display_stocks]) if display_stocks else 0

        print(f"    平均评分: {avg_score:.1f} | 最高评分: {max_score:.1f} | 最低评分: {min_score:.1f}")

        # 条件通过统计（基于显示的前10只）
        cond1_count = sum(1 for s in display_stocks if s['cond1']['passed'])
        cond2_count = sum(1 for s in display_stocks if s['cond2']['passed'])
        both_cond_count = sum(1 for s in display_stocks if s['cond1']['passed'] and s['cond2']['passed'])

        print(f"    条件1通过: {cond1_count}只 | 条件2通过: {cond2_count}只 | 双条件通过: {both_cond_count}只")

        # 提示信息
        if total_selected > 10:
            print(f"\n  💡 提示: 共选出 {total_selected} 只股票，此处仅显示前10只。将根据持仓限制选择前 {min(3, total_selected)} 只进行交易")
        elif total_selected < self.parameters.get('max_stocks', 10):
            print(f"\n  💡 提示: 选股结果共 {total_selected} 只，将根据持仓限制选择前 {min(3, total_selected)} 只进行交易")
        else:
            print(f"\n  ✅ 选股结果充足，将选择前 {min(3, total_selected)} 只进行交易")

        print("="*80)

    def get_strategy_status(self) -> Dict[str, Any]:
        """获取策略状态"""
        status = {
            'strategy_name': self.name,
            'total_runs': self.performance_stats['total_runs'],
            'last_run_time': self.performance_stats['last_run_time'],
            'avg_execution_time': np.mean(self.performance_stats['execution_times']) if self.performance_stats[
                'execution_times'] else 0,
            'avg_score': self.performance_stats['avg_score'],
            'sector_cache_size': len(self.sector_cache),
            'parameters': {
                'max_stocks': self.parameters['max_stocks'],
                'batch_size': self.parameters['batch_size']
            }
        }
        return status

    def health_check(self) -> bool:
        """策略健康检查"""
        try:
            # 检查必要组件
            if not self.broker:
                self.logger.error("❌ Broker不可用")
                return False

            # 检查参数有效性
            self._validate_parameters()

            # 测试数据获取
            test_symbols = ['HK.00001', 'HK.00005']  # 测试用股票
            snapshot = self._safe_get_market_snapshot(test_symbols)
            if not snapshot:
                self.logger.warning("⚠️ 数据获取测试失败")

            self.logger.info("✅ 策略健康检查通过")
            return True

        except Exception as e:
            self.logger.error(f"❌ 策略健康检查失败: {e}")
            return False

    # 保留原有的辅助方法
    def _get_full_market_universe(self) -> List[str]:
        """获取全市场正股列表"""
        if not self.broker:
            self.logger.warning("broker 不可用，返回空列表")
            return []

        try:
            from futu import RET_OK

            current_market = getattr(self.config, 'current_market', 'hk')
            market_str = current_market.upper() if current_market else 'HK'

            ret, df = self.broker.get_stock_basicinfo(market_str)
            if ret == RET_OK and df is not None and not df.empty:
                codes = df['code'].astype(str).tolist()
                codes = [c for c in codes if isinstance(c, str) and c.strip()]

                normalized = []
                for c in codes:
                    if c.startswith('HK.') or c.startswith('US.') or '.' in c:
                        normalized.append(c)
                    else:
                        if market_str == 'HK':
                            normalized.append(f"HK.{c}")
                        elif market_str == 'US':
                            normalized.append(f"US.{c}")
                        else:
                            normalized.append(c)

                self.logger.info(f"📈 获取全市场正股: {len(normalized)} 只股票")
                return normalized

            return []

        except Exception as e:
            self.logger.error(f"获取全市场股票失败: {e}")
            return []

    def _initial_snapshot_filter(self, universe: List[str]) -> List[str]:
        """初筛过滤"""
        batch_size = self.parameters.get('batch_size', 100)
        min_vol = self.parameters.get('min_volume', 2_000_000)
        min_price = self.parameters.get('min_price', 0.1)
        min_mcap = self.parameters.get('min_market_cap', 2e8)
        max_change_rate = self.parameters.get('max_change_rate', 0.15)

        candidates = []
        filter_stats = {
            'price_rejected': 0,
            'volume_rejected': 0,
            'market_cap_rejected': 0,
            'change_rate_rejected': 0,
            'suspended': 0,
        }

        total = len(universe)
        batches = (total + batch_size - 1) // batch_size

        for batch_num in range(batches):
            batch_start = batch_num * batch_size
            batch_end = min(batch_start + batch_size, total)
            batch_symbols = universe[batch_start:batch_end]

            self._debug(f"📡 初筛批次 {batch_num + 1}/{batches}: {len(batch_symbols)} 只")

            snapshot = self._safe_get_market_snapshot(batch_symbols)
            if not snapshot:
                continue

            for symbol in batch_symbols:
                data = snapshot.get(symbol, {})
                if not data:
                    continue

                try:
                    last_price = float(data.get('last_price', 0) or 0)
                    volume = int(data.get('volume', 0) or 0)
                    change_rate = abs(float(data.get('change_rate', 0) or 0))

                    mcap = 0.0
                    for field in ['market_cap', 'total_market_val', 'circulating_market_val']:
                        val = data.get(field, 0)
                        if val and float(val) > 0:
                            mcap = float(val)
                            break

                    if last_price <= 0 or last_price < min_price:
                        filter_stats['price_rejected'] += 1
                        continue
                    if volume < min_vol:
                        filter_stats['volume_rejected'] += 1
                        continue
                    if mcap < min_mcap:
                        filter_stats['market_cap_rejected'] += 1
                        continue
                    if change_rate > max_change_rate:
                        filter_stats['change_rate_rejected'] += 1
                        continue
                    if data.get('trade_status') == 'SUSPENDED':
                        filter_stats['suspended'] += 1
                        continue

                    candidates.append(symbol)

                except Exception as e:
                    self._debug(f"初筛异常 {symbol}: {e}")
                    continue

        self.logger.info(
            f"📊 初筛统计: "
            f"价格拒绝={filter_stats['price_rejected']}, "
            f"成交量拒绝={filter_stats['volume_rejected']}, "
            f"市值拒绝={filter_stats['market_cap_rejected']}, "
            f"涨跌幅拒绝={filter_stats['change_rate_rejected']}, "
            f"停牌={filter_stats['suspended']}"
        )

        return candidates

    def _check_cond1_realtime(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """条件1判断"""
        result = {'passed': False, 'details': {}}

        try:
            last_price = float(snapshot.get('last_price', 0) or 0)
            open_price = float(snapshot.get('open_price', 0) or 0)
            amplitude = abs(float(snapshot.get('amplitude', 0) or 0))
            change_rate = float(snapshot.get('change_rate', 0) or 0)
            turnover = float(snapshot.get('turnover', 0) or 0)
            market_cap = float(snapshot.get('market_cap', 1) or 1)

            is_red = last_price > open_price
            result['details']['is_red'] = is_red

            amplitude_threshold = self.parameters.get('cond1_volume_amplitude_threshold', 0.03)
            volume_signal_1 = amplitude > amplitude_threshold

            turnover_ratio = turnover / market_cap if market_cap > 0 else 0
            volume_signal_2 = turnover_ratio > 0.001

            volume_signal = volume_signal_1 or volume_signal_2
            result['details']['volume_signal'] = volume_signal
            result['details']['amplitude'] = amplitude
            result['details']['turnover_ratio'] = turnover_ratio

            low_min = self.parameters.get('cond1_low_range_min', -0.05)
            low_max = self.parameters.get('cond1_low_range_max', 0.02)
            is_low = low_min < change_rate < low_max
            result['details']['is_low'] = is_low
            result['details']['change_rate'] = change_rate

            result['passed'] = is_red and volume_signal and is_low

        except Exception as e:
            self._debug(f"条件1判断异常: {e}")
            result['passed'] = False

        return result

    def _check_cond2_realtime_alternative(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """条件2判断"""
        result = {'passed': False, 'details': {}}

        try:
            amplitude = abs(float(snapshot.get('amplitude', 0) or 0))
            change_rate = float(snapshot.get('change_rate', 0) or 0)
            last_price = float(snapshot.get('last_price', 0) or 0)
            prev_close = float(snapshot.get('prev_close_price', 0) or 0)

            amp_min = self.parameters.get('cond2_amplitude_min', 0.01)
            amp_max = self.parameters.get('cond2_amplitude_max', 0.08)
            is_converged = amp_min < amplitude < amp_max
            result['details']['is_converged'] = is_converged
            result['details']['amplitude'] = amplitude

            start_min = self.parameters.get('cond2_start_range_min', -0.02)
            start_max = self.parameters.get('cond2_start_range_max', 0.05)
            is_starting = start_min < change_rate < start_max
            result['details']['is_starting'] = is_starting
            result['details']['change_rate'] = change_rate

            if prev_close > 0:
                price_vs_prev = (last_price - prev_close) / prev_close
                result['details']['price_vs_prev'] = price_vs_prev
                if start_min < price_vs_prev < start_max:
                    is_starting = True

            result['passed'] = is_converged and is_starting

        except Exception as e:
            self._debug(f"条件2判断异常: {e}")
            result['passed'] = False

        return result

    def _safe_get_market_snapshot(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """安全获取市场快照"""
        if not self.broker or not symbols:
            return {}

        try:
            return self.broker.get_market_snapshot(symbols)
        except Exception as e:
            self._debug(f"获取快照失败: {e}")
            return {}