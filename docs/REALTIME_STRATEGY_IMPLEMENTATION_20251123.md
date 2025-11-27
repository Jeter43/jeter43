# 实时数据选股策略实现说明 - 2025-11-23

## 📋 实现概述

已成功实现**方案3：纯实时替代方案**，创建了新的选股策略 `RealtimeSelectionStrategy`。

### 核心特点

1. **完全基于实时数据**：只使用快照数据（snapshot），不使用历史K线
2. **两个核心条件**：
   - 条件1：阳线放量低位（cond1）
   - 条件2：均线收敛启动（cond2）- 使用实时数据替代逻辑
3. **不消耗历史K线额度**：适合全市场实时监控，历史K线可用于回测

---

## 🎯 实现的功能

### 1. 条件1：阳线放量低位（纯实时实现）

**判断逻辑：**
- ✅ **阳线**：`last_price > open_price`（快照数据有）
- ✅ **放量**：
  - 方式1：振幅 > 3%（`amplitude > 0.03`）
  - 方式2：成交额/市值比例 > 0.1%（`turnover / market_cap > 0.001`）
- ✅ **低位**：涨跌幅在 -5% 到 +2% 之间

**参数配置：**
```python
'cond1_volume_amplitude_threshold': 0.03  # 振幅阈值（3%）
'cond1_low_range_min': -0.05  # 低位范围：-5%
'cond1_low_range_max': 0.02    # 低位范围：+2%
```

---

### 2. 条件2：均线收敛启动（实时替代方案）

**替代逻辑：**
由于没有均线数据，使用实时数据替代：
- ✅ **收敛**：振幅在 2%-6% 之间（表示波动收敛）
- ✅ **启动**：涨幅在 0-3% 之间（表示开始上涨）

**参数配置：**
```python
'cond2_amplitude_min': 0.02  # 收敛：振幅2%-6%
'cond2_amplitude_max': 0.06
'cond2_start_range_min': 0.0   # 启动：涨幅0-3%
'cond2_start_range_max': 0.03
```

---

## 📁 文件结构

### 新增文件

1. **`quant_system/domain/strategies/selection_realtime.py`**
   - 实时数据选股策略实现
   - 包含完整的选股流程和条件判断逻辑

### 修改文件

1. **`quant_system/domain/strategies/strategy_factory.py`**
   - 注册了新的实时选股策略
   - 策略名称：`realtime_monitoring`
   - 策略描述：`实时数据选股策略（纯实时，不使用历史K线）`

---

## 🚀 使用方法

### 1. 在策略选择中选择实时监控策略

运行主程序时，在选股策略选择中选择：
```
5. 🛠️ 自定义选择
```

然后选择 `realtime_monitoring` 策略。

### 2. 配置参数（可选）

可以在配置文件中调整参数，例如：
```yaml
realtime_monitoring:
  cond1_volume_amplitude_threshold: 0.03  # 条件1振幅阈值
  cond1_low_range_min: -0.05              # 条件1低位下限
  cond1_low_range_max: 0.02               # 条件1低位上限
  cond2_amplitude_min: 0.02                # 条件2振幅下限
  cond2_amplitude_max: 0.06                # 条件2振幅上限
  cond2_start_range_min: 0.0               # 条件2启动下限
  cond2_start_range_max: 0.03              # 条件2启动上限
  min_volume: 2000000                      # 最小成交量
  min_price: 0.1                           # 最小价格
  min_market_cap: 200000000               # 最小市值
  max_stocks: 50                           # 最大选股数量
```

---

## 📊 选股流程

1. **获取股票池**
   - 如果未指定，自动获取全市场正股列表
   - 支持自定义股票池

2. **初筛（基础过滤）**
   - 价格、成交量、市值过滤
   - 停牌股票过滤
   - 涨跌幅过大过滤（>15%）

3. **实时条件筛选（核心逻辑）**
   - 判断条件1：阳线放量低位
   - 判断条件2：均线收敛启动（实时替代）
   - 只保留同时满足两个条件的股票

4. **排序和限制**
   - 按综合评分排序
   - 限制最大选股数量（默认50只）

5. **输出结果**
   - 显示选中的股票列表
   - 包含评分、理由等详细信息

---

## 🔍 评分机制

### 综合评分计算

- **基础分**：50分
- **条件1贡献**：40分（满足条件1）
  - 额外加分：振幅>5% +10分，振幅>3% +5分
