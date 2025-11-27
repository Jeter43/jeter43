# quant_system/domain/strategies/selection_technical.py
"""
兼容 comp_trategy_HK_v5.4_20251017.py 行为的技术选股策略实现

说明：
- 力求在筛选逻辑、阈值和输出风格上与旧脚本一致（放量 1.5、均线聚拢阈值 3%、允许分数 > 100 等）
- 使用 TechnicalAnalyzer 和 MultiDimensionScorer 作为指标与评分引擎
- 并发拉历史以提高性能
- 详细 debug 日志输出以便逐条对比
- 新增：详细的入选理由说明
"""

import sys
import os
import logging
import random
import traceback
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

# 确保项目根目录可导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from quant_system.utils.logger import get_logger
from .base import SelectionStrategy, StrategyConfig, ExecutionResult
from quant_system.domain.analysis.technical_analyzer import TechnicalAnalyzer
from quant_system.domain.analysis.multi_dimension_scorer import MultiDimensionScorer

# 默认常量（接近旧脚本行为）
DEFAULT_HISTORY_BARS = 120  # 优化：从240减少到120，减少50%数据量
DEFAULT_BATCH_SIZE = 500
DEFAULT_MAX_ANALYSIS = 5000
DEFAULT_HISTORY_WORKERS = 8  # 优化：从12降到8，更严格遵守API频率限制（每30秒60次，8个并发更安全）


class DataCache:
    """数据缓存类 - 用于缓存K线和快照数据，提升性能"""
    
    def __init__(self, ttl_seconds: int = 300):  # 5分钟TTL
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds
        self.logger = get_logger(__name__)
    
    def _get_cache_key(self, symbol: str, data_type: str, **kwargs) -> str:
        """生成缓存键"""
        key_str = f"{symbol}_{data_type}_{kwargs}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, symbol: str, data_type: str, **kwargs) -> Optional[Any]:
        """获取缓存数据"""
        cache_key = self._get_cache_key(symbol, data_type, **kwargs)
        
        if cache_key in self.cache:
            cached_item = self.cache[cache_key]
            age = (datetime.now() - cached_item['timestamp']).total_seconds()
            
            if age < self.ttl:
                # 只在debug模式记录单个缓存命中
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"缓存命中: {symbol} {data_type}")
                return cached_item['data']
            else:
                # 缓存过期，删除
                del self.cache[cache_key]
        
        return None
    
    def set(self, symbol: str, data_type: str, data: Any, **kwargs):
        """设置缓存数据"""
        cache_key = self._get_cache_key(symbol, data_type, **kwargs)
        self.cache[cache_key] = {
            'data': data,
            'timestamp': datetime.now()
        }
        # 只在debug模式记录单个缓存设置
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"缓存设置: {symbol} {data_type}")
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.logger.info("数据缓存已清空")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            'cache_size': len(self.cache),
            'ttl_seconds': self.ttl
        }


