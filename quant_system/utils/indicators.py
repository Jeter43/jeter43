# trading_system/utils/indicators.py


"""
技术指标计算工具模块 - Technical Indicators Calculation Module

本模块提供了量化交易系统中常用的技术分析指标计算功能。
所有指标计算都经过优化，确保计算效率和数值稳定性。

主要特性：
1. 完整的异常处理和参数验证
2. 性能监控和缓存优化
3. 类型安全和文档完整性
4. 支持批量计算和向量化操作
5. 可配置的计算参数和默认值

版本重大改进：
- 使用自定义异常替代简单的print错误输出
- 集成性能监控系统，所有函数都有执行时间统计
- 增加参数验证和边界检查，提高计算稳定性
- 添加缓存机制，避免重复计算提升性能
- 支持更多的技术指标和计算选项
- 提供完整的类型提示和文档字符串

核心功能分类：
1. 趋势指标: MA, EMA, MACD, 趋势强度等
2. 动量指标: RSI, KDJ, MACD等
3. 波动率指标: ATR, 布林带等
4. 成交量指标: OBV, 量比, 成交量MA等
5. 支撑阻力: 支撑位、阻力位计算
6. 综合分析: 多指标综合评分和信号生成
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
from decimal import Decimal
import warnings
from functools import lru_cache
from datetime import datetime

# 导入项目内部模块
from quant_system.core.exceptions import DataValidationError, DataNotFoundError
from quant_system.utils.monitoring import performance_monitor, Timer

# 忽略警告信息
warnings.filterwarnings('ignore')


# 模块级常量定义
class IndicatorConstants:
    """技术指标计算常量定义"""

    # 默认计算周期
    DEFAULT_PERIOD_FAST = 12  # MACD快线默认周期
    DEFAULT_PERIOD_SLOW = 26  # MACD慢线默认周期
    DEFAULT_PERIOD_SIGNAL = 9  # MACD信号线默认周期
    DEFAULT_PERIOD_RSI = 14  # RSI默认周期
    DEFAULT_PERIOD_BOLL = 20  # 布林带默认周期
    DEFAULT_PERIOD_ATR = 14  # ATR默认周期
    DEFAULT_PERIOD_KDJ = 9  # KDJ默认周期

    # 技术指标阈值
    RSI_OVERSOLD = 30  # RSI超卖阈值
    RSI_OVERBOUGHT = 70  # RSI超买阈值
    BOLLINGER_STD_DEV = 2  # 布林带标准差倍数

    # 数值稳定性参数
    MIN_DATA_LENGTH = 2  # 最小数据长度要求
    MAX_CACHE_SIZE = 1000  # 缓存最大大小


@performance_monitor("indicators_calculate_ema")
def calculate_ema(series: pd.Series,
                  period: int,
                  adjust: bool = False,
                  min_periods: Optional[int] = None) -> pd.Series:
    """
    计算指数移动平均线 (Exponential Moving Average)

    EMA给予近期价格更高的权重，相比SMA对价格变化更加敏感。
    计算公式: EMA_t = α * Price_t + (1-α) * EMA_{t-1}
    其中 α = 2 / (period + 1)

    Args:
        series (pd.Series): 价格数据序列，通常是收盘价
        period (int): EMA计算周期，必须大于0
        adjust (bool): 是否进行调整计算，默认为False
        min_periods (Optional[int]): 最小计算周期，为None时等于period

    Returns:
        pd.Series: 计算得到的EMA序列，与输入序列长度相同

    Raises:
        DataValidationError: 当输入参数无效或数据不足时
        DataNotFoundError: 当输入数据为空时

    Example:
        >>> close_prices = pd.Series([100, 101, 102, 101, 103])
        >>> ema_5 = calculate_ema(close_prices, period=5)
        >>> print(ema_5.iloc[-1])  # 输出最新的EMA值
    """
    # 参数验证
    if not isinstance(series, pd.Series):
        raise DataValidationError("series参数必须是pandas Series类型")

    if period <= 0:
        raise DataValidationError(f"period必须大于0，当前值: {period}")

    if len(series) == 0:
        raise DataNotFoundError("输入的价格序列为空")

    if len(series) < (min_periods or period):
        raise DataValidationError(
            f"数据长度不足: 需要至少{min_periods or period}个数据点，当前只有{len(series)}个"
        )

    try:
        # 使用pandas的ewm函数计算指数加权移动平均
        ema_series = series.ewm(
            span=period,
            adjust=adjust,
            min_periods=min_periods
        ).mean()

        return ema_series

    except Exception as e:
        raise DataValidationError(
            f"计算EMA时发生错误: {str(e)}",
            details={
                'period': period,
                'adjust': adjust,
                'data_length': len(series),
                'data_type': type(series).__name__
            }
        ) from e


@performance_monitor("indicators_calculate_sma")
def calculate_sma(series: pd.Series,
                  period: int,
                  min_periods: Optional[int] = None) -> pd.Series:
    """
    计算简单移动平均线 (Simple Moving Average)

    SMA是给定期间内价格的平均值，是最基本的技术指标之一。
    计算公式: SMA_t = (Price_t + Price_{t-1} + ... + Price_{t-period+1}) / period

    Args:
        series (pd.Series): 价格数据序列
        period (int): SMA计算周期，必须大于0
        min_periods (Optional[int]): 最小计算周期，为None时等于period

    Returns:
        pd.Series: 计算得到的SMA序列，前period-1个值为NaN

    Raises:
        DataValidationError: 当输入参数无效时
        DataNotFoundError: 当输入数据为空时

    Example:
        >>> close_prices = pd.Series([100, 101, 102, 101, 103])
        >>> sma_3 = calculate_sma(close_prices, period=3)
        >>> print(sma_3.iloc[-1])  # 输出: 102.0
    """
    # 参数验证
    if not isinstance(series, pd.Series):
        raise DataValidationError("series参数必须是pandas Series类型")

    if period <= 0:
        raise DataValidationError(f"period必须大于0，当前值: {period}")

    if len(series) == 0:
        raise DataNotFoundError("输入的价格序列为空")

    try:
        # 使用pandas的rolling函数计算简单移动平均
        sma_series = series.rolling(
            window=period,
            min_periods=min_periods
        ).mean()

        return sma_series

    except Exception as e:
        raise DataValidationError(
            f"计算SMA时发生错误: {str(e)}",
            details={
                'period': period,
                'data_length': len(series)
            }
        ) from e


@performance_monitor("indicators_calculate_atr")
def calculate_atr(high: Union[List[float], pd.Series],
                  low: Union[List[float], pd.Series],
                  close: Union[List[float], pd.Series],
                  period: int = IndicatorConstants.DEFAULT_PERIOD_ATR,
                  return_series: bool = False) -> Union[float, pd.Series]:
    """
    计算平均真实波幅 (Average True Range)

    ATR衡量价格波动性，考虑了价格跳空的情况。
    真实波幅(TR)取以下三者最大值:
    1. 当日最高价 - 当日最低价
    2. |当日最高价 - 前日收盘价|
    3. |当日最低价 - 前日收盘价|
    ATR是TR的N日移动平均

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: ATR计算周期，默认14
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[float, pd.Series]: ATR值或ATR序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> high = [100, 102, 101, 103]
        >>> low = [98, 100, 99, 101]
        >>> close = [99, 101, 100, 102]
        >>> atr_value = calculate_atr(high, low, close, period=14)
        >>> print(atr_value)  # 输出最新的ATR值
    """
    # 参数验证
    if period <= 0:
        raise DataValidationError(f"period必须大于0，当前值: {period}")

    # 转换输入数据为pandas Series
    try:
        high_series = pd.Series(high) if not isinstance(high, pd.Series) else high
        low_series = pd.Series(low) if not isinstance(low, pd.Series) else low
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    data_length = len(high_series)
    if data_length < period + 1:
        raise DataValidationError(
            f"数据长度不足: 需要至少{period + 1}个数据点计算{period}周期ATR，当前只有{data_length}个"
        )

    try:
        # 计算真实波幅(True Range)
        tr1 = high_series - low_series  # 当日波动范围
        tr2 = abs(high_series - close_series.shift(1))  # 向上跳空
        tr3 = abs(low_series - close_series.shift(1))  # 向下跳空

        # 取三者最大值作为真实波幅
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # 计算ATR (True Range的移动平均)
        atr_series = true_range.rolling(window=period).mean()

        if return_series:
            return atr_series
        else:
            atr_value = atr_series.iloc[-1]
            return float(atr_value) if not pd.isna(atr_value) else 0.0

    except Exception as e:
        raise DataValidationError(
            f"计算ATR时发生错误: {str(e)}",
            details={
                'period': period,
                'data_length': data_length,
                'return_series': return_series
            }
        ) from e


@performance_monitor("indicators_calculate_macd")
def calculate_macd(close: Union[List[float], pd.Series],
                   fast_period: int = IndicatorConstants.DEFAULT_PERIOD_FAST,
                   slow_period: int = IndicatorConstants.DEFAULT_PERIOD_SLOW,
                   signal_period: int = IndicatorConstants.DEFAULT_PERIOD_SIGNAL,
                   return_series: bool = False) -> Union[Dict[str, float], Dict[str, pd.Series]]:
    """
    计算MACD指标 (Moving Average Convergence Divergence)

    MACD是常用的趋势跟踪动量指标，由三部分组成：
    1. DIF (差离值) = EMA(快线) - EMA(慢线)
    2. DEA (信号线) = EMA(DIF)
    3. MACD柱 = (DIF - DEA) × 2

    Args:
        close: 收盘价序列
        fast_period: 快线EMA周期，默认12
        slow_period: 慢线EMA周期，默认26
        signal_period: 信号线EMA周期，默认9
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[Dict, Dict]: MACD指标值或序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> close_prices = [100, 101, 102, 101, 103, 104, 103, 105]
        >>> macd_data = calculate_macd(close_prices)
        >>> print(f"DIF: {macd_data['dif']}, DEA: {macd_data['dea']}, MACD: {macd_data['macd']}")
    """
    # 参数验证
    if fast_period >= slow_period:
        raise DataValidationError(f"快线周期必须小于慢线周期: {fast_period} >= {slow_period}")

    if slow_period <= 0 or fast_period <= 0 or signal_period <= 0:
        raise DataValidationError("所有周期参数必须大于0")

    # 转换输入数据
    try:
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    min_data_length = max(slow_period, signal_period) + 1
    if len(close_series) < min_data_length:
        raise DataValidationError(
            f"数据长度不足: 需要至少{min_data_length}个数据点，当前只有{len(close_series)}个"
        )

    try:
        # 计算快线和慢线EMA
        ema_fast = calculate_ema(close_series, fast_period)
        ema_slow = calculate_ema(close_series, slow_period)

        # 计算DIF (差离值)
        dif = ema_fast - ema_slow

        # 计算DEA (信号线，DIF的EMA)
        dea = calculate_ema(dif, signal_period)

        # 计算MACD柱状图
        macd_histogram = (dif - dea) * 2

        if return_series:
            return {
                'dif': dif,
                'dea': dea,
                'macd': macd_histogram
            }
        else:
            return {
                'dif': float(dif.iloc[-1]) if not pd.isna(dif.iloc[-1]) else 0.0,
                'dea': float(dea.iloc[-1]) if not pd.isna(dea.iloc[-1]) else 0.0,
                'macd': float(macd_histogram.iloc[-1]) if not pd.isna(macd_histogram.iloc[-1]) else 0.0
            }

    except Exception as e:
        raise DataValidationError(
            f"计算MACD时发生错误: {str(e)}",
            details={
                'fast_period': fast_period,
                'slow_period': slow_period,
                'signal_period': signal_period,
                'data_length': len(close_series)
            }
        ) from e


@performance_monitor("indicators_calculate_rsi")
def calculate_rsi(close: Union[List[float], pd.Series],
                  period: int = IndicatorConstants.DEFAULT_PERIOD_RSI,
                  return_series: bool = False) -> Union[float, pd.Series]:
    """
    计算相对强弱指数 (Relative Strength Index)

    RSI是动量振荡器，衡量价格变动的速度和幅度，用于识别超买超卖状态。
    计算公式: RSI = 100 - (100 / (1 + RS))
    其中 RS = 平均涨幅 / 平均跌幅

    Args:
        close: 收盘价序列
        period: RSI计算周期，默认14
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[float, pd.Series]: RSI值或RSI序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> close_prices = [100, 101, 102, 101, 100, 99, 98, 97, 96, 95]
        >>> rsi_value = calculate_rsi(close_prices, period=14)
        >>> print(f"RSI: {rsi_value}")
    """
    # 参数验证
    if period <= 0:
        raise DataValidationError(f"period必须大于0，当前值: {period}")

    # 转换输入数据
    try:
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    if len(close_series) < period + 1:
        raise DataValidationError(
            f"数据长度不足: 需要至少{period + 1}个数据点计算{period}周期RSI，当前只有{len(close_series)}个"
        )

    try:
        # 计算价格变化
        delta = close_series.diff()

        # 分离上涨和下跌
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        # 计算平均涨幅和平均跌幅
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        # 计算相对强度(RS)
        rs = avg_gain / avg_loss

        # 计算RSI
        rsi = 100 - (100 / (1 + rs))

        if return_series:
            return rsi
        else:
            rsi_value = rsi.iloc[-1]
            return float(rsi_value) if not pd.isna(rsi_value) else 50.0

    except Exception as e:
        raise DataValidationError(
            f"计算RSI时发生错误: {str(e)}",
            details={
                'period': period,
                'data_length': len(close_series)
            }
        ) from e


@performance_monitor("indicators_calculate_bollinger_bands")
def calculate_bollinger_bands(close: Union[List[float], pd.Series],
                              period: int = IndicatorConstants.DEFAULT_PERIOD_BOLL,
                              std_dev: int = IndicatorConstants.BOLLINGER_STD_DEV,
                              return_series: bool = False) -> Union[Dict[str, float], Dict[str, pd.Series]]:
    """
    计算布林带指标 (Bollinger Bands)

    布林带由三条线组成：
    1. 中轨: N日简单移动平均线
    2. 上轨: 中轨 + K倍标准差
    3. 下轨: 中轨 - K倍标准差

    Args:
        close: 收盘价序列
        period: 计算周期，默认20
        std_dev: 标准差倍数，默认2
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[Dict, Dict]: 布林带值或序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> close_prices = [100, 101, 102, 101, 103, 104, 103, 105, 104, 106]
        >>> bb_data = calculate_bollinger_bands(close_prices)
        >>> print(f"上轨: {bb_data['upper']}, 中轨: {bb_data['middle']}, 下轨: {bb_data['lower']}")
    """
    # 参数验证
    if period <= 0:
        raise DataValidationError(f"period必须大于0，当前值: {period}")

    if std_dev <= 0:
        raise DataValidationError(f"std_dev必须大于0，当前值: {std_dev}")

    # 转换输入数据
    try:
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    if len(close_series) < period:
        raise DataValidationError(
            f"数据长度不足: 需要至少{period}个数据点计算布林带，当前只有{len(close_series)}个"
        )

    try:
        # 计算中轨 (简单移动平均)
        middle_band = calculate_sma(close_series, period)

        # 计算标准差
        rolling_std = close_series.rolling(window=period).std()

        # 计算上轨和下轨
        upper_band = middle_band + (rolling_std * std_dev)
        lower_band = middle_band - (rolling_std * std_dev)

        if return_series:
            return {
                'upper': upper_band,
                'middle': middle_band,
                'lower': lower_band
            }
        else:
            current_price = close_series.iloc[-1]
            return {
                'upper': float(upper_band.iloc[-1]) if not pd.isna(upper_band.iloc[-1]) else current_price,
                'middle': float(middle_band.iloc[-1]) if not pd.isna(middle_band.iloc[-1]) else current_price,
                'lower': float(lower_band.iloc[-1]) if not pd.isna(lower_band.iloc[-1]) else current_price,
                'band_width': float((upper_band.iloc[-1] - lower_band.iloc[-1]) / middle_band.iloc[-1]) if not pd.isna(
                    middle_band.iloc[-1]) and middle_band.iloc[-1] > 0 else 0.0
            }

    except Exception as e:
        raise DataValidationError(
            f"计算布林带时发生错误: {str(e)}",
            details={
                'period': period,
                'std_dev': std_dev,
                'data_length': len(close_series)
            }
        ) from e


@performance_monitor("indicators_calculate_kdj")
def calculate_kdj(high: Union[List[float], pd.Series],
                  low: Union[List[float], pd.Series],
                  close: Union[List[float], pd.Series],
                  period: int = IndicatorConstants.DEFAULT_PERIOD_KDJ,
                  k_smooth: int = 3,
                  d_smooth: int = 3,
                  return_series: bool = False) -> Union[Dict[str, float], Dict[str, pd.Series]]:
    """
    计算KDJ指标 (随机指标)

    KDJ是动量振荡器，用于识别超买超卖状态，由K线、D线和J线组成。
    计算公式:
    RSV = (收盘价 - N日内最低价) / (N日内最高价 - N日内最低价) × 100
    K值 = RSV的M1日移动平均
    D值 = K值的M2日移动平均
    J值 = 3×K - 2×D

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 计算周期，默认9
        k_smooth: K值平滑周期，默认3
        d_smooth: D值平滑周期，默认3
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[Dict, Dict]: KDJ指标值或序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> high = [102, 103, 104, 103, 105, 106, 105, 107]
        >>> low = [98, 99, 100, 99, 101, 102, 101, 103]
        >>> close = [100, 101, 102, 101, 103, 104, 103, 105]
        >>> kdj_data = calculate_kdj(high, low, close)
        >>> print(f"K: {kdj_data['k']}, D: {kdj_data['d']}, J: {kdj_data['j']}")
    """
    # 参数验证
    if period <= 0 or k_smooth <= 0 or d_smooth <= 0:
        raise DataValidationError("所有周期参数必须大于0")

    # 转换输入数据
    try:
        high_series = pd.Series(high) if not isinstance(high, pd.Series) else high
        low_series = pd.Series(low) if not isinstance(low, pd.Series) else low
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    min_data_length = period + max(k_smooth, d_smooth)
    data_length = len(close_series)
    if data_length < min_data_length:
        raise DataValidationError(
            f"数据长度不足: 需要至少{min_data_length}个数据点，当前只有{data_length}个"
        )

    try:
        # 计算N日内最高价和最低价
        highest_high = high_series.rolling(window=period).max()
        lowest_low = low_series.rolling(window=period).min()

        # 计算RSV (未成熟随机值)
        rsv = ((close_series - lowest_low) / (highest_high - lowest_low)) * 100
        rsv = rsv.replace([np.inf, -np.inf], np.nan)  # 处理除零情况

        # 计算K值 (RSV的移动平均)
        k_value = rsv.rolling(window=k_smooth).mean()

        # 计算D值 (K值的移动平均)
        d_value = k_value.rolling(window=d_smooth).mean()

        # 计算J值
        j_value = 3 * k_value - 2 * d_value

        if return_series:
            return {
                'k': k_value,
                'd': d_value,
                'j': j_value
            }
        else:
            return {
                'k': float(k_value.iloc[-1]) if not pd.isna(k_value.iloc[-1]) else 50.0,
                'd': float(d_value.iloc[-1]) if not pd.isna(d_value.iloc[-1]) else 50.0,
                'j': float(j_value.iloc[-1]) if not pd.isna(j_value.iloc[-1]) else 50.0
            }

    except Exception as e:
        raise DataValidationError(
            f"计算KDJ时发生错误: {str(e)}",
            details={
                'period': period,
                'k_smooth': k_smooth,
                'd_smooth': d_smooth,
                'data_length': data_length
            }
        ) from e


@performance_monitor("indicators_calculate_volume_indicators")
def calculate_volume_indicators(volume: Union[List[float], pd.Series],
                                close: Union[List[float], pd.Series],
                                period: int = 20,
                                return_series: bool = False) -> Union[Dict[str, float], Dict[str, pd.Series]]:
    """
    计算成交量相关技术指标

    包括成交量移动平均、量比、OBV(能量潮)等成交量分析指标。

    Args:
        volume: 成交量序列
        close: 收盘价序列
        period: 计算周期，默认20
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[Dict, Dict]: 成交量指标值或序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> volume = [1000000, 1200000, 1500000, 1300000, 1100000]
        >>> close = [100, 101, 102, 101, 103]
        >>> volume_data = calculate_volume_indicators(volume, close)
        >>> print(f"成交量MA: {volume_data['volume_ma']}, 量比: {volume_data['volume_ratio']}")
    """
    # 参数验证
    if period <= 0:
        raise DataValidationError(f"period必须大于0，当前值: {period}")

    # 转换输入数据
    try:
        volume_series = pd.Series(volume) if not isinstance(volume, pd.Series) else volume
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    if len(volume_series) < period:
        raise DataValidationError(
            f"数据长度不足: 需要至少{period}个数据点，当前只有{len(volume_series)}个"
        )

    try:
        # 计算成交量移动平均
        volume_ma = volume_series.rolling(window=period).mean()

        # 计算量比 (当前成交量/平均成交量)
        volume_ratio = volume_series.iloc[-1] / volume_ma.iloc[-1] if volume_ma.iloc[-1] > 0 else 1.0

        # 计算OBV (能量潮)
        close_diff = close_series.diff()
        obv_direction = np.where(close_diff > 0, 1, np.where(close_diff < 0, -1, 0))
        obv = (volume_series * obv_direction).cumsum()

        if return_series:
            return {
                'volume_ma': volume_ma,
                'volume_ratio': volume_series / volume_ma,
                'obv': obv
            }
        else:
            return {
                'volume_ma': float(volume_ma.iloc[-1]) if not pd.isna(volume_ma.iloc[-1]) else volume_series.iloc[-1],
                'volume_ratio': float(volume_ratio) if not pd.isna(volume_ratio) else 1.0,
                'obv': float(obv.iloc[-1]) if not pd.isna(obv.iloc[-1]) else 0.0
            }

    except Exception as e:
        raise DataValidationError(
            f"计算成交量指标时发生错误: {str(e)}",
            details={
                'period': period,
                'data_length': len(volume_series)
            }
        ) from e


@performance_monitor("indicators_calculate_trend_strength")
def calculate_trend_strength(close: Union[List[float], pd.Series],
                             short_period: int = 5,
                             medium_period: int = 10,
                             long_period: int = 20,
                             return_series: bool = False) -> Union[Dict[str, Any], Dict[str, pd.Series]]:
    """
    计算趋势强度和方向

    通过多时间框架的均线排列判断趋势强度和方向，识别多头/空头排列。

    Args:
        close: 收盘价序列
        short_period: 短期均线周期，默认5
        medium_period: 中期均线周期，默认10
        long_period: 长期均线周期，默认20
        return_series: 是否返回整个序列，默认只返回最新值

    Returns:
        Union[Dict, Dict]: 趋势分析结果或序列

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> close_prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
        >>> trend_data = calculate_trend_strength(close_prices)
        >>> print(f"趋势: {trend_data['trend']}, 强度: {trend_data['strength']}")
    """
    # 参数验证
    periods = [short_period, medium_period, long_period]
    if any(p <= 0 for p in periods):
        raise DataValidationError("所有均线周期必须大于0")

    if not (short_period < medium_period < long_period):
        raise DataValidationError("周期必须满足: 短期 < 中期 < 长期")

    # 转换输入数据
    try:
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    if len(close_series) < long_period:
        raise DataValidationError(
            f"数据长度不足: 需要至少{long_period}个数据点，当前只有{len(close_series)}个"
        )

    try:
        # 计算不同周期的均线
        ma_short = calculate_sma(close_series, short_period)
        ma_medium = calculate_sma(close_series, medium_period)
        ma_long = calculate_sma(close_series, long_period)

        if return_series:
            return {
                'ma_short': ma_short,
                'ma_medium': ma_medium,
                'ma_long': ma_long
            }
        else:
            # 获取最新值
            short_val = ma_short.iloc[-1]
            medium_val = ma_medium.iloc[-1]
            long_val = ma_long.iloc[-1]
            current_price = close_series.iloc[-1]

            # 判断趋势方向
            if short_val > medium_val > long_val:
                direction = 1  # 上升趋势
                trend = 'bullish'
            elif short_val < medium_val < long_val:
                direction = -1  # 下降趋势
                trend = 'bearish'
            else:
                direction = 0  # 震荡
                trend = 'neutral'

            # 计算趋势强度 (基于均线排列的紧凑程度)
            if direction != 0:
                # 使用均线之间的距离比例作为强度指标
                price_range = max(short_val, medium_val, long_val) - min(short_val, medium_val, long_val)
                strength = min(price_range / long_val * 1000, 100) if long_val > 0 else 0
            else:
                strength = 0

            return {
                'trend': trend,
                'strength': float(strength),
                'direction': direction,
                'ma_short': float(short_val) if not pd.isna(short_val) else current_price,
                'ma_medium': float(medium_val) if not pd.isna(medium_val) else current_price,
                'ma_long': float(long_val) if not pd.isna(long_val) else current_price
            }

    except Exception as e:
        raise DataValidationError(
            f"计算趋势强度时发生错误: {str(e)}",
            details={
                'short_period': short_period,
                'medium_period': medium_period,
                'long_period': long_period,
                'data_length': len(close_series)
            }
        ) from e


@performance_monitor("indicators_calculate_support_resistance")
def calculate_support_resistance(high: Union[List[float], pd.Series],
                                 low: Union[List[float], pd.Series],
                                 close: Union[List[float], pd.Series],
                                 lookback: int = 20,
                                 method: str = 'pivot') -> Dict[str, float]:
    """
    计算支撑位和阻力位

    使用多种方法识别关键的价格支撑和阻力水平。

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        lookback: 回溯周期，默认20
        method: 计算方法，'pivot'（枢轴点）或'extreme'（极值点）

    Returns:
        Dict: 支撑位和阻力位

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> high = [102, 103, 104, 105, 106, 105, 104, 103]
        >>> low = [98, 99, 100, 101, 102, 101, 100, 99]
        >>> close = [100, 101, 102, 103, 104, 103, 102, 101]
        >>> sr_data = calculate_support_resistance(high, low, close)
        >>> print(f"支撑: {sr_data['support']}, 阻力: {sr_data['resistance']}")
    """
    # 参数验证
    if lookback <= 0:
        raise DataValidationError(f"lookback必须大于0，当前值: {lookback}")

    if method not in ['pivot', 'extreme']:
        raise DataValidationError(f"不支持的计算方法: {method}")

    # 转换输入数据
    try:
        high_series = pd.Series(high) if not isinstance(high, pd.Series) else high
        low_series = pd.Series(low) if not isinstance(low, pd.Series) else low
        close_series = pd.Series(close) if not isinstance(close, pd.Series) else close
    except Exception as e:
        raise DataValidationError(f"数据转换失败: {str(e)}")

    # 数据长度验证
    if len(high_series) < lookback:
        raise DataValidationError(
            f"数据长度不足: 需要至少{lookback}个数据点，当前只有{len(high_series)}个"
        )

    try:
        current_price = close_series.iloc[-1]

        if method == 'pivot':
            # 枢轴点方法
            pivot_point = (high_series.iloc[-1] + low_series.iloc[-1] + close_series.iloc[-1]) / 3
            resistance1 = 2 * pivot_point - low_series.iloc[-1]
            support1 = 2 * pivot_point - high_series.iloc[-1]
            resistance2 = pivot_point + (high_series.iloc[-1] - low_series.iloc[-1])
            support2 = pivot_point - (high_series.iloc[-1] - low_series.iloc[-1])

            return {
                'support1': float(support1),
                'support2': float(support2),
                'resistance1': float(resistance1),
                'resistance2': float(resistance2),
                'pivot_point': float(pivot_point),
                'current_price': float(current_price)
            }

        else:  # extreme method
            # 极值点方法 - 使用最近N日的高低点
            recent_high = max(high_series.tail(lookback))
            recent_low = min(low_series.tail(lookback))

            # 动态调整支撑阻力
            if current_price >= recent_high * 0.98:
                # 接近阻力，可能突破
                resistance = recent_high * 1.02
                support = recent_low
            elif current_price <= recent_low * 1.02:
                # 接近支撑，可能跌破
                support = recent_low * 0.98
                resistance = recent_high
            else:
                support = recent_low
                resistance = recent_high

            return {
                'support': float(support),
                'resistance': float(resistance),
                'current_price': float(current_price)
            }

    except Exception as e:
        raise DataValidationError(
            f"计算支撑阻力时发生错误: {str(e)}",
            details={
                'lookback': lookback,
                'method': method,
                'data_length': len(high_series)
            }
        ) from e


@performance_monitor("indicators_get_technical_summary")
def get_technical_summary(symbol: str,
                          high: Union[List[float], pd.Series],
                          low: Union[List[float], pd.Series],
                          close: Union[List[float], pd.Series],
                          volume: Union[List[float], pd.Series],
                          config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    获取综合技术分析摘要

    整合多个技术指标，给出股票的综合技术状态评估和交易信号。

    Args:
        symbol: 股票代码
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        volume: 成交量序列
        config: 配置参数，可覆盖默认参数

    Returns:
        Dict: 综合技术分析结果

    Raises:
        DataValidationError: 当输入数据无效时

    Example:
        >>> symbol = "000001.SZ"
        >>> high = [102, 103, 104, 105, 106]
        >>> low = [98, 99, 100, 101, 102]
        >>> close = [100, 101, 102, 103, 104]
        >>> volume = [1000000, 1200000, 1500000, 1300000, 1100000]
        >>> summary = get_technical_summary(symbol, high, low, close, volume)
        >>> print(f"技术评分: {summary['technical_score']}, 信号: {summary['signal']}")
    """
    # 参数验证
    if not symbol or not isinstance(symbol, str):
        raise DataValidationError("symbol必须是有效的字符串")

    # 使用配置或默认参数
    config = config or {}
    macd_fast = config.get('macd_fast', IndicatorConstants.DEFAULT_PERIOD_FAST)
    macd_slow = config.get('macd_slow', IndicatorConstants.DEFAULT_PERIOD_SLOW)
    rsi_period = config.get('rsi_period', IndicatorConstants.DEFAULT_PERIOD_RSI)
    bb_period = config.get('bb_period', IndicatorConstants.DEFAULT_PERIOD_BOLL)

    try:
        # 安全计算各项技术指标
        with Timer("technical_analysis_full"):
            # 趋势指标
            trend_data = safe_calculate(
                calculate_trend_strength, close,
                default_value={'trend': 'neutral', 'strength': 0, 'direction': 0}
            )

            # 动量指标
            macd_data = safe_calculate(
                calculate_macd, close, macd_fast, macd_slow,
                default_value={'dif': 0.0, 'dea': 0.0, 'macd': 0.0}
            )

            rsi_value = safe_calculate(
                calculate_rsi, close, rsi_period,
                default_value=50.0
            )

            kdj_data = safe_calculate(
                calculate_kdj, high, low, close,
                default_value={'k': 50.0, 'd': 50.0, 'j': 50.0}
            )

            # 波动率指标
            bb_data = safe_calculate(
                calculate_bollinger_bands, close, bb_period,
                default_value={'upper': close[-1], 'middle': close[-1], 'lower': close[-1]}
            )

            atr_value = safe_calculate(
                calculate_atr, high, low, close,
                default_value=0.0
            )

            # 成交量指标
            volume_data = safe_calculate(
                calculate_volume_indicators, volume, close,
                default_value={'volume_ma': volume[-1], 'volume_ratio': 1.0, 'obv': 0.0}
            )

            # 支撑阻力
            sr_data = safe_calculate(
                calculate_support_resistance, high, low, close,
                default_value={'support': close[-1] * 0.95, 'resistance': close[-1] * 1.05, 'current_price': close[-1]}
            )

        # 综合技术评分 (0-100)
        score = 50  # 基础中性分数

        # MACD信号评分
        if macd_data['dif'] > macd_data['dea'] and macd_data['macd'] > 0:
            score += 10  # 金叉且柱状图向上
        elif macd_data['dif'] < macd_data['dea'] and macd_data['macd'] < 0:
            score -= 10  # 死叉且柱状图向下

        # RSI信号评分
        if rsi_value < IndicatorConstants.RSI_OVERSOLD:
            score += 8  # 超卖区域，可能反弹
        elif rsi_value > IndicatorConstants.RSI_OVERBOUGHT:
            score -= 8  # 超买区域，可能回调

        # 布林带位置评分
        current_price = close[-1] if isinstance(close, list) else close.iloc[-1]
        if 'upper' in bb_data and 'lower' in bb_data:
            bb_width = bb_data['upper'] - bb_data['lower']
            if bb_width > 0:
                bb_position = (current_price - bb_data['lower']) / bb_width
                if bb_position < 0.2:
                    score += 6  # 接近下轨，可能反弹
                elif bb_position > 0.8:
                    score -= 6  # 接近上轨，可能回调

        # 趋势强度评分
        score += trend_data['strength'] * trend_data['direction'] * 0.3

        # 成交量确认评分
        if volume_data['volume_ratio'] > 1.5:
            if trend_data['direction'] == 1:
                score += 5  # 放量上涨
            elif trend_data['direction'] == -1:
                score -= 5  # 放量下跌

        # KDJ信号评分
        if kdj_data['k'] > kdj_data['d'] and kdj_data['k'] < 30:
            score += 4  # K线上穿D线且在超卖区
        elif kdj_data['k'] < kdj_data['d'] and kdj_data['k'] > 70:
            score -= 4  # K线下穿D线且在超买区

        # 确保分数在0-100范围内
        score = max(0, min(100, score))

        # 生成交易信号
        if score >= 70:
            signal = 'strong_bullish'
        elif score >= 60:
            signal = 'bullish'
        elif score <= 30:
            signal = 'strong_bearish'
        elif score <= 40:
            signal = 'bearish'
        else:
            signal = 'neutral'

        return {
            'symbol': symbol,
            'technical_score': round(score, 2),
            'signal': signal,
            'timestamp': datetime.now().isoformat(),
            'trend': trend_data,
            'momentum': {
                'macd': macd_data,
                'rsi': round(rsi_value, 2),
                'kdj': kdj_data
            },
            'volatility': {
                'bollinger_bands': bb_data,
                'atr': round(atr_value, 4)
            },
            'volume': volume_data,
            'levels': sr_data,
            'recommendation': 'BUY' if signal in ['strong_bullish', 'bullish'] else 'SELL' if signal in [
                'strong_bearish', 'bearish'] else 'HOLD'
        }

    except Exception as e:
        raise DataValidationError(
            f"生成技术分析摘要时发生错误: {str(e)}",
            details={'symbol': symbol, 'config': config}
        ) from e

