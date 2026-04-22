            await self.log(f"  盈亏比: {profit_loss_ratio:.2f}")
            await self.log(f"  夏普比率: {sharpe_ratio:.2f}")
            await self.log(f"  收益回撤比: {return_drawdown_ratio:.2f}")
            await self.log(f"  总交易次数: {total_trades}")
            await self.log(f"  盈利次数: {winning_trades} / 亏损次数: {losing_trades}")
            await self.log(f"  平均持仓天数: {average_hold_days:.1f}")

        #  打印完整逐笔交易明细
        if len(merged_trades) > 0:
            await self.log("")
            await self.log("📝 【完整逐笔交易明细】")
            await self.log("股票代码\t股票名称\t策略\t情绪周期\t买入日期\t买入时间\t卖出日期\t卖出时间\t买入价格\t卖出价格\t持股数\t仓位\t持仓天数\t盈亏\t盈亏%\t是否盈利\t策略参数说明")
            await self.log("-----------------------------------------------------------------------------------------------------------------------------------------------------")
            
            #  merged_trades 已经是合并后的完整交易(买入+卖出合并为一笔)
            for idx, trade in enumerate(merged_trades, 1):
                ts_code = trade.get('ts_code', '')
                name = trade.get('name', ts_code)
                strategy = trade.get('strategy', '')
                # strategy 为空改为 "-"（表示无策略说明）
                strategy_name = strategy.strip()
                if not strategy_name:
                    strategy_name = "-"
                # 只取情绪第一部分，"高潮期" 而不是 "高潮期，仓位系数1.0"
                sentiment = trade.get('sentiment', '')
                if sentiment:
                    sentiment = sentiment.split('，')[0].strip()
                sentiment = sentiment or "-"
                buy_date = trade.get('buy_date', '')
                buy_price = float(trade.get('buy_price', 0)) if trade.get('buy_price') is not None else 0.0
                buy_time = trade.get('buy_time', '09:35')  # 使用存储的买入时间
                sell_date = trade.get('sell_date', '')
                sell_price = float(trade.get('sell_price', 0)) if trade.get('sell_price') is not None else 0.0
                sell_time = trade.get('sell_time', '收盘')
                shares = int(trade.get('shares', 0)) if trade.get('shares') is not None else 0
                profit_pct = trade.get('profit_pct')
                
                # 计算持仓天数、盈亏绝对值、是否盈利
                hold_days = 0
                profit_abs = 0
                is_profit = "-"
                if profit_pct is not None and buy_price > 0 and sell_price > 0:
                    profit_abs = shares * (sell_price - buy_price) * (1 - self.SELL_COMMISSION - self.STAMP_TAX)
                    if profit_pct > 0:
                        is_profit = "✅"
                    else:
                        is_profit = "❌"
                    
                    # 计算持仓天数
                    if buy_date and sell_date:
                        from datetime import datetime
                        try:
                            buy_dt = datetime.strptime(str(buy_date), '%Y%m%d')
                            sell_dt = datetime.strptime(str(sell_date), '%Y%m%d')
                            hold_days = (sell_dt - buy_dt).days
                        except:
                            hold_days = 0
                
                # 计算仓位（粗略估算：占总资金百分比）
                position_pct = "-"
                if shares > 0 and buy_price > 0:
                    cost = shares * buy_price
                    position_pct = f"{cost / self._initial_cash * 100:.0f}%"
                
                # 获取策略参数说明
                strategy_desc = strategy_name
                if strategy_name and "半路追涨" in strategy_name:
                    strategy_desc = f"{strategy_name}，涨幅符合要求，量比达标"
                elif not strategy_desc or strategy_desc == "-":
                    strategy_desc = "-"
                
                # 格式化输出，用制表符分隔，对齐更清晰
                profit_abs_str = f"{profit_abs:.0f}" if profit_abs != 0 else "-"
                profit_pct_str = f"{profit_pct:.2f}%" if profit_pct is not None else "-"
                
                await self.log(
                    f"{idx}\t{ts_code}\t{name}\t{strategy_name}\t{sentiment}\t{buy_date}\t{buy_time}\t{sell_date}\t{sell_time}\t{buy_price:.2f}\t{sell_price:.2f}\t{shares}\t{position_pct}\t{hold_days}\t{profit_abs_str}\t{profit_pct_str}\t{is_profit}\t{strategy_desc}"
                )
            
            await self.log("-----------------------------------------------------------------------------------------------------------------------------------------------------")
            await self.log(f"📊 总计 {len(merged_trades)} 笔完整交易")

        # 将 RebalanceRecord 对象转换为字典，方便 MongoDB 序列化
        rebalance_records_dict = []
        for day_records in rebalance_records:
            if isinstance(day_records, list):
                day_dict = []
                for record in day_records:
                    if hasattr(record, '__dict__'):
                        day_dict.append(record.__dict__)
                    else:
                        day_dict.append(record)
                rebalance_records_dict.append(day_dict)
            else:
                if hasattr(day_records, '__dict__'):
                    rebalance_records_dict.append(day_records.__dict__)
                else:
                    rebalance_records_dict.append(day_records)
        
        # 转换 all_trades 也为字典
        all_trades_dict = []
        for record in all_trades:
            if hasattr(record, '__dict__'):
                all_trades_dict.append(record.__dict__)
            else:
                all_trades_dict.append(record)
        
        # 计算净值曲线和每日盈亏
        # 从初始资金开始，记录每个调仓日的组合价值
        net_value_series = []
        # 我们需要重新构建每日净值
        # 由于只有调仓日才有记录，我们只保存调仓日的净值
        current_value = self._initial_cash
        net_value_series.append({
            "trade_date": rebalance_dates[0] if rebalance_dates else start_date,
            "net_value": current_value,
            "daily_profit": 0.0
        })
        
        # 如果有调仓记录，计算每日净值
        # 这里简化处理，只保存每个调仓日的净值
        daily_profit_list = []
        # 第一个点：初始资金
        net_value_series.append({
            "trade_date": str(config.get('start_date')) if rebalance_dates else str(config.get('start_date')),
            "net_value": self._initial_cash,
            "daily_profit": 0.0
        })
        daily_profit_list.append(0.0)
        
        current_value = self._initial_cash
        for i, day_records in enumerate(rebalance_records_dict):
            trade_date = None
            if isinstance(day_records, list) and len(day_records) > 0:
                trade_date = day_records[0].get('date', None) if isinstance(day_records[0], dict) else None
            
            # 计算当日盈亏(简化：基于最终价值反推)
            # 完整计算需要每日期权，这里先提供基础结构
            day_profit = 0.0
            if i == len(rebalance_records_dict) - 1:
                # 最后一天用最终价值
                day_profit = final_value - current_value
                current_value = final_value
            daily_profit_list.append(day_profit)
            
            if trade_date:
                net_value_series.append({
                    "trade_date": trade_date,
                    "net_value": current_value,
                    "daily_profit": day_profit
                })
            # 如果没有 trade_date，仍然添加到序列(保持净值曲线连续)
            elif len(net_value_series) > 0:
                # 和前一天净值相同，盈亏为0
                last_value = net_value_series[-1]['net_value']
                net_value_series.append({
                    "trade_date": str(trade_date) if trade_date else f"day_{i}",
                    "net_value": last_value,
                    "daily_profit": 0.0
                })
                daily_profit_list.append(0.0)
        
        # 计算最大回撤(基于净值曲线)
        max_drawdown = 0.0
        if len(net_value_series) > 1:
            peak = net_value_series[0]['net_value']
            for point in net_value_series:
                if point['net_value'] > peak:
                    peak = point['net_value']
                drawdown = (peak - point['net_value']) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
            # max_drawdown 转换为小数(百分比由前端显示时 ×100)
        
        # 提取 daily_profit 序列
        daily_profit = [point['daily_profit'] for point in net_value_series]
        
        # 计算盈亏比：总盈利 / 总亏损
        # 我们从 daily_profit 统计
        total_profit = 0.0
        total_loss = 0.0
        for p in daily_profit:
            if p > 0:
                total_profit += p
            else:
                total_loss += -p
        
        profit_loss_ratio = 0.0
        if total_loss > 0:
            profit_loss_ratio = total_profit / total_loss
        
        # 计算夏普比率：需要无风险利率，这里简化为 0
        # sharpe_ratio = mean(daily_profit) / std(daily_profit)
        # 暂时简化为 0.0，后续可以完整计算
        sharpe_ratio = 0.0
        
        # 计算 drawdown 序列
        drawdown_series = []
        if len(net_value_series) > 1:
            peak = net_value_series[0]['net_value']
            for point in net_value_series:
                if point['net_value'] > peak:
                    peak = point['net_value']
                drawdown = (peak - point['net_value']) / peak
                drawdown_series.append({
                    "trade_date": point['trade_date'],
                    "drawdown": drawdown
                })
        
        # 返回完整结果(全部为字典，可序列化)
        return {
            "success": True,
            "initial_cash": self._initial_cash,
            "final_cash": cash,
            "final_value": final_value,
            "final_holdings": holdings,
            "total_return": total_return,
            "annualized_return": annualized_return,
            "win_rate": win_rate,
            "total_signals": total_signals,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "profit_loss_ratio": profit_loss_ratio,
            "return_drawdown_ratio": return_drawdown_ratio,
            "average_hold_days": average_hold_days,
            "rebalance_records": rebalance_records_dict,
            "all_trades": all_trades_dict,
            "benchmark_data": benchmark_data,
            "stock_names": stock_names,
            "net_value_series": net_value_series,
            "drawdown_series": drawdown_series,
            "daily_profit": daily_profit,
        }

    async def _load_benchmark_data(self, benchmark_code: str, start_date: int, end_date: int):
        """加载基准指数数据用于计算超额收益"""
        # 从 stock_daily_ak_full 加载基准数据
        # 数据库验证：trade_date 存储为 int 类型
        query = {
            "ts_code": benchmark_code,
            "trade_date": {"$gte": start_date, "$lte": end_date}
        }
        docs = await mongo_manager.find_many("stock_daily_ak_full", query)
        # 按日期排序
        docs.sort(key=lambda x: x["trade_date"])
        benchmark_data = []
        for doc in docs:
            benchmark_data.append({
                "trade_date": doc["trade_date"],
                "close": doc["close"],
                "pct_chg": doc.get("pct_chg", 0.0)
            })
        return benchmark_data

    async def _get_prices(self, ts_codes: set[str], trade_date):
        """批量获取指定股票在指定日期的开盘价和收盘价
        
        Returns:
            dict: {ts_code: {"open": open_price, "close": close_price}}
        """
        # 自动格式标准化：兼容两种输入格式
        # 数据库中 ts_code 带后缀(.SH/.SZ)，所以无论输入什么都转换为带后缀格式
        ts_codes_standard = []
        for code in ts_codes:
            code_str = str(code).strip()
            if code_str.endswith(".SH") or code_str.endswith(".SZ"):
                # 输入已经带后缀，直接使用(匹配数据库)
                ts_codes_standard.append(code_str)
            else:
                # 输入不带后缀，根据代码开头自动补全后缀
                # - 6/5/9 开头 → .SH(上交所)
                # - 其他 → .SZ(深交所)
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    ts_codes_standard.append(f"{code_str}.SH")
                else:
                    ts_codes_standard.append(f"{code_str}.SZ")

        # 修复 MongoDB 复合索引查询 bug：
        # 使用复合索引 (ts_code, trade_date) + $in 查询时，MongoDB 无法正确匹配，总是返回 0 条
        # 所以改为：先按 trade_date 查询，再在内存中过滤 ts_code
        ts_codes_set = set(ts_codes_standard)
        # 🔧 修复：trade_date 从 all_trade_dates 获取是字符串，但数据库存 int，必须转换
        trade_date_int = int(trade_date)
        query = {
            "trade_date": trade_date_int,
        }

        await self.log(f"            🔍 _get_prices: 查询 {len(ts_codes_standard)} 只股票，日期: {trade_date}, 标准化后候选: {sorted(ts_codes_standard)}")

        docs = await mongo_manager.find_many("stock_daily_ak_full", query)
        result = {}
        # 调试：打印每个doc的ts_code，帮助定位问题
        matched = 0
        for doc in docs:
            ts_code_doc = doc["ts_code"]

            # 支持两种格式匹配：
            # 1. 完全匹配(数据库带后缀)
            # 2. 不带后缀匹配(数据库不带后缀，我们带后缀)
            matched_key = None
            if ts_code_doc in ts_codes_set:
                matched_key = ts_code_doc
            else:
                # 尝试去掉后缀再匹配
                if ts_code_doc.endswith('.SH') or ts_code_doc.endswith('.SZ'):
                    ts_code_doc_no_suffix = ts_code_doc[:-3]
                    if ts_code_doc_no_suffix in ts_codes_set:
                        matched_key = ts_code_doc_no_suffix
                else:
                    # 反向匹配：我们带后缀，但数据库不带
                    # 数据库不带后缀，我们带后缀 → 需要找到我们这边对应的候选
                    for candidate in ts_codes_set:
                        if candidate.endswith('.SH') or candidate.endswith('.SZ'):
                            candidate_no_suffix = candidate[:-3]
                            if candidate_no_suffix == ts_code_doc:
                                matched_key = candidate
                                break

            if matched_key:
                result[matched_key] = {
                    "open": doc.get("open", doc["close"]),  # 如果没有open，fallback to close
                    "close": doc["close"]
                }
                matched += 1


        await self.log(f"            ✅ _get_prices: 查询到 {len(result)} 只股票有价格")

        return result

    def _compute_weights(self, candidates: list[str], factor_df, weight_method: str):
        """计算目标权重 - 根据权重方法分配权重"""
        if weight_method == "equal":
            # 等权分配
            weight = 1.0 / len(candidates) if len(candidates) > 0 else 0
            return dict.fromkeys(candidates, weight)
        else:
            # 默认等权
            weight = 1.0 / len(candidates) if len(candidates) > 0 else 0
            return dict.fromkeys(candidates, weight)

    def _rebalance(self, trade_date: int, target_weights: dict[str, float],
                   cash: float, holdings: dict[str, int], prices: dict[str, float], sentiment: str = ""):
        """执行调仓

        Args:
            trade_date: 当前调仓日期
            target_weights: 目标权重 {ts_code: weight}
            cash: 当前现金
            holdings: 当前持仓 {ts_code: shares}
            prices: 当前价格 {ts_code: price}

        Returns:
            (new_cash, new_holdings, records)
        """
        records = []

        # 计算当前总价值
        total_value = cash
        for code, shares in holdings.items():
            if code in prices and shares > 0:
                # 持仓卖出用收盘价估值
                price = prices[code]['close']
                total_value += shares * price

        # 计算目标持仓
        target_shares = {}  # {ts_code: target_shares}
        for code, weight in target_weights.items():
            if code not in prices:
                continue  # 没有价格，无法买入
            target_value = total_value * weight
            price = prices[code]['open']  # 买入用开盘价
            # 向下取整到 100 的倍数(A股买入规则)
            shares = int(int(target_value / price) / 100) * 100
            if shares > 0:
                target_shares[code] = shares

        # 先卖出：不在目标持仓中的股票卖出
        sell_codes = [code for code in holdings if code not in target_shares and holdings[code] > 0]
        for ts_code in sell_codes:
            shares = holdings[ts_code]
            price = prices.get(ts_code, {}).get('close', 0)
            if price <= 0 or shares <= 0:
                continue

            # 计算卖出金额
            gross_amount = shares * price
            commission = max(gross_amount * self.SELL_COMMISSION, self.MIN_COMMISSION)
            stamp_tax = gross_amount * self.STAMP_TAX
            net_amount = gross_amount - commission - stamp_tax

            # 更新现金
            cash += net_amount

            # 记录交易
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="sell",
                ts_code=ts_code,
                shares=shares,
                price=price,  # 卖出用收盘价
                amount=net_amount,
                reason="not_in_target",
                sentiment=sentiment
            ))

            # 清空持仓
            holdings[ts_code] = 0

        # 再买入：目标持仓中需要增加的股票
        for ts_code, target_count in target_shares.items():
            current_shares = holdings.get(ts_code, 0)
            delta = target_count - current_shares

            if delta <= 0:
                continue  # 不需要买入

            price = prices.get(ts_code, {}).get('open', 0)
            if price <= 0:
                continue

            # 计算买入成本
            gross_amount = delta * price
            commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
            total_cost = gross_amount + commission

            if cash < total_cost:
                # 现金不足，按比例缩减
                ratio = cash / total_cost
                delta = int(int(delta * ratio) / 100) * 100
                if delta <= 0:
                    continue
                gross_amount = delta * price
                commission = max(gross_amount * self.BUY_COMMISSION, self.MIN_COMMISSION)
                total_cost = gross_amount + commission

            # 更新现金
            cash -= total_cost

            # 更新持仓
            holdings[ts_code] = current_shares + delta

            # 记录交易
            records.append(RebalanceRecord(
                date=str(trade_date),
                action="buy",
                ts_code=ts_code,
                shares=delta,
                price=price,
                amount=-total_cost,
                reason="rebalance",
                sentiment=sentiment
            ))

        # 清理零持仓
        holdings = {code: shares for code, shares in holdings.items() if shares > 0}

        return cash, holdings, records

    async def _get_stock_names(self, ts_codes: list[str]):
        """批量获取股票名称，使用缓存减少查询"""
        result = {}
        need_query = []

        # 自动格式标准化：适配数据库实际存储格式
        # 数据库中 stock_basic 存储格式：
        #   上海交易所 → sh + 数字 + .SZ   (例如 sh600000.SZ → 浦发银行)
        #   深圳交易所 → sz + 数字 + .SZ   (例如 sz000001.SZ → 平安银行)
        #   北交所 → bj + 数字 + .SZ   (例如 bj920000.SZ → 安徽凤凰)
        for ts_code in ts_codes:
            code_str = str(ts_code).strip()
            
            # 如果输入已经带有交易所前缀+后缀，直接使用
            if code_str.startswith('sh') or code_str.startswith('sz') or code_str.startswith('bj'):
                standard_code = code_str
            elif code_str.endswith(".SH") or code_str.endswith(".SZ"):
                # 输入带后缀但没有交易所前缀 → 添加交易所前缀
                code_only = code_str.split('.')[0]
                if code_only.startswith('6') or code_only.startswith('5') or code_only.startswith('9'):
                    # 上海交易所
                    standard_code = f"sh{code_str}"
                else:
                    # 深圳交易所
                    standard_code = f"sz{code_str}"
            else:
                # 输入既没有前缀也没有后缀 → 添加交易所前缀和后缀
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    standard_code = f"sh{code_str}.SH"
                else:
                    standard_code = f"sz{code_str}.SZ"

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                need_query.append(standard_code)

        # 查询缓存未命中的(已经标准化)
        if len(need_query) > 0:
            docs = await mongo_manager.find_many(
                "stock_basic",
                {"ts_code": {"$in": need_query}},
                {"ts_code": 1, "name": 1}
            )

            for doc in docs:
                standard_code = doc["ts_code"]
                name = doc.get("name", standard_code)
                self._stock_name_cache[standard_code] = name

        # 构建结果，返回给调用方使用原始 ts_code 作为 key
        for ts_code in ts_codes:
            code_str = str(ts_code).strip()
            
            if code_str.startswith('sh') or code_str.startswith('sz') or code_str.startswith('bj'):
                standard_code = code_str
            elif code_str.endswith(".SH") or code_str.endswith(".SZ"):
                code_only = code_str.split('.')[0]
                if code_only.startswith('6') or code_only.startswith('5') or code_only.startswith('9'):
                    standard_code = f"sh{code_str}"
                else:
                    standard_code = f"sz{code_str}"
            else:
                if code_str.startswith('6') or code_str.startswith('5') or code_str.startswith('9'):
                    standard_code = f"sh{code_str}.SH"
                else:
                    standard_code = f"sz{code_str}.SZ"

            if standard_code in self._stock_name_cache:
                result[ts_code] = self._stock_name_cache[standard_code]
            else:
                # 找不到，回退到使用原始代码去掉后缀作为名称
                if '.' in code_str:
                    result[ts_code] = code_str.split('.')[0]
                else:
                    result[ts_code] = code_str

        return result