class TechnicalSelectionStrategy(SelectionStrategy):
    """
    与 comp_trategy_HK_v5.4 兼容的技术选股策略实现
    新增详细入选理由功能
    """

    def __init__(self,
                 name: str = "technical_analysis",
                 config: Optional[StrategyConfig] = None,
                 broker: Optional[Any] = None,
                 stock_pool_manager: Optional[Any] = None):
        from quant_system.domain.strategies.base import StrategyType
        super().__init__(name, config, broker, stock_pool_manager)
        self.name = name
        self.config = config
        self.broker = broker
        self.stock_pool_manager = stock_pool_manager

        self.logger = get_logger(__name__)

        # 分析器与评分器
        self.technical_analyzer = TechnicalAnalyzer()
        self.scorer = MultiDimensionScorer(broker) if broker is not None else MultiDimensionScorer()

        # 参数：全市场分批处理配置（已优化性能）
        self.parameters: Dict[str, Any] = {
            'batch_size': int(getattr(self.config, 'batch_size', 200)),
            'max_analysis_stocks': int(getattr(self.config, 'max_analysis_stocks', 5000)),
            'history_min_bars': int(getattr(self.config, 'history_min_bars', DEFAULT_HISTORY_BARS)),  # 优化：默认120
            'history_workers': int(getattr(self.config, 'history_workers', DEFAULT_HISTORY_WORKERS)),  # 优化：默认12，避免API频率限制
            'min_volume': int(getattr(self.config, 'min_volume', 2_000_000)),  # 优化：从1M提高到2M，更严格初筛
            'min_price': float(getattr(self.config, 'min_price', 0.1)),
            'min_market_cap': float(getattr(self.config, 'min_market_cap', 2e8)),  # 优化：从1e8提高到2e8，更严格初筛
            'volatility_limit': float(getattr(self.config, 'volatility_limit', 0.15)),
            'w_tech': float(getattr(self.config, 'w_tech', 0.6)),
            'w_multi': float(getattr(self.config, 'w_multi', 0.4)),
            'score_threshold': float(getattr(self.config, 'score_threshold', 60.0)),
            'max_stocks': int(getattr(self.config, 'max_stocks', 50)),
            'priority_quota': int(getattr(self.config, 'priority_quota', 5)),
            'priority_boost': float(getattr(self.config, 'priority_boost', 10.0)),
            'allow_mock_market_data': bool(getattr(self.config, 'allow_mock_market_data', False)),
            'debug_relax_screening': bool(getattr(self.config, 'debug_relax_screening', True)),  # 临时打开以便调试
            'max_market_stocks': int(getattr(self.config, 'max_market_stocks', 10000)),  # 提高限制：支持全市场正股分析（港股主板约1500-2000只正股）
            'analysis_batch_size': int(getattr(self.config, 'analysis_batch_size', 100)),  # 优化：从200减少到100
            'enable_progressive_filter': bool(getattr(self.config, 'enable_progressive_filter', True)),  # 渐进式筛选
            'enable_cache': bool(getattr(self.config, 'enable_cache', True)),  # 新增：启用缓存
            'cache_ttl_seconds': int(getattr(self.config, 'cache_ttl_seconds', 300)),  # 新增：缓存TTL（5分钟）
            # 与旧脚本一致的阈值
            'volume_multiplier_for_signal': float(getattr(self.config, 'volume_multiplier_for_signal', 1.5)),
            'conv_threshold_percent': float(getattr(self.config, 'conv_threshold_percent', 3.0))
        }
        
        # 初始化数据缓存（性能优化）
        if self.parameters.get('enable_cache', True):
            self.data_cache = DataCache(ttl_seconds=self.parameters.get('cache_ttl_seconds', 300))
            self.logger.info("✅ 数据缓存已启用（TTL: 300秒）")
        else:
            self.data_cache = None

        # 简单 sector map（可被 stock_pool_manager 扩展）
        self.sector_map = self._initialize_sector_map()

        # 性能与统计
        self.performance_stats = {
            'total_runs': 0,
            'last_run_time': None,
            'candidates_examined': 0,
            'market_stocks_count': 0,
            'batches_processed': 0
        }

        self.logger.info(f"✅ TechnicalSelectionStrategy 初始化完成（性能优化版）: {self.name}")
        self.logger.info(f"   优化参数: K线={self.parameters['history_min_bars']}, 并发={self.parameters['history_workers']}, 最大分析={self.parameters['max_market_stocks']}")

    def _initialize_sector_map(self) -> Dict[str, str]:
        return {
            '00700': '科技', '09988': '科技', '03690': '科技',
            '00005': '金融', '00941': '电信', '02318': '金融',
            '01093': '医药', '00883': '能源', '00388': '金融'
        }

    # ---------- 顶层入口 ----------
    def select_stocks(self, universe: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        全市场选股流程 - 完整版本
        支持全市场选股和传入股票池两种模式
        """
        start = datetime.now()
        self.logger.info("🌍 开始执行全市场技术选股流程（完整版）")
        self._ensure_debug_logging()

        # 🎯 关键修复：处理股票池输入
        if universe is None or len(universe) == 0:
            self.logger.info("📋 universe参数为空，使用全市场获取")
            market_universe = self._get_full_market_universe()
        elif len(universe) < 100:  # 如果股票池很小，记录警告但仍使用
            self.logger.warning(f"⚠️ 检测到小规模股票池 ({len(universe)}只)，但仍会进行全市场选股")
            market_universe = self._get_full_market_universe()
        else:
            self.logger.info(f"📋 使用传入的股票列表: {len(universe)} 只")
            market_universe = universe

        if not market_universe:
            self.logger.warning("⚠️ 无法获取任何股票列表，返回空")
            return []

        try:
            # 1) 检查是否需要限制分析数量（仅当股票数量异常多时）
            # 注意：由于现在只获取正股，港股主板通常只有1500-2000只正股，一般不需要限制
            max_market_stocks = self.parameters.get('max_market_stocks', 10000)
            if len(market_universe) > max_market_stocks:
                original_count = len(market_universe)
                market_universe = market_universe[:max_market_stocks]
                self.logger.warning(f"⚠️ 股票数量异常多，限制分析数量: {original_count} → {max_market_stocks} 只股票")
            else:
                self.logger.info(f"✅ 全市场正股数量: {len(market_universe)} 只（未限制）")

            self.performance_stats['market_stocks_count'] = len(market_universe)
            self.logger.info(f"🌍 最终分析股票数量: {len(market_universe)} 只")

            # 2) 分批进行初筛
            batch_size = self.parameters.get('analysis_batch_size', 200)
            all_candidates = []

            total_batches = (len(market_universe) + batch_size - 1) // batch_size
            self.logger.info(f"🔄 开始分批初筛，共 {total_batches} 个批次")

            for batch_num, batch_start in enumerate(range(0, len(market_universe), batch_size)):
                batch_end = min(batch_start + batch_size, len(market_universe))
                batch_symbols = market_universe[batch_start:batch_end]

                self.logger.info(
                    f"🔄 处理初筛批次 {batch_num + 1}/{total_batches}: {batch_start}-{batch_end}"
                )

                # 初筛当前批次
                batch_candidates = self._initial_snapshot_filter(batch_symbols)
                all_candidates.extend(batch_candidates)

                self.logger.info(f"   ✅ 批次 {batch_num + 1} 初筛通过: {len(batch_candidates)} 只")

                # 如果候选总数过多，提前停止
                if len(all_candidates) >= self.parameters.get('max_analysis_stocks', 5000):
                    self.logger.info(f"📊 候选股票达到上限: {len(all_candidates)}，停止初筛")
                    break

            self.logger.info(f"🔎 全市场初筛完成: 总候选 {len(all_candidates)} 只")
            self.performance_stats['candidates_examined'] = len(all_candidates)

            if not all_candidates:
                self.logger.info("📭 全市场初筛未得到任何候选，返回空")
                return []

            # 3) 分批进行详细分析
            final_scored = []
            analysis_batch_size = min(100, batch_size)  # 详细分析批次更小

            analysis_batches = (len(all_candidates) + analysis_batch_size - 1) // analysis_batch_size
            self.logger.info(f"🔍 开始详细分析，共 {analysis_batches} 个批次")

            for batch_num, batch_start in enumerate(range(0, len(all_candidates), analysis_batch_size)):
                batch_end = min(batch_start + analysis_batch_size, len(all_candidates))
                batch_candidates = all_candidates[batch_start:batch_end]

                self.logger.info(
                    f"🔍 详细分析批次 {batch_num + 1}/{analysis_batches}: {len(batch_candidates)} 只"
                )

                # 并发获取历史数据和技术分析
                batch_indicators = self._parallel_fetch_and_calc(batch_candidates)

                # 对当前批次进行评分
                batch_scored = self._score_batch_stocks(batch_indicators)
                final_scored.extend(batch_scored)

                self.logger.info(f"   ✅ 批次 {batch_num + 1} 分析完成: {len(batch_scored)} 只")

                self.performance_stats['batches_processed'] = batch_num + 1

                # 显示进度
                progress = ((batch_num + 1) / analysis_batches) * 100
                if batch_num + 1 < analysis_batches:  # 不是最后一批时显示进度
                    self.logger.info(f"   📊 分析进度: {progress:.1f}%")

            # 4) 合并所有批次结果并排序
            if not final_scored:
                self.logger.info("📭 详细分析未得到任何有效结果")
                return []

            # 按评分排序
            ranked = sorted(final_scored, key=lambda x: x['score'], reverse=True)
            self.logger.info(f"📊 全市场分析完成: 共分析 {len(ranked)} 只股票")

            # 显示评分分布
            if ranked:
                scores = [item['score'] for item in ranked]
                self.logger.info(
                    f"📈 评分统计 - 最高: {max(scores):.1f}, 最低: {min(scores):.1f}, 平均: {sum(scores) / len(scores):.1f}")

            # 5) 板块分散 + 合并优先
            diversified = self._select_diversified(ranked)
            self.logger.info(f"🎯 板块分散后: {len(diversified)} 只股票")

            # 合并自选股
            priority_list = self._get_priority_stocks()
            if priority_list:
                self.logger.info(f"⭐ 发现 {len(priority_list)} 只自选股")
            final = self._merge_priority_and_trim(diversified, priority_list)

            # 格式化输出
            final_out = self._format_final_results(final)

            # 统计更新
            runtime = (datetime.now() - start).total_seconds()
            self.performance_stats['total_runs'] += 1
            self.performance_stats['last_run_time'] = datetime.now()

            self.logger.info(
                f"🎯 全市场选股完成: "
                f"耗时 {runtime:.2f}s, "
                f"分析 {len(market_universe)}→{len(all_candidates)}→{len(ranked)}→{len(final_out)}"
            )
            
            # 显示缓存统计
            if self.data_cache:
                cache_stats = self.data_cache.get_cache_stats()
                self.logger.info(f"📊 缓存统计: 缓存大小={cache_stats['cache_size']}, TTL={cache_stats['ttl_seconds']}秒")
            
            self._log_performance_summary(market_universe, all_candidates, ranked, final_out)

            # 显示最终结果摘要
            if final_out:
                self.logger.info("🏆 最终选股结果:")
                for i, stock in enumerate(final_out, 1):
                    self.logger.info(
                        f"  {i}. {stock['symbol']} {stock['name']} - "
                        f"评分: {stock['score']:.1f} - "
                        f"理由: {stock.get('reason', 'N/A')}"
                    )

            return final_out

        except Exception as e:
            self.logger.error(f"❌ 全市场选股执行失败: {e}")
            self.logger.debug(traceback.format_exc())
            return []

    def _detailed_analysis_optimized(self, candidates: List[str]) -> List[Dict[str, Any]]:
        """
        优化的详细分析 - 小批次处理避免内存和API限制
        """
        analysis_batch_size = 50  # 更小的分析批次
        final_scored = []

        self.logger.info(f"🔬 开始详细分析 {len(candidates)} 只候选股票")

        for batch_num, batch_start in enumerate(range(0, len(candidates), analysis_batch_size)):
            batch_end = min(batch_start + analysis_batch_size, len(candidates))
            batch_candidates = candidates[batch_start:batch_end]

            self.logger.info(
                f"🔍 详细分析批次 {batch_num + 1}/{(len(candidates) + analysis_batch_size - 1) // analysis_batch_size}")

            # 并发获取数据和技术分析
            batch_indicators = self._parallel_fetch_and_calc(batch_candidates)

            # 评分
            batch_scored = self._score_batch_stocks(batch_indicators)
            final_scored.extend(batch_scored)

            self.logger.info(f"   ✅ 批次 {batch_num + 1} 分析完成: {len(batch_scored)} 只")

            # 进度和内存监控
            progress = (batch_end / len(candidates)) * 100
            self.logger.info(f"   📊 分析进度: {progress:.1f}% ({batch_end}/{len(candidates)})")

        return final_scored

    def _get_full_market_universe(self) -> List[str]:
        """
        获取全市场正股列表（仅正股，不包含衍生品和指数）
        
        只获取 SecurityType.STOCK 类型的股票，确保分析的是真正的正股。
        衍生品（权证、窝轮等）和指数会在后续快照获取时被进一步过滤。
        """
        if not self.broker:
            self.logger.warning("broker 不可用，返回空列表")
            return []

        try:
            from futu import Market, SecurityType, RET_OK
            all_stocks = []

            # 只获取正股类型，不包含权证、指数等衍生品
            market_types = [
                (Market.HK, SecurityType.STOCK),  # 仅获取正股
            ]

            for market, sec_type in market_types:
                try:
                    # 分批获取，避免单次请求过多
                    ret, df = self.broker.get_stock_basicinfo(market, sec_type)
                    if ret == RET_OK and df is not None and not df.empty:
                        codes = df['code'].astype(str).tolist()
                        codes = [c for c in codes if isinstance(c, str) and c.strip()]
                        normalized = [c if c.startswith('HK.') else f"HK.{c}" for c in codes]
                        all_stocks.extend(normalized)
                        self.logger.info(f"📈 获取 {market}.{sec_type}（正股）: {len(normalized)} 只股票")
                except Exception as e:
                    self.logger.debug(f"获取 {market}.{sec_type} 失败: {e}")
                    continue

            # 去重
            all_stocks = list(set(all_stocks))
            self.logger.info(f"🌍 全市场正股总数: {len(all_stocks)} 只（已排除衍生品和指数）")

            return all_stocks

        except Exception as e:
            self.logger.error(f"获取全市场股票失败: {e}")
            self.logger.debug(traceback.format_exc())
            return []

    def _score_batch_stocks(self, indicators_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        对一批股票进行评分
        """
        scored = []

        for sym, payload in indicators_map.items():
            try:
                kline = payload.get('kline')
                snapshot = payload.get('snapshot', {})

                if kline is None or kline.empty:
                    continue

                # technical analyzer 基础结果
                tech_res = self.technical_analyzer.analyze_conditions(kline)
                # multi-dim score
                multi_res = self.scorer.calculate_comprehensive_score(sym, kline, snapshot)

                # 合并得分
                tech_base = float(tech_res.get('total_score', 0) or 0)
                multi_score = float(multi_res.get('final_score', 0) or 0)
                composite = self.parameters['w_tech'] * tech_base + self.parameters['w_multi'] * multi_score

                # 加入 volatility 惩罚
                vol = float(payload.get('indicators', {}).get('volatility', 0) or 0)
                if vol > self.parameters['volatility_limit']:
                    composite -= min(30.0, (vol - self.parameters['volatility_limit']) * 200.0)

                # 生成详细的入选理由
                reason = self._generate_detailed_reason(sym, tech_res, multi_res, composite, vol, snapshot)

                scored.append({
                    'symbol': sym,
                    'score': float(composite),
                    'tech_total_score': tech_base,
                    'multi_score': multi_score,
                    'indicators': payload.get('indicators', {}),
                    'kline': kline,
                    'snapshot': snapshot,
                    'reason': reason
                })

                # 记录详细日志（可选）
                if self.parameters.get('debug_relax_screening'):
                    name = snapshot.get('name', sym)
                    self.logger.debug(
                        f"   📊 {sym} {name}: 技术{tech_base:.1f}, 多维{multi_score:.1f}, 综合{composite:.1f}")

            except Exception as e:
                self.logger.debug(f"评分异常 {sym}: {e}")
                continue

        return scored

    def _get_priority_stocks(self) -> List[str]:
        """获取优先股票列表"""
        priority_list = []
        try:
            if self.stock_pool_manager:
                # 尝试获取不同的优先池
                priority_pools = ['priority', 'default', 'favorites', 'watchlist']
                for pool_name in priority_pools:
                    try:
                        if hasattr(self.stock_pool_manager, 'get_stocks_from_pool'):
                            stocks = self.stock_pool_manager.get_stocks_from_pool(pool_name)
                            if stocks:
                                priority_list.extend(stocks)
                                self.logger.info(f"🎯 从 {pool_name} 池获取 {len(stocks)} 只优先股")
                                break
                    except Exception:
                        continue
        except Exception as e:
            self.logger.debug(f"获取优先股失败: {e}")

        return list(set(priority_list))  # 去重

    def _format_final_results(self, final: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化最终结果"""
        final_out = []
        for item in final:
            snap = item.get('snapshot', {}) or {}
            final_out.append({
                'symbol': item['symbol'],
                'name': snap.get('name', item['symbol']),
                'score': float(item.get('score', 0)),
                'current_price': snap.get('last_price', 0),
                'change_rate': snap.get('change_rate', 0),
                'indicators': item.get('indicators', {}),
                'reason': item.get('reason')
            })
        return final_out

    def _log_performance_summary(self, market_universe: List[str], candidates: List[str],
                                 scored: List[Dict], final: List[Dict]):
        """记录性能摘要"""
        if scored:
            avg_score = sum(item['score'] for item in scored) / len(scored)
            high_score_count = sum(1 for item in scored if item['score'] >= 80)
            medium_score_count = sum(1 for item in scored if item['score'] >= 60)
        else:
            avg_score = 0
            high_score_count = 0
            medium_score_count = 0

        self.logger.info("📈 全市场选股性能摘要:")
        self.logger.info(f"   • 市场股票: {len(market_universe)}")
        self.logger.info(f"   • 初筛候选: {len(candidates)}")
        self.logger.info(f"   • 详细分析: {len(scored)}")
        self.logger.info(f"   • 最终入选: {len(final)}")
        self.logger.info(f"   • 平均评分: {avg_score:.1f}")
        self.logger.info(f"   • 高分股票(≥80): {high_score_count}只")
        self.logger.info(f"   • 良好股票(≥60): {medium_score_count}只")
        self.logger.info(f"   • 处理批次: {self.performance_stats['batches_processed']}")


    # 替换 _generate_detailed_reason 方法及其相关方法

    def _generate_detailed_reason(self, symbol: str, tech_res: Dict, multi_res: Dict,
                                  composite_score: float, volatility: float, snapshot: Dict) -> str:
        """
        生成详细的入选理由 - 优化版
        更积极地展示股票的优点
        """
        reasons = []

        try:
            # 1. 技术分析理由 - 优先展示正面信号
            tech_reasons = self._extract_tech_reasons(tech_res)
            reasons.extend(tech_reasons)

            # 2. 多维度评分理由 - 只展示优秀和良好的维度
            multi_reasons = self._extract_multi_reasons(multi_res)
            reasons.extend(multi_reasons)

            # 3. 价格表现理由 - 优先展示正面表现
            price_reasons = self._extract_price_reasons(snapshot)
            reasons.extend(price_reasons)

            # 4. 综合评分理由 - 根据实际分数调整描述
            score_reason = self._get_score_reason(composite_score)
            reasons.append(score_reason)

            # 5. 波动率特征 - 优化描述
            vol_reason = self._get_volatility_reason(volatility)
            if "低波动" in vol_reason or "正常" in vol_reason:
                reasons.append(vol_reason)

            # 6. 特殊信号 - 只展示正面信号
            special_signals = self._get_special_signals(tech_res, multi_res)
            reasons.extend(special_signals)

            # 如果理由不足，添加一些通用的正面描述
            if len(reasons) < 2:
                if composite_score >= 60:
                    reasons.append("技术面良好")
                elif composite_score >= 40:
                    reasons.append("具备潜力")
                else:
                    reasons.append("观察标的")

            # 限制理由数量，优先保留正面理由
            if len(reasons) > 4:
                # 优先保留正面理由
                positive_keywords = ['金叉', '多头', '突破', '放量', '优秀', '良好', '上涨', '高分', '共振']
                positive_reasons = [r for r in reasons if any(keyword in r for keyword in positive_keywords)]
                other_reasons = [r for r in reasons if r not in positive_reasons]
                main_reasons = positive_reasons[:3] + other_reasons[:1]
            else:
                main_reasons = reasons

            return " | ".join(main_reasons) if main_reasons else "综合技术分析"

        except Exception as e:
            self.logger.debug(f"生成入选理由失败 {symbol}: {e}")
            return "技术分析通过"

    def _extract_tech_reasons(self, tech_res: Dict) -> List[str]:
        """从技术分析结果提取理由 - 优化版"""
        reasons = []

        try:
            # 检查技术分析中的关键信号
            conditions = tech_res.get('conditions', {})

            # MACD 信号 - 只关注金叉
            macd_signal = conditions.get('macd_signal')
            if macd_signal == 'golden_cross':
                reasons.append("MACD金叉")

            # 均线排列 - 只关注多头
            ma_arrangement = conditions.get('ma_arrangement')
            if ma_arrangement == 'bullish':
                reasons.append("均线多头")

            # RSI 状态 - 优化描述
            rsi_status = conditions.get('rsi_status')
            if rsi_status == 'oversold':
                reasons.append("RSI超卖有机会")
            elif rsi_status == 'normal':
                reasons.append("RSI健康")

            # 成交量信号 - 只关注放量
            volume_signal = conditions.get('volume_signal')
            if volume_signal == 'volume_breakout':
                reasons.append("量价配合")

            # 趋势状态 - 只关注上升趋势
            trend = conditions.get('trend')
            if trend == 'uptrend':
                reasons.append("趋势向上")
            elif trend == 'sideways':
                reasons.append("震荡整理")

            # 突破信号
            if conditions.get('breakout'):
                reasons.append("形态突破")

        except Exception as e:
            self.logger.debug(f"提取技术理由失败: {e}")

        return reasons

    def _extract_multi_reasons(self, multi_res: Dict) -> List[str]:
        """从多维度评分提取理由 - 优化版"""
        reasons = []

        try:
            scores = multi_res.get('dimension_scores', {})

            # 只展示评分较高的维度
            dimension_names = {
                'momentum': '动量', 'value': '估值', 'growth': '成长',
                'quality': '质量', 'risk': '风控', 'liquidity': '流动性'
            }

            for dimension, score in scores.items():
                dim_name = dimension_names.get(dimension, dimension)
                if score >= 75:
                    reasons.append(f"{dim_name}优秀")
                elif score >= 60:
                    reasons.append(f"{dim_name}良好")

            # 特殊维度处理 - 优化描述
            momentum_score = scores.get('momentum', 0)
            if momentum_score >= 70:
                reasons.append("动量强劲")
            elif momentum_score >= 50:
                reasons.append("动量稳定")

            value_score = scores.get('value', 0)
            if value_score >= 70:
                reasons.append("估值吸引")

        except Exception as e:
            self.logger.debug(f"提取多维度理由失败: {e}")

        return reasons

    def _extract_price_reasons(self, snapshot: Dict) -> List[str]:
        """从价格数据提取理由 - 优化版"""
        reasons = []

        try:
            change_rate = snapshot.get('change_rate', 0)
            amplitude = snapshot.get('amplitude', 0)

            # 涨跌幅理由 - 优化描述
            if change_rate > 0.03:
                reasons.append("价格强势")
            elif change_rate > 0:
                reasons.append("价格企稳")
            elif change_rate >= -0.02:
                reasons.append("价格稳定")

            # 振幅理由 - 优化描述
            if 0.03 <= amplitude <= 0.08:
                reasons.append("交投活跃")
            elif amplitude < 0.03:
                reasons.append("走势稳健")

        except Exception as e:
            self.logger.debug(f"提取价格理由失败: {e}")

        return reasons

    def _get_score_reason(self, composite_score: float) -> str:
        """根据综合评分给出评价 - 优化版"""
        if composite_score >= 80:
            return "综合优秀"
        elif composite_score >= 60:
            return "表现良好"
        elif composite_score >= 40:
            return "具备潜力"
        else:
            return "观察标的"

    def _get_volatility_reason(self, volatility: float) -> str:
        """波动率特征 - 优化版"""
        if volatility < 0.015:
            return "走势稳健"
        elif volatility < 0.03:
            return "波动合理"
        elif volatility < 0.05:
            return "活跃度高"
        else:
            return "波动较大"

    def _get_special_signals(self, tech_res: Dict, multi_res: Dict) -> List[str]:
        """特殊信号检测 - 优化版"""
        signals = []

        try:
            # 检查是否有强烈的买入信号
            conditions = tech_res.get('conditions', {})

            # 多重技术指标共振
            bullish_signals = 0
            if conditions.get('macd_signal') == 'golden_cross':
                bullish_signals += 1
            if conditions.get('ma_arrangement') == 'bullish':
                bullish_signals += 1
            if conditions.get('trend') == 'uptrend':
                bullish_signals += 1

            if bullish_signals >= 2:
                signals.append("技术面共振")
            elif bullish_signals >= 1:
                signals.append("技术指标向好")

            # 检查超卖反弹机会
            if (conditions.get('rsi_status') == 'oversold' and
                    conditions.get('trend') != 'downtrend'):
                signals.append("超卖反弹机会")

            # 检查多维度优秀
            scores = multi_res.get('dimension_scores', {})
            excellent_dims = sum(1 for score in scores.values() if score >= 75)
            good_dims = sum(1 for score in scores.values() if score >= 60)

            if excellent_dims >= 2:
                signals.append("多维度优秀")
            elif good_dims >= 3:
                signals.append("多维度良好")

        except Exception as e:
            self.logger.debug(f"检测特殊信号失败: {e}")

        return signals

    # ---------- 辅助方法：市场列表 & 初筛 ----------
    def _get_market_universe(self) -> List[str]:
        """
        尽可能获取全市场股票列表，优先使用 broker.get_stock_basicinfo
        返回标准化为 'HK.XXXX' 的代码列表
        """
        if not self.broker or not hasattr(self.broker, 'get_stock_basicinfo'):
            self.logger.warning("broker 不可用或不支持 get_stock_basicinfo，返回空列表")
            return []

        try:
            # futu 风格: ret, df
            from futu import Market, SecurityType, RET_OK
            ret, df = self.broker.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
            if ret == RET_OK and df is not None and not df.empty:
                codes = df['code'].astype(str).tolist()
                codes = [c for c in codes if isinstance(c, str) and c.strip()]
                normalized = [c if c.startswith('HK.') else f"HK.{c}" for c in codes]
                return normalized
            else:
                self.logger.warning("broker.get_stock_basicinfo 未返回有效数据")
                return []
        except Exception as e:
            self.logger.error(f"获取市场股票失败: {e}")
            self.logger.debug(traceback.format_exc())
            return []

    def _initial_snapshot_filter(self, universe: List[str]) -> List[str]:
        batch = int(self.parameters.get('batch_size', DEFAULT_BATCH_SIZE))
        candidates = []
        max_cand = int(self.parameters.get('max_analysis_stocks', DEFAULT_MAX_ANALYSIS))
        vol_mult = float(self.parameters.get('volume_multiplier_for_signal', 1.5))
        min_vol = int(self.parameters.get('min_volume', 2_000_000))  # 优化：使用更严格的阈值
        min_price = float(self.parameters.get('min_price', 0.1))
        min_mcap = float(self.parameters.get('min_market_cap', 2e8))  # 优化：使用更严格的阈值

        total = len(universe)
        # 筛选统计（批量日志优化）
        filter_stats = {
            'price_rejected': 0,
            'volume_rejected': 0,
            'suspended': 0,
            'market_cap_rejected': 0,
            'change_rate_rejected': 0,
            'zero_market_cap': 0,
            'exceptions': 0
        }
        
        for i in range(0, total, batch):
            chunk = universe[i:i + batch]
            snap = self._safe_get_market_snapshot(chunk)
            if not snap:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"[SNAPSHOT] 批次 {i // batch + 1} 未获取到快照")
                continue

            for s in chunk:
                d = snap.get(s, {})
                if not d:
                    continue
                try:
                    last = float(d.get('last_price', 0) or 0)
                    vol = int(d.get('volume', 0) or 0)

                    # 🔧 修复：改进市值数据获取逻辑
                    # 尝试多种可能的市值字段
                    mcap = 0.0
                    market_cap_fields = [
                        'market_cap', 'total_market_val', 'total_market_cap',
                        'market_value', 'capitalization', 'circulating_market_val'
                    ]

                    for field in market_cap_fields:
                        field_value = d.get(field, 0)
                        if field_value and float(field_value) > 0:
                            mcap = float(field_value)
                            # 只在debug模式记录单个市值获取
                            if self.logger.isEnabledFor(logging.DEBUG) and self.parameters.get('debug_relax_screening'):
                                self.logger.debug(f"💰 {s} 使用 {field} 字段获取市值: {mcap}")
                            break

                    # 如果所有字段都是0，记录警告（但只记录一次或汇总）
                    if mcap == 0:
                        filter_stats['zero_market_cap'] += 1
                        if filter_stats['zero_market_cap'] <= 3:  # 只记录前3个
                            self.logger.warning(f"⚠️ {s} 所有市值字段均为0，检查可用字段: {list(d.keys())}")

                    trade_status = d.get('trade_status', None)
                    change_rate = abs(float(d.get('change_rate', 0) or 0))

                    # 基础过滤：价格、volume、状态、市值（批量统计，不逐条记录）
                    if last <= 0 or last < min_price:
                        filter_stats['price_rejected'] += 1
                        continue
                    if vol < min_vol:
                        filter_stats['volume_rejected'] += 1
                        continue
                    if trade_status == 'SUSPENDED':
                        filter_stats['suspended'] += 1
                        continue
                    if mcap < min_mcap:
                        filter_stats['market_cap_rejected'] += 1
                        continue
                    
                    # 优化：过滤掉单日涨跌幅过大的股票（减少异常波动）
                    if change_rate > 0.15:  # 过滤单日涨跌幅超过15%的
                        filter_stats['change_rate_rejected'] += 1
                        continue

                    # 通过初筛，加入候选
                    candidates.append(s)

                    # 若候选过多，截断（模拟旧脚本中对候选池的限制）
                    if len(candidates) >= max_cand:
                        # 输出筛选统计
                        if self.logger.isEnabledFor(logging.DEBUG):
                            self.logger.debug(f"初筛统计: 价格拒绝={filter_stats['price_rejected']}, "
                                            f"成交量拒绝={filter_stats['volume_rejected']}, "
                                            f"停牌={filter_stats['suspended']}, "
                                            f"市值拒绝={filter_stats['market_cap_rejected']}, "
                                            f"涨跌幅拒绝={filter_stats['change_rate_rejected']}")
                        return candidates

                except Exception as e:
                    filter_stats['exceptions'] += 1
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"[初筛异常] {s}: {e}")
                    continue

        # 输出最终筛选统计
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"初筛完成统计: 价格拒绝={filter_stats['price_rejected']}, "
                            f"成交量拒绝={filter_stats['volume_rejected']}, "
                            f"停牌={filter_stats['suspended']}, "
                            f"市值拒绝={filter_stats['market_cap_rejected']}, "
                            f"涨跌幅拒绝={filter_stats['change_rate_rejected']}, "
                            f"零市值={filter_stats['zero_market_cap']}, "
                            f"异常={filter_stats['exceptions']}, "
                            f"通过={len(candidates)}")

        return candidates

    def _safe_get_market_snapshot(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        分批获取市场快照，每批不超过200只
        已优化：添加缓存支持
        """
        if not symbols:
            return {}

        # 检查缓存
        cached_results = {}
        symbols_to_fetch = []
        
        if self.data_cache:
            for symbol in symbols:
                cached_snapshot = self.data_cache.get(symbol, 'snapshot')
                if cached_snapshot is not None:
                    cached_results[symbol] = cached_snapshot
                else:
                    symbols_to_fetch.append(symbol)
        else:
            symbols_to_fetch = symbols

        if not self.broker or not hasattr(self.broker, 'get_market_snapshot'):
            if self.parameters.get('allow_mock_market_data'):
                mock_data = self._generate_mock_market_data(symbols_to_fetch)
                # 存入缓存
                if self.data_cache and mock_data:
                    for symbol, data in mock_data.items():
                        self.data_cache.set(symbol, 'snapshot', data)
                cached_results.update(mock_data)
                return cached_results
            return cached_results

        try:
            # 分批处理，每批最多200只
            batch_size = 200
            all_results = {}

            total_batches = (len(symbols_to_fetch) - 1) // batch_size + 1
            failed_batches = 0
            
            for i in range(0, len(symbols_to_fetch), batch_size):
                batch_symbols = symbols_to_fetch[i:i + batch_size]
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"📡 获取快照批次 {i // batch_size + 1}/{total_batches}: {len(batch_symbols)} 只")

                try:
                    res = self.broker.get_market_snapshot(batch_symbols)
                    if res:
                        all_results.update(res)
                        # 存入缓存
                        if self.data_cache:
                            for symbol, snapshot in res.items():
                                self.data_cache.set(symbol, 'snapshot', snapshot)

                    # 添加小延迟避免API限制
                    import time
                    time.sleep(0.1)

                except Exception as e:
                    failed_batches += 1
                    self.logger.warning(f"快照批次 {i // batch_size + 1} 失败: {e}")
                    continue

            # 合并缓存和获取的结果
            cached_results.update(all_results)
            cache_count = len(cached_results) - len(all_results)
            self.logger.info(f"✅ 快照获取完成: {len(cached_results)}/{len(symbols)} 只股票（缓存: {cache_count}, 失败批次: {failed_batches}）")
            return cached_results

        except Exception as e:
            self.logger.error(f"get_market_snapshot 异常: {e}")
            if self.parameters.get('allow_mock_market_data'):
                mock_data = self._generate_mock_market_data(symbols_to_fetch)
                cached_results.update(mock_data)
                return cached_results
            return cached_results

    # ---------- 并发拉历史与指标计算 ----------
    def _parallel_fetch_and_calc(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        并发获取历史K线 - 优化版，控制并发数量
        已优化：提高并发数和批次大小
        """
        results = {}
        # 自适应并发控制：根据API限制（每30秒60次）动态调整
        # 保守估计：每个请求约0.5秒，12个并发更安全，避免触发频率限制
        workers = min(self.parameters.get('history_workers', DEFAULT_HISTORY_WORKERS), 10)  # 最大10，严格遵守API限制（每30秒60次）
        history_bars = self.parameters.get('history_min_bars', DEFAULT_HISTORY_BARS)

        # 控制每批处理数量
        batch_size = 100  # 优化：从50增加到100，提高吞吐量

        def task(sym: str):
            try:
                # 获取快照（单只股票，不受200限制）
                snap = self._safe_get_market_snapshot([sym]).get(sym, {})

                # 获取历史K线
                kline = self._safe_get_history_kline(sym, history_bars)
                if kline is None or len(kline) < history_bars:
                    if self.parameters.get('allow_mock_market_data'):
                        kline = self._generate_mock_kline(sym, bars=history_bars)
                    else:
                        return sym, None

                # 计算技术指标
                indicators = {}
                try:
                    ta_data = self.technical_analyzer._calculate_technical_indicators(kline.copy())
                    indicators.update({
                        'volatility': float(ta_data.get('CONV', pd.Series([0])).iloc[-1]),
                        'ma_mean': float(ta_data.get('MA_MEAN', pd.Series([0])).iloc[-1]),
                        'macd_golden': bool(ta_data.get('MACD_GOLDEN', pd.Series([False])).iloc[-1])
                    })
                except Exception as e:
                    self.logger.debug(f"指标计算失败 {sym}: {e}")

                return sym, {'kline': kline, 'snapshot': snap, 'indicators': indicators}

            except Exception as e:
                self.logger.debug(f"并发任务失败 {sym}: {e}")
                return sym, None

        # 分批执行并发任务
        for batch_start in range(0, len(symbols), batch_size):
            batch_symbols = symbols[batch_start:batch_start + batch_size]
            self.logger.info(
                f"🔍 分析批次 {batch_start // batch_size + 1}/{(len(symbols) - 1) // batch_size + 1}: {len(batch_symbols)} 只")

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_symbol = {executor.submit(task, sym): sym for sym in batch_symbols}

                for future in as_completed(future_to_symbol):
                    sym = future_to_symbol[future]
                    try:
                        symbol, payload = future.result()
                        if payload:
                            results[symbol] = payload
                    except Exception as e:
                        self.logger.debug(f"并发任务异常 {sym}: {e}")

            # 批次间延迟，避免API限制
            import time
            time.sleep(0.3)  # 优化：从0.5减少到0.3，加快速度

        return results

    def _safe_get_history_kline(self, symbol: str, bars: int) -> Optional[pd.DataFrame]:
        """
        安全获取历史K线（尝试 broker.get_history_kline），失败则返回 None（上层决定是否 mock）
        已优化：添加缓存支持
        """
        # 检查缓存
        if self.data_cache:
            cached_kline = self.data_cache.get(symbol, 'kline', bars=bars)
            if cached_kline is not None:
                return cached_kline
        
        if not self.broker or not hasattr(self.broker, 'get_history_kline'):
            if self.parameters.get('allow_mock_market_data'):
                return self._generate_mock_kline(symbol, bars=bars)
            return None

        try:
            kline = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=bars)
            if kline is not None and not kline.empty:
                # 存入缓存
                if self.data_cache:
                    self.data_cache.set(symbol, 'kline', kline, bars=bars)
                return kline
            return None
        except Exception as e:
            self.logger.debug(f"get_history_kline 异常 {symbol}: {e}")
            return None

    # ---------- 板块分散规则 ----------
    def _select_diversified(self, ranked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        尽量保证板块分散，尽量模仿旧脚本（第一轮：每板块取第一名；第二轮按分补充）
        """
        max_stocks = int(self.parameters.get('max_stocks', 20))
        per_sector_max = max(1, int(max_stocks / 4))
        if not ranked:
            return []

        sector_buckets: Dict[str, List[Dict[str, Any]]] = {}
        for item in ranked:
            sec = self._get_stock_sector(item['symbol'])
            sector_buckets.setdefault(sec, []).append(item)

        selected = []
        sector_counts = {}

        # 第一轮：每个板块取第一名
        for sec, arr in sector_buckets.items():
            if arr:
                selected.append(arr[0])
                sector_counts[sec] = 1

        # 第二轮：按得分补充，尊重每板块上限
        for item in ranked:
            if len(selected) >= max_stocks:
                break
            if item in selected:
                continue
            sec = self._get_stock_sector(item['symbol'])
            cnt = sector_counts.get(sec, 0)
            if cnt < per_sector_max:
                selected.append(item)
                sector_counts[sec] = cnt + 1

        # 按得分排序后返回
        return sorted(selected, key=lambda x: x['score'], reverse=True)[:max_stocks]

    # ---------- 合并优先逻辑 ----------
    def _merge_priority_and_trim(self, final_list: List[Dict[str, Any]], priority_list: List[str]) -> List[
        Dict[str, Any]]:
        """
        确保 priority_list（自选）能进入结果，且允许 priority_boost 把分数提升（可超 100）
        """
        if not priority_list:
            return final_list[:self.parameters.get('max_stocks', 20)]

        max_stocks = int(self.parameters.get('max_stocks', 20))
        quota = int(self.parameters.get('priority_quota', 5))
        boost = float(self.parameters.get('priority_boost', 10.0))
        allow_mock = bool(self.parameters.get('allow_mock_market_data', False))

        # 现有 symbol 集合
        exist = {it['symbol'] for it in final_list}
        inserted = 0
        # 优先保留已经在 final 的 priority
        retained = [it for it in final_list if it['symbol'] in priority_list]

        # 对没有进入 final 的 priority 做补救
        need = [p for p in priority_list if p not in exist]
        for p in need:
            if inserted >= quota:
                break
            snap = self._safe_get_market_snapshot([p]).get(p, {}) if self.broker else {}
            if not snap and not allow_mock:
                continue
            kline = self._safe_get_history_kline(p, int(self.parameters.get('history_min_bars', DEFAULT_HISTORY_BARS)))
            if kline is None and not allow_mock:
                continue
            kline = kline if kline is not None else self._generate_mock_kline(p, bars=int(
                self.parameters.get('history_min_bars', DEFAULT_HISTORY_BARS)))
            indicators = {}
            try:
                ta = self.technical_analyzer.analyze_conditions(kline)
                multi = self.scorer.calculate_comprehensive_score(p, kline, snap)
                base = float(ta.get('total_score', 0) or 0)
                mscore = float(multi.get('final_score', 0) or 0)
                base_composite = self.parameters['w_tech'] * base + self.parameters['w_multi'] * mscore
                boosted = base_composite + boost
                # 为优先股生成理由
                reason = f"自选优先股 | {self._get_score_reason(boosted)}"
            except Exception:
                boosted = boost  # 最低也给一个 boost
                reason = "自选优先股"

            cand = {
                'symbol': p,
                'score': float(boosted),
                'indicators': indicators,
                'snapshot': snap,
                'reason': reason
            }
            final_list.append(cand)
            inserted += 1
            self.logger.info(f"   ✅ 自选股入选: {p}，提分后得分: {boosted:.1f}，理由: {reason}")

        # 去重：保留最高分
        uniq = {}
        for it in final_list:
            sym = it.get('symbol')
            if not sym:
                continue
            if sym not in uniq or it.get('score', 0) > uniq[sym].get('score', 0):
                uniq[sym] = it

        merged = sorted(list(uniq.values()), key=lambda x: x.get('score', 0), reverse=True)[:max_stocks]
        return merged

    # ---------- 辅助工具 ----------
    def _get_stock_sector(self, symbol: str) -> str:
        try:
            code = symbol.replace('HK.', '')
            return self.sector_map.get(code, '其他')
        except Exception:
            return '其他'

    def _generate_mock_market_data(self, universe: List[str]) -> Dict[str, Any]:
        res = {}
        for s in universe:
            p = round(random.uniform(5, 200), 2)
            res[s] = {
                'last_price': p,
                'volume': random.randint(100_000, 50_000_000),
                'market_cap': random.uniform(1e8, 1e11),
                'total_market_val': random.uniform(1e8, 1e11),
                'change_rate': random.uniform(-0.05, 0.05),
                'name': s
            }
        return res

    def _generate_mock_kline(self, symbol: str, bars: int = DEFAULT_HISTORY_BARS) -> pd.DataFrame:
        import numpy as _np
        dates = pd.date_range(end=pd.Timestamp.today(), periods=bars)
        price = _np.cumsum(_np.random.randn(bars)) + 50.0
        df = pd.DataFrame({
            'time_key': dates,
            'open': price,
            'close': price + _np.random.randn(bars),
            'high': price + abs(_np.random.randn(bars)),
            'low': price - abs(_np.random.randn(bars)),
            'volume': (_np.random.rand(bars) * 1e6).astype(int)
        })
        return df

    def _ensure_debug_logging(self):
        """
        如果日志级别未被外部设置为 DEBUG，则临时将当前 logger 设为 DEBUG，便于对齐旧脚本输出
        （注意：生产环境不一定要持续 DEBUG）
        """
        try:
            # 如果根 logger 或当前 logger 等级不是 DEBUG，则临时设置 DEBUG
            if logging.getLogger().level != logging.DEBUG:
                logging.getLogger().setLevel(logging.DEBUG)
            self.logger.setLevel(logging.DEBUG)
        except Exception:
            pass

    def get_performance_metrics(self) -> Dict[str, Any]:
        base = super().get_performance_metrics()
        base.update({
            'parameters': self.parameters,
            'performance_stats': self.performance_stats
        })
        return base


# 导出
__all__ = ['TechnicalSelectionStrategy']