- **条件2贡献**：40分（满足条件2）
  - 额外加分：涨幅2-3% +10分，涨幅1-2% +5分
- **额外加分**：成交量>500万 +5分

**总分范围**：0-100分

---

## 📈 性能统计

策略会记录以下统计信息：
- `total_runs`：总运行次数
- `stocks_scanned`：扫描股票数量
- `cond1_passed`：条件1通过数量
- `cond2_passed`：条件2通过数量
- `both_cond_passed`：同时满足两个条件的数量

---

## ⚙️ 参数说明

### 条件1参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `cond1_volume_amplitude_threshold` | 0.03 | 放量判断的振幅阈值（3%） |
| `cond1_low_range_min` | -0.05 | 低位判断的下限（-5%） |
| `cond1_low_range_max` | 0.02 | 低位判断的上限（+2%） |

### 条件2参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `cond2_amplitude_min` | 0.02 | 收敛判断的振幅下限（2%） |
| `cond2_amplitude_max` | 0.06 | 收敛判断的振幅上限（6%） |
| `cond2_start_range_min` | 0.0 | 启动判断的涨幅下限（0%） |
| `cond2_start_range_max` | 0.03 | 启动判断的涨幅上限（3%） |

### 初筛参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_volume` | 2,000,000 | 最小成交量 |
| `min_price` | 0.1 | 最小价格 |
| `min_market_cap` | 200,000,000 | 最小市值（2亿） |
| `max_change_rate` | 0.15 | 最大涨跌幅（15%） |

### 批次处理参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `batch_size` | 100 | 批次大小 |
| `max_stocks` | 50 | 最大选股数量 |

---

## 🎯 优势与限制

### 优势

1. ✅ **完全不消耗历史K线额度**：适合全市场实时监控
2. ✅ **实时性强**：基于最新快照数据，响应迅速
3. ✅ **实现简单**：逻辑清晰，易于理解和调整
4. ✅ **资源消耗低**：只需要快照数据，API调用少

### 限制

1. ⚠️ **准确性可能略低**：条件2使用替代逻辑，可能不如真实均线准确
2. ⚠️ **需要验证效果**：需要实际运行验证选股效果
3. ⚠️ **参数需要调优**：可能需要根据实际市场情况调整参数

---

## 🔄 后续优化方向

### 阶段1：验证效果（当前）

- 运行策略，观察选股结果
- 对比历史K线策略的选股效果
- 收集反馈，调整参数

### 阶段2：优化提升（如果效果可接受）

- 如果效果可接受，继续使用纯实时方案
- 如果效果不够好，考虑方案2（少量历史数据）或方案1（实时订阅）

### 阶段3：最佳方案（如果富途API支持）

- 如果富途API支持实时技术指标订阅，使用订阅方式
- 完全不需要历史K线，且准确性更高

---

## 📝 使用示例

### 示例1：使用默认参数

```python
from quant_system.domain.strategies.selection_realtime import RealtimeSelectionStrategy

strategy = RealtimeSelectionStrategy(
    name="realtime_monitoring",
    config=config,
    broker=broker,
    stock_pool_manager=stock_pool_manager
)

# 执行选股
selected_stocks = strategy.select_stocks()

# 查看结果
for stock in selected_stocks:
    print(f"{stock['symbol']} - {stock['name']} - 评分: {stock['score']:.1f}")
    print(f"  理由: {stock['reason']}")
```

### 示例2：自定义参数

```python
# 在配置中设置参数
config.cond1_volume_amplitude_threshold = 0.04  # 提高振幅阈值到4%
config.cond2_start_range_max = 0.05  # 提高启动涨幅上限到5%

strategy = RealtimeSelectionStrategy(
    name="realtime_monitoring",
    config=config,
    broker=broker,
    stock_pool_manager=stock_pool_manager
)

selected_stocks = strategy.select_stocks()
```

---

## ✅ 总结

已成功实现**方案3：纯实时替代方案**，创建了新的实时数据选股策略。该策略：

1. ✅ 完全基于实时快照数据，不使用历史K线
2. ✅ 实现了两个核心条件的判断逻辑
3. ✅ 支持全市场实时监控
4. ✅ 已注册到策略工厂，可以直接使用

**下一步**：运行策略，验证选股效果，根据实际情况调整参数。


