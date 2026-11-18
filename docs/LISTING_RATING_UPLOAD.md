# 领星产品监控表统一上传（2026-11-16）

- 上传中心仅保留每日的“领星产品监控表”入口，移除每周独立 Rating 卡片；每周业绩报表及其月份倒序列表不变。
- 每日上传使用原 `/api/reports/listing-prices`，文件名仍包含 `ListingYYYYMMDD`，原始 Excel、价格/变体字段、180 天历史及预览/下载继续保留。新上传必须同时包含 `Rating总数`、`评分`；数字须有限，数量非负且为整数，评分在 0–5 之间。评分空值保持缺失，真实 0 不变。
- 在现有 Listing 锁及文件回滚范围内，从最新日期快照生成兼容 `sources/rating.csv`，同时更新原 rating 索引。该文件是原表的派生数据，不是新的独立上传源。DE/FR/ES/IT 转为原评分计算使用的中文国家，ASIN 按 Listing 原有规则标准化。
- 产品矩阵、新品、补货和批次沿用原评分消费者及聚合规则，不将跨 MSKU 的评分数累加；评分源文件及索引继续触发原有缓存/revision 失效。缺源提示指向领星产品监控表。
- 同日覆盖同步更新评分；补传较旧日期只更新历史，不回退当前评分。同内容重传保持幂等，可补回缺失的评分派生文件，并升级早期未保留评分列的当日标准化快照。
- 评分校验失败不修改任一源；保存快照失败同时还原评分文件、原索引及旧原始文件。既有旧格式快照仍可读取，不为了补列批量重解析历史 Excel。没有合并表前保留已有 Rating 数据；下次成功上传合并表时更新。
- 旧 Rating API/存储键保留兼容，前端不再提供独立上传、删除入口。本轮不自动导入用户附件或迁移真实评分数据。

实现入口：`backend/listing_prices.py`、`backend/dashboard_api.py`、`frontend/src/UploadCenter.tsx`。回归入口：`tests/test_listing_rating_upload.py`、`frontend/src/UploadCenter.test.tsx`。
