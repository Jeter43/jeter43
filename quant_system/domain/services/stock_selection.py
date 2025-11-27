"""
选股服务模块 (trading_system/domain/services/stock_selection.py)

功能概述：
    提供专业的股票选择服务，结合技术分析、基本面分析和市场情绪。
    支持多种选股策略，包括自选股优先、技术面选股和混合策略。

核心特性：
    1. 多策略选股：支持多种选股算法的组合
    2. 智能评分：基于多维度指标的股票评分系统
    3. 缓存优化：选股结果的智能缓存和更新
    4. 性能监控：选股过程的性能统计和分析
    5. 配置驱动：基于配置的动态策略调整

设计模式：
    - 策略模式：可插拔的选股算法
    - 工厂模式：选股策略的创建和管理
    - 缓存模式：选股结果的智能缓存

版本历史：
    v1.0 - 基础选股服务
    v2.0 - 增加多策略支持和缓存优化
    v3.0 - 集成技术指标和性能监控
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from dataclasses import dataclass
from enum import Enum

from quant_system.infrastructure.brokers.base import Broker
from quant_system.core.config import ConfigManager
from quant_system.utils.logger import get_logger


class SelectionStrategy(Enum):
    """选股策略类型枚举"""
    PRIORITY_FIRST = "priority_first"  # 自选股优先
    TECHNICAL_ONLY = "technical_only"  # 纯技术分析
    MIXED_STRATEGY = "mixed_strategy"  # 混合策略
    MOMENTUM_BASED = "momentum_based"  # 动量策略


@dataclass
class StockScore:
    """股票评分数据类"""
    symbol: str
    name: str
    total_score: float
    technical_score: float
    fundamental_score: float
    momentum_score: float
    volume_score: float
    is_priority: bool
    current_price: float
    change_rate: float
    volume: float
    reason: str
    timestamp: datetime


class StockSelectionService:
    """
    选股服务 - 优化版本

    提供专业的股票选择功能，结合多种分析维度和智能评分系统。
    支持缓存优化和性能监控，确保选股过程的高效和准确。

    属性:
        broker: 券商接口实例
        config: 配置管理器实例
        user_priority_stocks: 用户自选股列表
        last_selection_time: 上次选股时间
        selection_cache: 选股结果缓存
        performance_stats: 选股性能统计
    """

    def __init__(self, broker: Broker, config: ConfigManager):
        """
        初始化选股服务

        Args:
            broker: 券商接口
            config: 配置管理器
        """
        self.broker = broker
        self.config = config
        self.logger = get_logger(__name__)

        # 选股状态
        self.user_priority_stocks: List[str] = self._load_priority_stocks()
        self.last_selection_time: Optional[datetime] = None

        # 缓存系统
        self.selection_cache: Dict[str, List[StockScore]] = {}
        self.cache_ttl = timedelta(hours=2)  # 缓存有效期2小时

        # 性能统计
        self.performance_stats = {
            'total_selections': 0,
            'average_duration': 0.0,
            'cache_hits': 0,
            'cache_misses': 0,
            'last_successful_selection': None
        }

        # 技术指标参数
        self._technical_params = {
            'ma_periods': [5, 10, 20, 60],
            'rsi_period': 14,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'bollinger_period': 20,
            'bollinger_std': 2
        }

        self.logger.info("选股服务初始化完成")

    def select_stocks_with_priority(self) -> List[str]:
        """
        执行优先选股策略 - 优化版本

        结合自选股优先和全市场优选，提供智能的股票选择。

        Returns:
            List[str]: 选中的股票代码列表
        """
        start_time = datetime.now()
        self.logger.info("🔍 启动智能选股：自选股优先 + 全市场优选")

        try:
            # 检查缓存
            cached_result = self._get_cached_selection()
            if cached_result:
                self.performance_stats['cache_hits'] += 1
                self.logger.info("🔄 使用缓存的选股结果")
                return cached_result

            self.performance_stats['cache_misses'] += 1

            # 获取自选股候选
            priority_candidates = self._analyze_priority_stocks()

            # 获取常规候选
            regular_candidates = self._run_regular_stock_selection()

            # 合并并排序所有候选
            all_candidates = priority_candidates + regular_candidates
            all_candidates.sort(key=lambda x: x.total_score, reverse=True)

            # 应用筛选条件
            filtered_candidates = self._apply_selection_filters(all_candidates)

            # 选择前N只股票
            max_stocks = getattr(self.config.trading, 'max_stocks', 10)
            final_stocks = filtered_candidates[:max_stocks]
            final_codes = [stock.symbol for stock in final_stocks]

            # 更新缓存和统计
            self._update_selection_cache(final_codes)
            self._update_performance_stats(start_time)

            # 记录选股结果
            self._log_selection_results(final_stocks)

            return final_codes

        except Exception as e:
            self.logger.error(f"选股过程异常: {e}")
            return []

    def get_stock_scores(self, symbols: List[str]) -> List[StockScore]:
        """
        获取指定股票的详细评分

        Args:
            symbols: 股票代码列表

        Returns:
            List[StockScore]: 股票评分列表
        """
        scores = []

        for symbol in symbols:
            try:
                score = self._calculate_comprehensive_score(symbol)
                if score:
                    scores.append(score)
            except Exception as e:
                self.logger.error(f"计算股票 {symbol} 评分失败: {e}")

        return scores

    def update_priority_stocks(self, new_stocks: List[str]) -> bool:
        """
        更新自选股列表

        Args:
            new_stocks: 新的自选股列表

        Returns:
            bool: 更新是否成功
        """
        try:
            # 验证股票代码格式
            validated_stocks = []
            for stock in new_stocks:
                if self._validate_stock_symbol(stock):
                    validated_stocks.append(stock)
                else:
                    self.logger.warning(f"无效的股票代码格式: {stock}")

            self.user_priority_stocks = validated_stocks
            self.logger.info(f"🔄 更新自选股列表: {len(validated_stocks)} 只股票")

            # 清除缓存，因为自选股列表已更新
            self._clear_cache()

            return True

        except Exception as e:
            self.logger.error(f"更新自选股列表失败: {e}")
            return False

    def should_run_selection(self) -> bool:
        """
        判断是否应该运行选股

        Returns:
            bool: 是否应该运行选股
        """
        current_time = datetime.now()

        # 检查今天是否已经运行过选股
        if (self.last_selection_time and
                self.last_selection_time.date() == current_time.date()):
            self.logger.debug("今天已经运行过选股")
            return False

        # 检查是否为交易日
        if current_time.weekday() >= 5:  # 周六周日
            self.logger.debug("非交易日，跳过选股")
            return False

        # 检查交易时间
        if not self._is_trading_hours():
            self.logger.debug("非交易时间，跳过选股")
            return False

        # 检查选股频率
        if self.last_selection_time:
            time_since_last = current_time - self.last_selection_time
            min_interval = timedelta(minutes=getattr(
                self.config.system, 'selection_interval_minutes', 120))
            if time_since_last < min_interval:
                return False

        return True

    def get_performance_report(self) -> Dict[str, Any]:
        """
        获取选股性能报告

        Returns:
            Dict[str, Any]: 性能报告数据
        """
        cache_efficiency = 0
        if self.performance_stats['cache_hits'] + self.performance_stats['cache_misses'] > 0:
            cache_efficiency = (self.performance_stats['cache_hits'] /
                                (self.performance_stats['cache_hits'] + self.performance_stats['cache_misses']) * 100)

        return {
            'total_selections': self.performance_stats['total_selections'],
            'cache_efficiency': f"{cache_efficiency:.1f}%",
            'average_duration': f"{self.performance_stats['average_duration']:.2f}s",
            'last_selection_time': self.last_selection_time,
            'priority_stocks_count': len(self.user_priority_stocks),
            'cache_size': len(self.selection_cache)
        }

    def _load_priority_stocks(self) -> List[str]:
        """
        加载自选股票池

        Returns:
            List[str]: 自选股列表
        """
        try:
            # 默认自选股列表（港股蓝筹）
            default_stocks = [
                '00700', '09988', '03690', '09888', '01810',  # 科技股
                '01299', '00883', '00388', '00941', '00857'  # 金融能源
            ]

            # 尝试从配置中获取自选股
            try:
                if (hasattr(self.config, 'stock_selection') and
                        hasattr(self.config.stock_selection, 'priority_stocks')):
                    configured_stocks = self.config.stock_selection.priority_stocks
                    if configured_stocks and isinstance(configured_stocks, list):
                        default_stocks = configured_stocks
            except AttributeError:
                pass  # 使用默认值

            # 标准化股票代码格式
            standardized_stocks = []
            for stock in default_stocks:
                if self._validate_stock_symbol(stock):
                    standardized_stocks.append(stock)

            self.logger.info(f"📋 加载自选股 {len(standardized_stocks)} 只")
            return standardized_stocks

        except Exception as e:
            self.logger.warning(f"加载自选股失败，使用默认列表: {e}")
            return ['00700', '09988', '03690', '09888', '01810']

    def _analyze_priority_stocks(self) -> List[StockScore]:
        """
        分析自选股 - 优化版本

        Returns:
            List[StockScore]: 自选股评分列表
        """
        candidates = []

        if not self.user_priority_stocks:
            self.logger.warning("⚠️ 自选股列表为空")
            return candidates

        # 批量获取市场数据
        market_data = self.broker.get_market_snapshot(self.user_priority_stocks)

        for symbol in self.user_priority_stocks:
            try:
                if symbol not in market_data:
                    self.logger.warning(f"无法获取 {symbol} 的市场数据")
                    continue

                data = market_data[symbol]
                score = self._calculate_priority_stock_score(symbol, data)

                if score:
                    candidates.append(score)
                    self.logger.debug(f"自选股分析: {symbol} 总分: {score.total_score:.2f}")

            except Exception as e:
                self.logger.error(f"分析自选股 {symbol} 失败: {e}")
                continue

        self.logger.info(f"✅ 自选股分析完成: {len(candidates)}只合格")
        return candidates

    def _run_regular_stock_selection(self) -> List[StockScore]:
        """
        运行常规选股 - 优化版本

        Returns:
            List[StockScore]: 常规选股评分列表
        """
        candidates = []

        # 获取热门股票池
        hot_stocks = self._get_hot_stock_pool()
        self.logger.info(f"分析常规股票池: {len(hot_stocks)} 只股票")

        # 批量处理以提高效率
        batch_size = 10
        for i in range(0, len(hot_stocks), batch_size):
            batch = hot_stocks[i:i + batch_size]

            for symbol in batch:
                try:
                    score = self._calculate_comprehensive_score(symbol)
                    if score and score.total_score >= 60:  # 及格线
                        candidates.append(score)

                except Exception as e:
                    self.logger.error(f"分析常规股票 {symbol} 失败: {e}")
                    continue

        self.logger.info(f"✅ 常规选股完成: {len(candidates)}只合格")
        return candidates

    def _calculate_comprehensive_score(self, symbol: str) -> Optional[StockScore]:
        """
        计算综合股票评分

        Args:
            symbol: 股票代码

        Returns:
            Optional[StockScore]: 股票评分对象
        """
        try:
            # 获取历史K线数据
            kline_data = self.broker.get_history_kline(
                symbol, ktype="K_DAY", max_count=100
            )

            if kline_data is None or kline_data.empty:
                return None

            # 获取当前市场数据
            current_data = self.broker.get_market_snapshot([symbol])
            if symbol not in current_data:
                return None

            current_info = current_data[symbol]

            # 计算各项得分
            technical_score = self._calculate_technical_score(kline_data)
            fundamental_score = self._calculate_fundamental_score(symbol)
            momentum_score = self._calculate_momentum_score(kline_data)
            volume_score = self._calculate_volume_score(kline_data, current_info)

            # 计算综合得分（加权平均）
            total_score = (
                    technical_score * 0.35 +
                    fundamental_score * 0.25 +
                    momentum_score * 0.25 +
                    volume_score * 0.15
            )

            # 创建评分对象
            score = StockScore(
                symbol=symbol,
                name=current_info.get('name', symbol),
                total_score=total_score,
                technical_score=technical_score,
                fundamental_score=fundamental_score,
                momentum_score=momentum_score,
                volume_score=volume_score,
                is_priority=symbol in self.user_priority_stocks,
                current_price=current_info.get('last_price', 0),
                change_rate=current_info.get('change_rate', 0),
                volume=current_info.get('volume', 0),
                reason=self._generate_selection_reason(technical_score, momentum_score),
                timestamp=datetime.now()
            )

            return score

        except Exception as e:
            self.logger.error(f"计算股票 {symbol} 综合评分失败: {e}")
            return None

    def _calculate_priority_stock_score(self, symbol: str, market_data: Dict) -> Optional[StockScore]:
        """
        计算自选股评分

        Args:
            symbol: 股票代码
            market_data: 市场数据

        Returns:
            Optional[StockScore]: 自选股评分对象
        """
        try:
            base_score = 75.0  # 自选股基础分

            # 价格变化分析
            change_rate = market_data.get('change_rate', 0)
            if 0 < change_rate <= 3:
                base_score += 8
            elif 3 < change_rate <= 6:
                base_score += 12
            elif change_rate > 6:
                base_score += 15
            elif change_rate < -3:  # 下跌时适当减分
                base_score -= 5

            # 成交量分析
            volume = market_data.get('volume', 0)
            avg_volume = market_data.get('avg_volume', volume)
            if volume > avg_volume * 2:
                base_score += 10
            elif volume > avg_volume * 1.5:
                base_score += 6

            # 技术信号强度
            signal_strength = self.get_signal_strength(symbol)
            base_score += (signal_strength - 50) * 0.3

            # 确保分数在合理范围内
            final_score = max(0, min(100, base_score))

            return StockScore(
                symbol=symbol,
                name=market_data.get('name', symbol),
                total_score=final_score,
                technical_score=final_score * 0.7,
                fundamental_score=final_score * 0.2,
                momentum_score=final_score * 0.1,
                volume_score=final_score * 0.1,
                is_priority=True,
                current_price=market_data.get('last_price', 0),
                change_rate=change_rate,
                volume=volume,
                reason="自选股优先策略",
                timestamp=datetime.now()
            )

        except Exception as e:
            self.logger.error(f"计算自选股 {symbol} 评分失败: {e}")
            return None

    def _calculate_technical_score(self, kline_data: pd.DataFrame) -> float:
        """
        计算技术面得分 - 优化版本

        Args:
            kline_data: K线数据

        Returns:
            float: 技术面得分 (0-100)
        """
        if len(kline_data) < 20:
            return 50.0

        try:
            close_prices = kline_data['close']
            score = 50.0

            # 移动平均线分析
            ma_scores = self._calculate_ma_scores(close_prices)
            score += ma_scores

            # RSI 指标
            rsi_score = self._calculate_rsi_score(close_prices)
            score += rsi_score

            # MACD 指标
            macd_score = self._calculate_macd_score(close_prices)
            score += macd_score

            # 布林带分析
            bollinger_score = self._calculate_bollinger_score(close_prices)
            score += bollinger_score

            return max(0, min(100, score))

        except Exception as e:
            self.logger.error(f"计算技术指标失败: {e}")
            return 50.0

    def _calculate_ma_scores(self, close_prices: pd.Series) -> float:
        """计算移动平均线得分"""
        score = 0.0

        # 计算不同周期的移动平均线
        ma5 = close_prices.rolling(5).mean().iloc[-1]
        ma10 = close_prices.rolling(10).mean().iloc[-1]
        ma20 = close_prices.rolling(20).mean().iloc[-1]
        ma60 = close_prices.rolling(60).mean().iloc[-1]
        current_price = close_prices.iloc[-1]

        # 多头排列加分
        if ma5 > ma10 > ma20 > ma60:
            score += 15
        elif ma5 > ma10 > ma20:
            score += 10
        elif ma5 > ma10:
            score += 5

        # 价格在均线上方加分
        if current_price > ma5:
            score += 5
        if current_price > ma10:
            score += 3
        if current_price > ma20:
            score += 2

        return score

    def _calculate_rsi_score(self, close_prices: pd.Series) -> float:
        """计算RSI指标得分"""
        try:
            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

            # RSI 在 30-70 之间为健康区间
            if 30 <= current_rsi <= 70:
                return 10
            elif 20 <= current_rsi < 30 or 70 < current_rsi <= 80:
                return 0
            else:
                return -5

        except Exception:
            return 0

    # 由于字符限制，剩余的技术指标计算方法和辅助方法将在下一条消息中继续...
    def _calculate_macd_score(self, close_prices: pd.Series) -> float:
        """计算MACD指标得分"""
        try:
            # 计算EMA
            ema12 = close_prices.ewm(span=12).mean()
            ema26 = close_prices.ewm(span=26).mean()

            # 计算MACD线和信号线
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9).mean()
            histogram = macd_line - signal_line

            current_macd = macd_line.iloc[-1]
            current_signal = signal_line.iloc[-1]
            current_histogram = histogram.iloc[-1]

            score = 0.0

            # MACD金叉加分
            if current_macd > current_signal and current_histogram > 0:
                score += 8
            # MACD在零轴上方加分
            if current_macd > 0:
                score += 5

            return score

        except Exception:
            return 0.0

    def _calculate_bollinger_score(self, close_prices: pd.Series) -> float:
        """计算布林带指标得分"""
        try:
            # 计算布林带
            middle_band = close_prices.rolling(20).mean()
            std = close_prices.rolling(20).std()
            upper_band = middle_band + (std * 2)
            lower_band = middle_band - (std * 2)

            current_price = close_prices.iloc[-1]
            current_upper = upper_band.iloc[-1]
            current_lower = lower_band.iloc[-1]
            current_middle = middle_band.iloc[-1]

            score = 0.0

            # 价格在布林带中上部为健康状态
            if current_lower <= current_price <= current_middle:
                score += 3
            elif current_middle < current_price <= current_upper:
                score += 5
            # 价格突破上轨可能超买，突破下轨可能超卖
            elif current_price > current_upper:
                score -= 2
            elif current_price < current_lower:
                score -= 3

            return score

        except Exception:
            return 0.0

    def _calculate_fundamental_score(self, symbol: str) -> float:
        """
        计算基本面得分

        Args:
            symbol: 股票代码

        Returns:
            float: 基本面得分
        """
        try:
            base_score = 60.0

            # 这里可以接入真实的基本面数据
            # 暂时基于股票类型和行业给分

            # 根据股票代码特征给分（示例逻辑）
            if symbol.startswith('00'):  # 主板股票
                base_score += 10
            elif symbol.startswith('03'):  # 创业板
                base_score += 5

            # 行业权重（示例）
            industry_weights = {
                '00700': 8,  # 腾讯 - 互联网
                '09988': 7,  # 阿里巴巴 - 互联网
                '03690': 6,  # 美团 - 互联网
                '01299': 9,  # 友邦保险 - 金融
                '00883': 7,  # 中海油 - 能源
            }

            industry_bonus = industry_weights.get(symbol, 5)
            base_score += industry_bonus

            return min(100.0, base_score)

        except Exception as e:
            self.logger.error(f"计算基本面得分失败 {symbol}: {e}")
            return 50.0

    def _calculate_momentum_score(self, kline_data: pd.DataFrame) -> float:
        """
        计算动量得分

        Args:
            kline_data: K线数据

        Returns:
            float: 动量得分
        """
        if len(kline_data) < 10:
            return 50.0

        try:
            close_prices = kline_data['close']
            current_price = close_prices.iloc[-1]

            score = 50.0

            # 短期动量（5日）
            if len(close_prices) >= 6:
                price_5d_ago = close_prices.iloc[-6]
                momentum_5d = (current_price - price_5d_ago) / price_5d_ago * 100

                if momentum_5d > 8:
                    score += 20
                elif momentum_5d > 4:
                    score += 12
                elif momentum_5d > 2:
                    score += 8
                elif momentum_5d < -5:
                    score -= 10

            # 中期动量（20日）
            if len(close_prices) >= 21:
                price_20d_ago = close_prices.iloc[-21]
                momentum_20d = (current_price - price_20d_ago) / price_20d_ago * 100

                if momentum_20d > 15:
                    score += 15
                elif momentum_20d > 8:
                    score += 8
                elif momentum_20d < -10:
                    score -= 8

            return max(0, min(100, score))

        except Exception as e:
            self.logger.error(f"计算动量得分失败: {e}")
            return 50.0

    def _calculate_volume_score(self, kline_data: pd.DataFrame, current_info: Dict) -> float:
        """
        计算成交量得分

        Args:
            kline_data: K线数据
            current_info: 当前市场信息

        Returns:
            float: 成交量得分
        """
        try:
            volume_data = kline_data['volume']
            current_volume = current_info.get('volume', 0)

            if len(volume_data) < 20 or current_volume == 0:
                return 50.0

            # 计算平均成交量
            avg_volume = volume_data.mean()
            volume_ratio = current_volume / avg_volume

            score = 50.0

            # 成交量放大加分
            if volume_ratio > 3:
                score += 20
            elif volume_ratio > 2:
                score += 15
            elif volume_ratio > 1.5:
                score += 10
            elif volume_ratio < 0.5:  # 缩量减分
                score -= 10

            return max(0, min(100, score))

        except Exception as e:
            self.logger.error(f"计算成交量得分失败: {e}")
            return 50.0

    def get_signal_strength(self, symbol: str) -> int:
        """
        获取信号强度 - 优化版本

        Args:
            symbol: 股票代码

        Returns:
            int: 信号强度 (0-100)
        """
        try:
            # 获取历史数据
            kline_data = self.broker.get_history_kline(symbol, ktype="K_DAY", max_count=30)
            if kline_data is None or kline_data.empty:
                return 50

            # 获取当前市场数据
            current_data = self.broker.get_market_snapshot([symbol])
            if symbol not in current_data:
                return 50

            current_info = current_data[symbol]

            # 计算价格变化强度
            current_price = kline_data['close'].iloc[-1]
            prev_price = kline_data['close'].iloc[-2] if len(kline_data) > 1 else current_price
            price_change_pct = abs((current_price - prev_price) / prev_price * 100)

            # 计算成交量强度
            current_volume = current_info.get('volume', 0)
            avg_volume = kline_data['volume'].mean()
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            # 基础信号强度
            base_strength = 50

            # 价格变化贡献
            if price_change_pct > 5:
                base_strength += 25
            elif price_change_pct > 3:
                base_strength += 15
            elif price_change_pct > 1:
                base_strength += 8

            # 成交量贡献
            if volume_ratio > 2.5:
                base_strength += 25
            elif volume_ratio > 1.8:
                base_strength += 15
            elif volume_ratio > 1.3:
                base_strength += 8

            return max(0, min(100, base_strength))

        except Exception as e:
            self.logger.error(f"计算信号强度失败 {symbol}: {e}")
            return 50

    def _generate_selection_reason(self, technical_score: float, momentum_score: float) -> str:
        """生成选股理由"""
        reasons = []

        if technical_score > 70:
            reasons.append("技术面强势")
        elif technical_score < 40:
            reasons.append("技术面弱势")

        if momentum_score > 70:
            reasons.append("动量强劲")
        elif momentum_score < 40:
            reasons.append("动量不足")

        if not reasons:
            reasons.append("综合评估良好")

        return "，".join(reasons)

    def _get_hot_stock_pool(self) -> List[str]:
        """获取热门股票池"""
        # 这里可以扩展为从数据库、API或配置文件获取
        hot_stocks = [
            '00700', '09988', '03690', '09888', '01810',  # 科技股
            '01299', '00883', '00388', '00941', '00857',  # 金融能源
            '02318', '02020', '00669', '00175', '01024',  # 其他热门
            '09618', '09868', '09992', '09633', '09961'  # 更多股票
        ]
        return hot_stocks

    def _apply_selection_filters(self, candidates: List[StockScore]) -> List[StockScore]:
        """应用选股过滤器"""
        filtered = []

        for candidate in candidates:
            # 价格过滤器（避免价格过低或过高的股票）
            if candidate.current_price < 0.1 or candidate.current_price > 1000:
                continue

            # 成交量过滤器（避免流动性太差的股票）
            if candidate.volume < 1000000:  # 成交量少于100万
                continue

            # 涨跌幅过滤器（避免波动过大的股票）
            if abs(candidate.change_rate) > 20:  # 单日涨跌幅超过20%
                continue

            filtered.append(candidate)

        self.logger.debug(f"过滤器应用: {len(candidates)} -> {len(filtered)} 只股票")
        return filtered

    def _validate_stock_symbol(self, symbol: str) -> bool:
        """验证股票代码格式"""
        if not symbol or not isinstance(symbol, str):
            return False

        # 简单的格式验证（可以根据具体市场调整）
        clean_symbol = symbol.replace('HK.', '').strip()
        if not clean_symbol:
            return False

        # 检查是否只包含数字（港股代码通常是数字）
        return clean_symbol.isdigit()

    def _should_use_cache(self) -> bool:
        """判断是否使用缓存"""
        if not self.last_selection_time:
            return False

        time_diff = datetime.now() - self.last_selection_time
        return time_diff < self.cache_ttl

    def _get_cached_selection(self) -> Optional[List[str]]:
        """获取缓存的选股结果"""
        if not self._should_use_cache():
            return None

        cache_key = datetime.now().strftime("%Y%m%d_%H")
        return [score.symbol for score in self.selection_cache.get(cache_key, [])]

    def _update_selection_cache(self, stocks: List[str]):
        """更新选股缓存"""
        cache_key = datetime.now().strftime("%Y%m%d_%H")

        # 获取股票的完整评分信息
        stock_scores = self.get_stock_scores(stocks)
        self.selection_cache[cache_key] = stock_scores

        self.last_selection_time = datetime.now()
        self._cleanup_old_cache()

    def _cleanup_old_cache(self):
        """清理过期缓存"""
        current_time = datetime.now()
        expired_keys = []

        for key in self.selection_cache.keys():
            try:
                # 解析缓存键中的时间
                cache_time = datetime.strptime(key, "%Y%m%d_%H")
                if current_time - cache_time > self.cache_ttl:
                    expired_keys.append(key)
            except ValueError:
                expired_keys.append(key)  # 无效格式的键也删除

        for key in expired_keys:
            del self.selection_cache[key]
            self.logger.debug(f"清理过期缓存: {key}")

    def _clear_cache(self):
        """清空缓存"""
        self.selection_cache.clear()
        self.logger.info("选股缓存已清空")

    def _update_performance_stats(self, start_time: datetime):
        """更新性能统计"""
        duration = (datetime.now() - start_time).total_seconds()
        self.performance_stats['total_selections'] += 1

        # 更新平均持续时间
        total_selections = self.performance_stats['total_selections']
        current_avg = self.performance_stats['average_duration']
        new_avg = (current_avg * (total_selections - 1) + duration) / total_selections
        self.performance_stats['average_duration'] = new_avg

        self.performance_stats['last_successful_selection'] = datetime.now()

    def _log_selection_results(self, selected_stocks: List[StockScore]):
        """记录选股结果"""
        if not selected_stocks:
            self.logger.info("📭 本次选股未选中任何股票")
            return

        self.logger.info("🎯 选股结果详情:")
        for i, stock in enumerate(selected_stocks, 1):
            stock_type = "⭐自选" if stock.is_priority else "📊常规"
            self.logger.info(
                f"  {i}. {stock_type} {stock.symbol} {stock.name} - "
                f"总分: {stock.total_score:.1f} - "
                f"技术: {stock.technical_score:.1f} - "
                f"动量: {stock.momentum_score:.1f} - "
                f"价格: {stock.current_price:.2f} ({stock.change_rate:+.2f}%) - "
                f"{stock.reason}"
            )

    def _is_trading_hours(self) -> bool:
        """判断是否在交易时间内"""
        try:
            # 获取当前市场配置
            market_config = self.config.get_current_market_config()
            return market_config.is_market_open()
        except Exception as e:
            self.logger.warning(f"检查交易时间失败: {e}")
            # 默认交易时间判断（港股）
            current_time = datetime.now()
            current_hour = current_time.hour
            return 9 <= current_hour < 16  # 港股交易时间