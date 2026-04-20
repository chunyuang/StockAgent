#!/usr/bin/env python3
"""
自动重新生成 README.md 的 dashboard 索引
从各个 metadata 目录读取信息，自动生成表格
"""

import os
from datetime import datetime

def read_raw_metadata():
    """读取所有原始数据 metadata"""
    metadata_dir = '/root/.openclaw/workspace/local-databases/raw/metadata'
    result = []
    for f in os.listdir(metadata_dir):
        if not f.endswith('.md'):
            continue
        name = f.replace('.md', '')
        path = os.path.join(metadata_dir, f)
        with open(path, 'r') as mf:
            content = mf.read()
            info = {
                'name': name,
                'version': 'v1',
                'start_date': '',
                'end_date': '',
                'n_stocks': 0,
                'n_days': 0,
                'total_records': 0,
                'created': '',
                'updated': datetime.now().strftime('%Y-%m-%d'),
            }
            for line in content.split('\n'):
                if '| **版本**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '版本' and not p == '项目' and not p == '信息':
                            info['version'] = p
                if '| **起止日期**' in line:
                    parts = line.split('|')
                    for p in parts:
                        if '~' in p:
                            dates = p.split('~')
                            if len(dates) >= 2:
                                info['start_date'] = dates[0].strip()
                                info['end_date'] = dates[1].strip()
                if '| **股票数量**' in line:
                    parts = line.split('|')
                    for p in parts:
                        digits = ''.join([c for c in p if c.isdigit()])
                        if digits:
                            info['n_stocks'] = int(digits)
                if '| **交易日数量**' in line:
                    parts = line.split('|')
                    for p in parts:
                        digits = ''.join([c for c in p if c.isdigit()])
                        if digits:
                            info['n_days'] = int(digits)
                if '| **总日线记录数**' in line:
                    parts = line.split('|')
                    for p in parts:
                        digits = ''.join([c for c in p if c.isdigit()])
                        if digits:
                            info['total_records'] = int(digits)
                if '| **创建时间**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '创建时间' and not p == '项目' and not p == '信息':
                            info['created'] = p
            result.append(info)
    return result

def read_factors_metadata():
    """读取所有因子计算 metadata"""
    metadata_dir = '/root/.openclaw/workspace/local-databases/factors/metadata'
    result = []
    for f in os.listdir(metadata_dir):
        if not f.endswith('.md'):
            continue
        name = f.replace('.md', '')
        path = os.path.join(metadata_dir, f)
        with open(path, 'r') as mf:
            content = mf.read()
            info = {
                'name': name,
                'version': 'v1',
                'raw_dep': '',
                'n_factors': 0,
                'total_records': 0,
                'created': '',
                'updated': datetime.now().strftime('%Y-%m-%d'),
            }
            for line in content.split('\n'):
                if '| **版本**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '版本' and not p == '项目' and not p == '信息':
                            info['version'] = p
                if '| **依赖原始数据**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '依赖原始数据' and not p == '项目' and not p == '信息':
                            info['raw_dep'] = p
                if '| **因子数量**' in line:
                    parts = line.split('|')
                    for p in parts:
                        digits = ''.join([c for c in p if c.isdigit()])
                        if digits:
                            info['n_factors'] = int(digits)
                if '| **总因子记录数**' in line:
                    parts = line.split('|')
                    for p in parts:
                        digits = ''.join([c for c in p if c.isdigit()])
                        if digits:
                            info['total_records'] = int(digits)
                if '| **计算时间**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '计算时间' and not p == '项目' and not p == '信息':
                            info['created'] = p
            result.append(info)
    return result

def read_backtests_metadata():
    """读取所有回测 metadata"""
    metadata_dir = '/root/.openclaw/workspace/local-databases/backtests/metadata'
    result = []
    for f in os.listdir(metadata_dir):
        if not f.endswith('.md'):
            continue
        name = f.replace('.md', '')
        path = os.path.join(metadata_dir, f)
        with open(path, 'r') as mf:
            content = mf.read()
            info = {
                'name': name,
                'version': 'v1',
                'raw_dep': '',
                'factor_dep': '',
                'config': '',
                'created': '',
                'updated': datetime.now().strftime('%Y-%m-%d'),
            }
            for line in content.split('\n'):
                if '| **版本**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '版本' and not p == '项目' and not p == '信息':
                            info['version'] = p
                if '| **依赖原始数据**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '依赖原始数据' and not p == '项目' and not p == '信息':
                            info['raw_dep'] = p
                if '| **依赖因子组合**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '依赖因子组合' and not p == '项目' and not p == '信息':
                            info['factor_dep'] = p
                if '| **回测设置**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '回测设置' and not p == '项目' and not p == '信息':
                            info['config'] = p
                if '| **回测时间**' in line:
                    parts = line.split('|')
                    for p in parts:
                        p = p.strip()
                        if p and not p == '回测时间' and not p == '项目' and not p == '信息':
                            info['created'] = p
            result.append(info)
    return result

