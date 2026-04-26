#!/usr/bin/env python3
"""
策略参数优化器
功能：基于历史数据自动优化策略参数，支持网格搜索、遗传算法、随机搜索，找到最优参数组合
"""
import sys
import os
import asyncio
import itertools
import random
from datetime import datetime
from typing import List, Dict, Tuple
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'AgentServer'))  # FIXME: 使用sys.path.insert做模块查找是反模式，应改用setup.py/pyproject.toml将项目安装到venv中
sys.path.insert(0, os.path.dirname(__file__))

from backtest_module.backtest_engine.factor_selection.portfolio_backtest import PortfolioBacktester

class StrategyOptimizer:
    """策略参数优化器"""
    
    def __init__(self, base_config: Dict):
        """
        初始化优化器
        base_config: 基础回测配置，固定不变的参数
        """
        self.base_config = base_config
        self.backtester = PortfolioBacktester(source="ak")
        self.results: List[Dict] = []
    
    async def grid_search(self, param_grid: Dict[str, List]) -> List[Dict]:
        """网格搜索：遍历所有参数组合"""
        print(f"🚀 开始网格搜索，参数组合数：{self._calc_combination_count(param_grid)}")
        
        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        
        total = len(list(itertools.product(*param_values)))
        for idx, combination in enumerate(itertools.product(*param_values)):
            params = dict(zip(param_names, combination))
            print(f"[{idx+1}/{total}] 测试参数组合：{params}")
            
            # 运行回测
            result = await self._run_backtest(params)
            if result:
                self.results.append(result)
                # 打印当前最优
                self._print_current_best()
        
        # 按收益率排序
        self.results.sort(key=lambda x: x["total_return"], reverse=True)
        return self.results
    
    async def random_search(self, param_ranges: Dict[str, Tuple], n_iter: int = 100) -> List[Dict]:
        """随机搜索：在参数范围内随机采样n次，适合大范围参数空间"""
        print(f"🚀 开始随机搜索，迭代次数：{n_iter}")
        
        for i in range(n_iter):
            # 随机生成参数
            params = {}
            for name, (min_val, max_val, dtype) in param_ranges.items():
                if dtype == "int":
                    params[name] = random.randint(min_val, max_val)
                elif dtype == "float":
                    params[name] = round(random.uniform(min_val, max_val), 4)
                elif dtype == "bool":
                    params[name] = random.choice([True, False])
            
            print(f"[{i+1}/{n_iter}] 测试参数组合：{params}")
            
            # 运行回测
            result = await self._run_backtest(params)
            if result:
                self.results.append(result)
                # 打印当前最优
                if (i+1) % 10 == 0:
                    self._print_current_best()
        
        # 按收益率排序
        self.results.sort(key=lambda x: x["total_return"], reverse=True)
        return self.results
    
    async def genetic_algorithm(self, param_ranges: Dict[str, Tuple], pop_size: int = 50, 
                                 generations: int = 20, mutation_rate: float = 0.1) -> List[Dict]:
        """遗传算法优化：适合复杂参数空间，收敛更快"""
        print(f"🚀 开始遗传算法优化，种群大小：{pop_size}，迭代代数：{generations}")
        
        # 初始化种群
        population = self._generate_population(param_ranges, pop_size)
        
        for gen in range(generations):
            print(f"\n📈 第{gen+1}代进化：")
            
            # 评估种群
            evaluated = []
            for idx, params in enumerate(population):
                print(f"评估个体 {idx+1}/{pop_size}：{params}")
                result = await self._run_backtest(params)
                if result:
                    evaluated.append((result["total_return"], params, result))
            
            # 按适应度排序
            evaluated.sort(key=lambda x: x[0], reverse=True)
            top_performers = evaluated[:int(pop_size * 0.3)]  # 前30%保留
            
            print(f"当前代最优收益：{top_performers[0][0]:.2f}%，参数：{top_performers[0][1]}")
            
            # 保存结果
            for fitness, params, result in top_performers:
                self.results.append(result)
            
            if gen == generations - 1:
                break  # 最后一代不生成新种群
            
            # 生成下一代
            new_population = []
            # 保留精英
            for _, params, _ in top_performers[:int(pop_size * 0.1)]:
                new_population.append(params.copy())
            
            # 交叉和变异
            while len(new_population) < pop_size:
                # 选择父母
                parent1 = self._select_parent(top_performers)
                parent2 = self._select_parent(top_performers)
                
                # 交叉
                child = self._crossover(parent1, parent2)
                
                # 变异
                if random.random() < mutation_rate:
                    child = self._mutate(child, param_ranges)
                
                new_population.append(child)
            
            population = new_population
        
        # 去重并排序
        self._deduplicate_results()
        self.results.sort(key=lambda x: x["total_return"], reverse=True)
        return self.results
    
    async def _run_backtest(self, params: Dict) -> Optional[Dict]:
        """运行单次回测并返回结果"""
        try:
            # 合并配置
            config = {**self.base_config, **params}
            
            # 运行回测
            result = await self.backtester.run(config)
            
            if "error" in result:
                print(f"❌ 回测失败：{result['error']}")
                return None
            
            perf = result["performance"]
            
            return {
                "params": params,
                "total_return": perf["total_return"],
                "sharpe_ratio": perf["sharpe_ratio"],
                "max_drawdown": perf["max_drawdown"],
                "win_rate": perf["win_rate"],
                "profit_loss_ratio": perf.get("profit_loss_ratio", 0),
                "total_trades": perf["trade_days"],
                "performance": perf
            }
        
        except Exception as e:
            print(f"❌ 回测异常：{e}")
            return None
    
    def _calc_combination_count(self, param_grid: Dict[str, List]) -> int:
        """计算参数组合数"""
        count = 1
        for vals in param_grid.values():
            count *= len(vals)
        return count
    
    def _generate_population(self, param_ranges: Dict[str, Tuple], pop_size: int) -> List[Dict]:
        """生成初始种群"""
        population = []
        for _ in range(pop_size):
            params = {}
            for name, (min_val, max_val, dtype) in param_ranges.items():
                if dtype == "int":
                    params[name] = random.randint(min_val, max_val)
                elif dtype == "float":
                    params[name] = round(random.uniform(min_val, max_val), 4)
                elif dtype == "bool":
                    params[name] = random.choice([True, False])
            population.append(params)
        return population
    
    def _select_parent(self, top_performers: List) -> Dict:
        """轮盘赌选择父母"""
        total_fitness = sum(max(0.1, fit) for fit, _, _ in top_performers)
        pick = random.uniform(0, total_fitness)
        current = 0
        for fit, params, _ in top_performers:
            current += max(0.1, fit)
            if current > pick:
                return params.copy()
        return top_performers[0][1].copy()
    
    def _crossover(self, parent1: Dict, parent2: Dict) -> Dict:
        """交叉操作"""
        child = {}
        for key in parent1.keys():
            if random.random() < 0.5:
                child[key] = parent1[key]
            else:
                child[key] = parent2[key]
        return child
    
    def _mutate(self, params: Dict, param_ranges: Dict[str, Tuple]) -> Dict:
        """变异操作"""
        key = random.choice(list(params.keys()))
        min_val, max_val, dtype = param_ranges[key]
        
        if dtype == "int":
            params[key] = random.randint(min_val, max_val)
        elif dtype == "float":
            params[key] = round(random.uniform(min_val, max_val), 4)
        elif dtype == "bool":
            params[key] = not params[key]
        
        return params
    
    def _deduplicate_results(self):
        """结果去重"""
        seen = set()
        unique = []
        for res in self.results:
            param_str = str(sorted(res["params"].items()))
            if param_str not in seen:
                seen.add(param_str)
                unique.append(res)
        self.results = unique
    
    def _print_current_best(self):
        """打印当前最优结果"""
        if not self.results:
            return
        
        best = max(self.results, key=lambda x: x["total_return"])
        print(f"🌟 当前最优：收益{best['total_return']:.2f}%，夏普{best['sharpe_ratio']:.2f}，最大回撤{best['max_drawdown']:.2f}%，参数：{best['params']}")
    
    def get_top_results(self, top_n: int = 10) -> List[Dict]:
        """获取前N名最优结果"""
        return self.results[:top_n]
    
    def generate_optimization_report(self, output_file: str = None) -> str:
        """生成优化报告"""
        if not self.results:
            return "ℹ️  无优化结果"
        
        top10 = self.get_top_results(10)
        
        report_lines = [
            "# 🎯 策略参数优化报告",
            "",
            "## 🔹 基础配置",
            f"- 回测区间：{self.base_config['start_date']} ~ {self.base_config['end_date']}",
            f"- 初始资金：{self.base_config['initial_cash']:.0f}元",
            f"- 共测试参数组合：{len(self.results)}组",
            f"- 报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 🏆 TOP 10 最优参数组合",
            "",
            "| 排名 | 总收益率 | 夏普比率 | 最大回撤 | 胜率 | 交易次数 | 参数组合 |",
            "|------|----------|----------|----------|------|----------|----------|",
        ]
        
        for idx, res in enumerate(top10, 1):
            param_str = "，".join([f"{k}={v}" for k, v in res["params"].items()])
            report_lines.append(
                f"| {idx} | {res['total_return']:.2f}% | {res['sharpe_ratio']:.2f} | {res['max_drawdown']:.2f}% | {res['win_rate']:.2f}% | {res['total_trades']} | {param_str} |"
            )
        
        # 参数重要性分析
        report_lines.extend([
            "",
            "## 💡 参数优化建议",
            self._generate_optimization_suggestions(),
        ])
        
        # 推荐最优参数
        best = top10[0]
        report_lines.extend([
            "",
            "## ✅ 推荐最优参数",
            "```python",
            f"best_params = {best['params']}",
            "```",
            f"**预期表现：** 收益率{best['total_return']:.2f}%，夏普比率{best['sharpe_ratio']:.2f}，最大回撤{best['max_drawdown']:.2f}%，胜率{best['win_rate']:.2f}%",
        ])
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ 优化报告已保存到：{output_file}")
        
        return report
    
    def _generate_optimization_suggestions(self) -> str:
        """生成优化建议"""
        if len(self.results) < 10:
            return "- 测试参数组合较少，建议增加测试数量"
        
        suggestions = []
        
        # 分析每个参数对收益的影响
        param_names = list(self.results[0]["params"].keys())
        for param in param_names:
            # 按参数值分组计算平均收益
            param_values = {}
            for res in self.results:
                val = res["params"][param]
                if val not in param_values:
                    param_values[val] = []
                param_values[val].append(res["total_return"])
            
            if len(param_values) < 2:
                continue
            
            # 计算每个值的平均收益
            value_returns = {v: np.mean(returns) for v, returns in param_values.items()}
            best_val = max(value_returns.items(), key=lambda x: x[1])
            worst_val = min(value_returns.items(), key=lambda x: x[1])
            
            diff = best_val[1] - worst_val[1]
            if diff > 5:  # 收益差超过5%，说明参数影响大
                suggestions.append(f"- ⭐ **{param}** 参数对收益影响大，最优值`{best_val[0]}`（比最差值高{diff:.2f}%收益），建议重点优化")
            elif diff > 2:
                suggestions.append(f"- ✅ **{param}** 参数对收益有一定影响，最优值`{best_val[0]}`")
            else:
                suggestions.append(f"- ℹ️  **{param}** 参数对收益影响较小，可以固定为推荐值`{best_val[0]}`")
        
        return "\n".join(suggestions)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="策略参数优化器")
    parser.add_argument("--method", required=True, choices=["grid", "random", "genetic"], 
                        help="优化方法：grid(网格搜索)/random(随机搜索)/genetic(遗传算法)")
    parser.add_argument("--start-date", required=True, help="回测开始日期(YYYYMMDD)")
    parser.add_argument("--end-date", required=True, help="回测结束日期(YYYYMMDD)")
    parser.add_argument("--initial-cash", type=float, default=1000000, help="初始资金，默认100万")
    parser.add_argument("--top-n", type=int, default=10, help="显示前N名结果，默认10")
    parser.add_argument("--output", help="输出报告文件路径")
    parser.add_argument("--iters", type=int, default=100, help="随机搜索/遗传算法迭代次数，默认100")
    parser.add_argument("--pop-size", type=int, default=50, help="遗传算法种群大小，默认50")
    
    args = parser.parse_args()
    
    # 基础配置
    base_config = {
        "universe": "all_a",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "initial_cash": args.initial_cash,
        "rebalance_freq": "daily",
        "top_n": 5,
        "weight_method": "equal",
        "factors": [
            {"name": "momentum_5d", "weight": 0.2},
            {"name": "volume_increase", "weight": 0.2},
            {"name": "limit_up_count", "weight": 0.2},
            {"name": "turnover_rate", "weight": 0.15},
            {"name": "volatility_20d", "weight": 0.15},
        ],
        "exclude": ["st", "new_stock"],
    }
    
    optimizer = StrategyOptimizer(base_config)
    
    # 示例参数配置（实际使用时根据需要修改）
    async def main():
        if args.method == "grid":
            # 网格搜索参数示例
            param_grid = {
                "max_position": [0.5, 0.7, 0.9],
                "stop_loss_pct": [0.03, 0.05, 0.08],
                "take_profit_pct": [0.08, 0.1, 0.15],
                "max_hold_days": [2, 3, 5],
                "liquidity_threshold": [3000000, 5000000, 10000000],
            }
            await optimizer.grid_search(param_grid)
        
        elif args.method == "random":
            # 随机搜索参数示例（min, max, type）
            param_ranges = {
                "max_position": (0.4, 0.9, "float"),
                "stop_loss_pct": (0.02, 0.1, "float"),
                "take_profit_pct": (0.05, 0.2, "float"),
                "max_hold_days": (2, 7, "int"),
                "liquidity_threshold": (1000000, 10000000, "int"),
                "enable_auction_filter": (False, True, "bool"),
            }
            await optimizer.random_search(param_ranges, args.iters)
        
        elif args.method == "genetic":
            # 遗传算法参数示例
            param_ranges = {
                "max_position": (0.4, 0.9, "float"),
                "stop_loss_pct": (0.02, 0.1, "float"),
                "take_profit_pct": (0.05, 0.2, "float"),
                "max_hold_days": (2, 7, "int"),
                "liquidity_threshold": (1000000, 10000000, "int"),
                "enable_auction_filter": (False, True, "bool"),
            }
            await optimizer.genetic_algorithm(param_ranges, args.pop_size, args.iters)
        
        # 打印结果
        print("\n" + "="*80)
        print(optimizer.generate_optimization_report(args.output))
        print("="*80)
    
    asyncio.run(main())
