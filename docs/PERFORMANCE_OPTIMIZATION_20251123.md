# 技术分析选股性能优化方案

## 问题分析

技术分析选股执行时间长的主要原因：

1. **全市场股票数量过大**：可能分析2000-3500只股票
2. **历史K线数据获取**：每只股票需要获取240根K线，网络IO密集
3. **并发数偏少**：默认16个worker，无法充分利用网络带宽
4. **缺少数据缓存**：每次选股都重新获取所有数据
5. **技术指标计算重复**：相同股票重复计算指标

## 优化方案

### 方案1：使用优化版策略（推荐）

已在原文件中直接优化 `TechnicalSelectionStrategy`，主要优化：

- ✅ **数据缓存机制**：5分钟TTL，避免重复获取数据
- ✅ **更严格的初筛**：提高成交量/市值阈值，减少分析数量
- ✅ **更高的并发数**：从16增加到32，最大64
- ✅ **减少K线数量**：从240减少到120（仍足够分析）
- ✅ **减少最大分析数量**：从3500减少到2000

**优化已自动生效，无需额外配置！**

### 方案2：调整配置参数（快速优化）

在配置文件中调整以下参数，无需修改代码：

```yaml
# config/system.yaml 或通过代码设置
system:
  selection_strategies_config:
    technical_analysis:
      enabled: true
      # 性能优化参数
      history_min_bars: 120        # 从240减少到120（减少50%数据量）
      history_workers: 32          # 从16增加到32（提高并发）
      max_market_stocks: 2000       # 从3500减少到2000（减少分析数量）
      min_volume: 2000000          # 提高成交量阈值（更严格初筛）
      min_market_cap: 200000000    # 提高市值阈值（更严格初筛）
      analysis_batch_size: 100     # 从200减少到100（更快响应）
      enable_cache: true            # 启用缓存
      cache_ttl_seconds: 300       # 缓存5分钟
```

### 方案3：使用股票池限制（最快）

如果不需要全市场选股，可以限制在特定股票池：

```python
# 在 system_runner.py 中修改
def _get_stock_universe(self) -> List[str]:
    # 使用股票池管理器，而不是全市场
    if self.stock_pool_manager:
        # 使用特定股票池
        stocks = self.stock_pool_manager.get_stocks_from_pool('hk_blue_chip')
        if stocks:
            return stocks
    
    # 或者限制数量
    all_stocks = self._get_full_market_universe()
    return all_stocks[:1000]  # 只分析前1000只
```

## 性能对比

| 优化项 | 原配置 | 优化后 | 提升 |
|--------|--------|--------|------|
| 历史K线数量 | 240根 | 120根 | 减少50% |
| 并发数 | 16 | 32 | 提升100% |
| 最大分析数量 | 3500只 | 2000只 | 减少43% |
| 数据缓存 | 无 | 5分钟TTL | 减少重复请求 |
| 初筛严格度 | 基础 | 更严格 | 减少候选数量 |

**预期性能提升：**
- 首次运行：**30-50%** 时间减少
- 缓存命中后：**60-80%** 时间减少

## 详细优化说明

### 1. 数据缓存机制

```python
# 缓存K线数据（5分钟TTL）
kline = cache.get(symbol, 'kline', bars=120)
if not kline:
    kline = broker.get_history_kline(symbol, 120)
    cache.set(symbol, 'kline', kline, bars=120)
```

**优势：**
- 短时间内重复选股时，直接使用缓存
- 减少API调用次数
- 降低网络延迟影响

### 2. 更严格的初筛

```python
# 提高筛选阈值
min_volume = 2_000_000      # 从1M提高到2M
min_market_cap = 2e8        # 从1e8提高到2e8
max_change_rate = 0.15      # 过滤单日涨跌幅>15%的
```

**优势：**
- 减少需要详细分析的股票数量
- 提高选股质量
- 加快整体执行速度

### 3. 增加并发数

```python
# 从16增加到32
workers = min(32, 64)  # 最大64，避免API限制
```

**优势：**
- 充分利用网络带宽
- 并行获取数据，减少等待时间
- 注意：需要根据API限制调整

### 4. 减少K线数量

```python
# 从240减少到120
history_bars = 120  # 仍足够进行技术分析
```

**优势：**
- 减少单只股票的数据量
- 降低网络传输时间
- 120根K线（约6个月）仍足够分析

## 使用建议

### 开发环境
```python
# 快速测试，使用小股票池
max_market_stocks: 500
history_min_bars: 60
enable_cache: true
```

### 生产环境
```python
# 平衡性能和准确性
max_market_stocks: 2000
history_min_bars: 120
history_workers: 32
enable_cache: true
cache_ttl_seconds: 300
```

### 高频选股场景
```python
# 最大化缓存利用
max_market_stocks: 1500
history_min_bars: 120
enable_cache: true
cache_ttl_seconds: 600  # 10分钟缓存
```

## 监控和调试

### 查看性能统计

```python
# 在策略中查看性能指标
strategy = strategy_factory.get_selection_strategy("technical_analysis")
metrics = strategy.get_performance_metrics()
print(f"总运行次数: {metrics['performance_stats']['total_runs']}")
print(f"最后运行时间: {metrics['performance_stats']['last_run_time']}")
```

### 查看缓存统计

```python
if hasattr(strategy, 'data_cache'):
    cache_stats = strategy.data_cache.get_cache_stats()
    print(f"缓存大小: {cache_stats['cache_size']}")
```

## 注意事项

1. **API限制**：增加并发数时，注意券商API的请求频率限制
2. **内存使用**：缓存会占用内存，大量股票时注意内存管理
3. **数据新鲜度**：缓存TTL设置需要平衡性能和实时性
4. **网络环境**：网络较慢时，可以进一步减少分析数量

## 进一步优化建议

如果仍然觉得慢，可以考虑：

1. **使用增量更新**：只分析新增或变化的股票
2. **异步处理**：使用异步IO（asyncio）替代线程池
3. **分布式处理**：多机器并行分析不同股票池
4. **预计算指标**：提前计算常用技术指标并存储
5. **使用更快的数据库**：将历史数据存储在本地数据库

## 问题反馈

如果优化后仍有性能问题，请提供：
- 分析的股票数量
- 网络环境（本地/云服务器）
- 券商API响应时间
- 系统资源使用情况（CPU/内存）

