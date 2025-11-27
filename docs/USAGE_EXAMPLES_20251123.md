# 新架构使用示例 - 2025-11-23

## 📚 快速开始

### 1. 使用依赖注入容器

```python
from quant_system.core.bootstrap import bootstrap_system, get_broker, get_strategy_factory

# 引导系统（自动配置所有依赖）
container = bootstrap_system()

# 获取服务
broker = get_broker()
strategy_factory = get_strategy_factory()
```

### 2. 手动配置容器

```python
from quant_system.core.container import get_container
from quant_system.core.interfaces import IBroker, IStrategyFactory
from quant_system.infrastructure.brokers.futu_link import FutuBroker
from quant_system.domain.strategies.strategy_factory import StrategyFactory
from quant_system.core.config import ConfigManager

container = get_container()
config = ConfigManager()

# 注册服务
container.register_singleton(IBroker, FutuBroker)
container.register_singleton(IStrategyFactory, StrategyFactory)

# 解析依赖
broker = container.resolve(IBroker)
factory = container.resolve(IStrategyFactory)
```

### 3. 使用Repository访问数据

```python
from quant_system.core.bootstrap import get_stock_repository

# 获取Repository
repo = get_stock_repository()

# 获取股票列表
stocks = repo.get_stock_list('HK', 'STOCK')

# 获取历史K线
kline = repo.get_history_kline('HK.00700', ktype='K_DAY', max_count=100)

# 获取市场快照
snapshot = repo.get_market_snapshot(['HK.00700', 'HK.00005'])
```

---

## 🔧 实际应用示例

### 示例1：在策略中使用Repository

```python
from quant_system.core.bootstrap import get_stock_repository
from quant_system.core.interfaces import IStockRepository

class MyStrategy:
    def __init__(self, stock_repo: IStockRepository):
        self.stock_repo = stock_repo
    
    def select_stocks(self):
        # 使用Repository获取数据，而不是直接调用Broker
        stocks = self.stock_repo.get_stock_list('HK', 'STOCK')
        
        # 分析股票
        for symbol in stocks[:10]:
            kline = self.stock_repo.get_history_kline(symbol)
            # ... 分析逻辑
```

### 示例2：测试中使用Mock

```python
from unittest.mock import Mock
from quant_system.core.container import get_container, reset_container
from quant_system.core.interfaces import IBroker

def test_my_strategy():
    # 重置容器
    reset_container()
    container = get_container()
    
    # 创建Mock Broker
    mock_broker = Mock(spec=IBroker)
    mock_broker.get_account_info.return_value = {'total_assets': 1000000}
    
    # 注册Mock
    container.register_instance(IBroker, mock_broker)
    
    # 测试代码
    broker = container.resolve(IBroker)
    assert broker.get_account_info()['total_assets'] == 1000000
```

### 示例3：替换实现

```python
from quant_system.core.container import get_container
from quant_system.core.interfaces import IBroker

# 假设你有一个新的券商实现
class NewBroker(IBroker):
    # ... 实现接口方法
    pass

# 替换实现
container = get_container()
container.register_singleton(IBroker, NewBroker)

# 现在所有使用IBroker的地方都会使用NewBroker
broker = container.resolve(IBroker)
```

---

## 🧪 运行测试

### 安装测试依赖

```bash
pip install -r requirements-dev.txt
```

### 运行所有测试

```bash
pytest
```

### 运行特定测试

```bash
# 运行容器测试
pytest tests/unit/test_container.py

# 运行单元测试
pytest tests/unit/

# 查看覆盖率
pytest --cov=quant_system --cov-report=html
```

---

## 📝 最佳实践

### 1. 使用接口而不是具体类

```python
# ✅ 好的做法
def process_stocks(broker: IBroker):
    pass

# ❌ 不好的做法
def process_stocks(broker: FutuBroker):
    pass
```

### 2. 通过容器获取依赖

```python
# ✅ 好的做法
from quant_system.core.bootstrap import get_broker
broker = get_broker()

# ❌ 不好的做法
broker = FutuBroker(config)
```

### 3. 使用Repository访问数据

```python
# ✅ 好的做法
from quant_system.core.bootstrap import get_stock_repository
repo = get_stock_repository()
stocks = repo.get_stock_list('HK', 'STOCK')

# ❌ 不好的做法
stocks = broker.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
```

---

## 🎯 迁移指南

### 从旧代码迁移到新架构

#### 步骤1：更新导入

```python
# 旧代码
from quant_system.infrastructure.brokers.futu_link import FutuBroker
broker = FutuBroker(config)

# 新代码
from quant_system.core.bootstrap import get_broker
broker = get_broker()
```

#### 步骤2：使用接口类型注解

```python
# 旧代码
def my_function(broker: FutuBroker):
    pass

# 新代码
from quant_system.core.interfaces import IBroker
def my_function(broker: IBroker):
    pass
```

#### 步骤3：使用Repository

```python
# 旧代码
stocks = broker.get_stock_basicinfo(Market.HK, SecurityType.STOCK)

# 新代码
from quant_system.core.bootstrap import get_stock_repository
repo = get_stock_repository()
stocks = repo.get_stock_list('HK', 'STOCK')
```

---

## ✅ 总结

新架构提供了：

1. **依赖注入** - 统一管理依赖关系
2. **接口抽象** - 提高可测试性和可扩展性
3. **Repository模式** - 统一数据访问
4. **测试框架** - 保证代码质量

这些改进让代码更加：
- ✅ **可测试** - 可以轻松注入Mock对象
- ✅ **可扩展** - 可以轻松替换实现
- ✅ **可维护** - 依赖关系清晰
- ✅ **可复用** - 接口定义明确


