// 检查 20260105 昨日涨停数量
db = db.getSiblingDB('stock_agent');

var checkDate = 20260106;
var yesterday = db.stock_daily.aggregate([
  {$match: {trade_date: {$lt: checkDate}, source: "ak"}},
  {$group: {_id: null, max_date: {$max: "$trade_date"}}},
]).toArray();

var y = yesterday[0].max_date;
print("Yesterday date: " + y);

var count = db.stock_daily.countDocuments({
  trade_date: y,
  source: "ak",
  $where: "this.close >= this.up_limit * 0.998"
});

print("Yesterday limit-up count: " + count);