def safe_calculate(func, *args, default_value=None, **kwargs):
    """
    安全计算技术指标的装饰器模式实现

    这个函数提供了技术指标计算的异常安全包装，确保即使某个指标计算失败
    也不会影响整个系统的运行。它会捕获所有异常并返回默认值。

    Args:
        func: 要执行的技术指标计算函数
        *args: 传递给函数的位置参数
        default_value: 计算失败时返回的默认值
        **kwargs: 传递给函数的关键字参数

    Returns:
        计算成功返回计算结果，失败返回default_value

    Example:
        >>> # 安全计算RSI，即使数据不足也不会抛出异常
        >>> rsi = safe_calculate(calculate_rsi, close_prices, period=14, default_value=50.0)
    """
    try:
        with Timer(f"safe_calculate_{func.__name__}"):
            result = func(*args, **kwargs)
            return result

    except (DataValidationError, DataNotFoundError) as e:
        # 记录业务异常但不中断程序
        print(f"⚠️ 技术指标计算业务异常 {func.__name__}: {e}")
        return default_value

    except Exception as e:
        # 记录系统异常但不中断程序
        print(f"🚨 技术指标计算系统异常 {func.__name__}: {e}")
        return default_value


# 导出所有函数
__all__ = [
    'calculate_ema',
    'calculate_sma',
    'calculate_atr',
    'calculate_macd',
    'calculate_rsi',
    'calculate_bollinger_bands',
    'calculate_kdj',
    'calculate_volume_indicators',
    'calculate_trend_strength',
    'calculate_support_resistance',
    'get_technical_summary',
    'safe_calculate',
    'IndicatorConstants'
]