def regenerate_readme():
    """重新生成 README.md"""
    raw_list = read_raw_metadata()
    factors_list = read_factors_metadata()
    backtests_list = read_backtests_metadata()
    
    # 读取现有 README，保留头部，替换索引部分
    readme_path = '/root/.openclaw/workspace/local-databases/README.md'
    with open(readme_path, 'r') as f:
        original = f.read()
    
    # 分割，保留 原始数据源列表 之前的部分
    if '## 原始数据源列表' in original:
        before, _ = original.split('## 原始数据源列表', 1)
        new_content = before + """## 原始数据源列表

| 原始数据名称 | 版本 | 起止日期 | 股票数量 | 交易日 | 总记录数 | 创建时间 | 更新时间 |
|--------------|------|----------|----------|------------|----------|----------|------------|
"""
        for raw in raw_list:
            new_content += f"| `{raw['name']}` | {raw['version']} | {raw['start_date']} ~ {raw['end_date']} | {raw['n_stocks']:,} | {raw['n_days']} | {raw['total_records']:,} | {raw['created']} | {raw['updated']} |\n"
        
        new_content += """
## 因子计算列表

| 因子组合名称 | 版本 | 依赖原始数据 | 因子数量 | 总记录数 | 创建时间 | 更新时间 |
|--------------|------|------------------|------------|----------|----------|------------|
"""
        for factor in factors_list:
            new_content += f"| `{factor['name']}` | {factor['version']} | {factor['raw_dep']} | {factor['n_factors']} | {factor['total_records']:,} | {factor['created']} | {factor['updated']} |\n"
        
        new_content += """
## 回测结果列表

| 回测名称 | 版本 | 依赖原始数据 | 依赖因子组合 | 回测配置 | 创建时间 | 更新时间 |
|----------|------|--------------|------------------|----------|----------|------------|
"""
        for backtest in backtests_list:
            new_content += f"| `{backtest['name']}` | {backtest['version']} | {backtest['raw_dep']} | {backtest['factor_dep']} | {backtest['config']} | {backtest['created']} | {backtest['updated']} |\n"
        
        # 保留后面使用方法
        if '## 使用方法' in original:
            _, after = original.split('## 使用方法', 1)
            new_content += """
## 使用方法
""" + after
        else:
            new_content += """
## 使用方法

### 校验数据库

```bash
# 校验原始数据
python3 local-databases/bin/check-db.py --raw 20251215-20260318-akshare

# 校验因子数据
python3 local-databases/bin/check-db.py --factors 20251215-20260318-akshare--21pricefactors

# 同时校验原始和因子
python3 local-databases/bin/check-db.py --raw 20251215-20260318-akshare --factors 20251215-20260318-akshare--21pricefactors
```

### 增量更新

```bash
# 增量更新从上次更新后到今天的数据
python3 local-databases/bin/incremental-update.py --raw 20251215-20260318-akshare

# 指定起止日期
python3 local-databases/bin/incremental-update.py --raw 20251215-20260318-akshare --start 20260301 --end 20260318
```

### 重新生成索引

```bash
# 新增/更新数据库后，重新生成 README 索引
python3 local-databases/bin/regenerate-index.py
```

### 命名规范

- 原始数据: `{start}_{end}_{source}` → 例如 `20251215-20260318-akshare`
- 因子计算: `{raw_name}--{factor_set}` → 例如 `20251215-20260318-akshare--21pricefactors`
- 回测结果: `{raw_name}--{factor_set}--{backtest_config}` → 例如 `20251215-20260318-akshare--21pricefactors--top50-monthly`

使用 `--` 分隔层级，清晰可读。
"""
        
        with open(readme_path, 'w') as f:
            f.write(new_content)
        
        print(f"✅ README regenerated: {readme_path}")
        print(f"  - Raw databases: {len(raw_list)}")
        print(f"  - Factor combinations: {len(factors_list)}")
        print(f"  - Backtests: {len(backtests_list)}")
    else:
        print("❌ Could not find '## 原始数据源列表' in README")

if __name__ == '__main__':
    regenerate_readme()
