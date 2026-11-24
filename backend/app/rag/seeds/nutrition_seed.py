"""Seed nutrition knowledge base.

Source attribution mostly drawn from:
  - 中国食物成分表（标准版第6版，2018）— 节选数值近似
  - USDA FoodData Central — 节选数值近似
  - WHO/Chinese Nutrition Society 公开指南
  - American College of Sports Medicine (ACSM) 公开建议

NOT a medical source. Numbers are educational approximations.
For each fact we include enough specifics for BM25 to retrieve well.
"""

from __future__ import annotations

from ..retriever import Document


def build_nutrition_corpus() -> list[Document]:
    return [
        # ---------- 食物成分（每 100g） ----------
        Document(
            id="food:鸡蛋",
            text="鸡蛋（每100g煮熟）：能量 144 kcal，蛋白质 13.3g，脂肪 8.8g，碳水 1.1g，"
                 "胆固醇较高（约 372 mg），减脂期可只吃 1 个全蛋 + 2 个蛋白替代。",
            source="中国食物成分表（标准版第6版，2018）",
            tags=("food", "protein", "low_carb"),
        ),
        Document(
            id="food:鸡胸肉",
            text="鸡胸肉（每100g熟）：能量 165 kcal，蛋白质 31g，脂肪 3.6g，碳水 0g。"
                 "高蛋白低脂的代表，适合减脂与增肌。建议煎烤少油，避免裹粉炸制。",
            source="USDA FoodData Central",
            tags=("food", "protein", "lean"),
        ),
        Document(
            id="food:三文鱼",
            text="三文鱼（每100g）：能量 208 kcal，蛋白质 20g，脂肪 13g（含 EPA+DHA 约 2g）。"
                 "Omega-3 EPA/DHA 对心血管与抗炎有益，每周建议 2 次，每次 100-150g。",
            source="USDA FoodData Central + AHA 推荐",
            tags=("food", "protein", "omega3"),
        ),
        Document(
            id="food:牛油果",
            text="牛油果（每100g）：能量 160 kcal，脂肪 14.7g（多为单不饱和脂肪酸），"
                 "膳食纤维 6.7g，碳水 8.5g（净碳水仅 1.8g）。脂肪密度高，减脂期建议每日 1/4 个。",
            source="USDA FoodData Central",
            tags=("food", "fat", "fiber", "low_carb"),
        ),
        Document(
            id="food:坚果混合",
            text="混合坚果（每100g）：能量约 580-650 kcal，脂肪 50-60g，蛋白 15-20g，碳水 15-20g。"
                 "热量密度极高，每日建议不超过 25g（约一把），优选无盐烘焙原味。",
            source="中国食物成分表 + 中国居民膳食指南2022",
            tags=("food", "fat", "snack"),
        ),
        Document(
            id="food:糙米",
            text="糙米（每100g熟）：能量 110 kcal，蛋白 2.6g，碳水 23g，纤维 1.8g。"
                 "GI（升糖指数）约 50，比白米饭（GI 73）更稳血糖，减脂期建议替代部分白米。",
            source="中国食物成分表 + GI 数据库",
            tags=("food", "carb", "low_gi"),
        ),
        Document(
            id="food:燕麦",
            text="燕麦片（每100g干）：能量 389 kcal，蛋白 17g，碳水 66g，β-葡聚糖纤维 4-7g。"
                 "β-葡聚糖证据较强，每日 3g 可帮助降低 LDL 胆固醇约 5-7%。",
            source="EFSA 健康声称授权 + 中国食物成分表",
            tags=("food", "carb", "fiber", "heart"),
        ),
        Document(
            id="food:豆腐",
            text="北豆腐（每100g）：能量 116 kcal，蛋白质 12.2g，脂肪 4.8g，钙 138mg。"
                 "植物蛋白来源，适合素食者；煎煮少油可作为鸡胸的低成本替代。",
            source="中国食物成分表",
            tags=("food", "protein", "vegetarian"),
        ),
        Document(
            id="food:希腊酸奶",
            text="无糖希腊酸奶（每100g）：能量 59 kcal，蛋白 10g，碳水 3.6g，脂肪 0.4g。"
                 "蛋白密度比普通酸奶高约 2 倍，含活性益生菌，适合早餐或运动后加餐。",
            source="USDA FoodData Central",
            tags=("food", "protein", "dairy"),
        ),
        Document(
            id="food:番茄炒蛋",
            text="番茄炒蛋（家常做法每份约 280g）：能量 280-320 kcal，蛋白 16-18g，"
                 "脂肪 18-22g（用油量是变量），碳水 8-10g。建议用油不超 1 茶匙（5g）。",
            source="中国食物成分表 + 家常烹饪估算",
            tags=("food", "homecook"),
        ),
        Document(
            id="food:米饭",
            text="白米饭（每100g熟）：能量 130 kcal，蛋白 2.7g，碳水 28g，脂肪 0.3g。"
                 "GI 约 73 偏高；建议混合糙米/藜麦比例 1:1 以平稳血糖。",
            source="中国食物成分表",
            tags=("food", "carb"),
        ),
        Document(
            id="food:全麦面包",
            text="全麦面包（每100g）：能量 247 kcal，蛋白 13g，碳水 41g，纤维 6g。"
                 "选购时认准成分表第一位为'全麦粉'，许多商品仅着色添加。",
            source="中国食物成分表 + 选购指南",
            tags=("food", "carb", "fiber"),
        ),
        Document(
            id="food:玉米",
            text="鲜玉米（每100g）：能量 86 kcal，蛋白 3.2g，碳水 19g，纤维 2.7g。"
                 "黄玉米富含叶黄素，对眼健康有益；甜玉米 GI 约 52，蒸煮即可。",
            source="USDA FoodData Central",
            tags=("food", "carb", "fiber"),
        ),
        Document(
            id="food:绿叶蔬菜",
            text="深色绿叶蔬菜（菠菜/羽衣甘蓝/西兰花，每100g）：能量 23-35 kcal，"
                 "纤维 2-3g，富含维生素 K、叶酸、镁。每日建议 300-500g 蔬菜，深色占一半。",
            source="中国居民膳食指南2022",
            tags=("food", "vegetable", "fiber"),
        ),
        Document(
            id="food:圣女果",
            text="圣女果（每100g）：能量 18 kcal，碳水 3.9g，纤维 1.2g，富含番茄红素与维C。"
                 "可作为减脂期甜味替代，建议每日不超 200g。",
            source="USDA FoodData Central",
            tags=("food", "vegetable", "low_kcal"),
        ),
        Document(
            id="food:香蕉",
            text="香蕉（每100g）：能量 89 kcal，碳水 22.8g，钾 358mg。"
                 "运动前 30-60 分钟食用可补糖原；脚抽筋多与电解质失衡相关，钾的补充有帮助。",
            source="USDA + ACSM",
            tags=("food", "carb", "potassium", "post_workout"),
        ),

        # ---------- 营养原则 ----------
        Document(
            id="principle:protein_target_general",
            text="一般成年人蛋白质推荐摄入 0.8-1.0 g/kg/天；力量训练人群建议 1.6-2.2 g/kg/天，"
                 "分散到 3-5 餐每餐 25-40g 最佳，单餐 >40g 蛋白合成边际效益递减。",
            source="ISSN Position Stand: Protein and Exercise (2017)",
            tags=("principle", "protein", "muscle"),
        ),
        Document(
            id="principle:protein_target_cut",
            text="减脂期为保留瘦体重，蛋白建议提至 1.8-2.4 g/kg/天，"
                 "并配合阻力训练。优先来源：鸡胸、鱼、鸡蛋、低脂乳、豆腐。",
            source="ISSN + ACSM 减脂期建议",
            tags=("principle", "protein", "cut"),
        ),
        Document(
            id="principle:caloric_deficit",
            text="减脂的核心是热量赤字：每日建议赤字 300-500 kcal（约 10-20% 维持量），"
                 "周减 0.5-1% 体重最稳。极端低热量（<1200 女/<1500 男）会降低代谢、流失肌肉。",
            source="ACSM/AHA 减重指南",
            tags=("principle", "cut", "kcal"),
        ),
        Document(
            id="principle:fat_quality",
            text="脂肪不要妖魔化：总脂肪 20-35% 总能量。优先单不饱和（橄榄油/牛油果）+"
                 "Omega-3（鱼/亚麻籽），限反式脂肪 <1%，饱和脂肪 <10%。",
            source="WHO 营养指南",
            tags=("principle", "fat"),
        ),
        Document(
            id="principle:carb_quality",
            text="碳水关注质量优于总量：低 GI（<55）+ 高纤维 > 高 GI 精白主食。"
                 "运动前后小窗口可摄入快碳（香蕉/白米）补充糖原，平时主选糙米/全麦/燕麦。",
            source="GI 数据库 + 中国居民膳食指南",
            tags=("principle", "carb"),
        ),
        Document(
            id="principle:fiber_target",
            text="膳食纤维每日 25-30g（成人）。多数中国成年人摄入仅 13g，"
                 "建议每餐有蔬菜、每天 1-2 份水果、主食一半粗粮即可达标。",
            source="中国营养学会",
            tags=("principle", "fiber"),
        ),
        Document(
            id="principle:water",
            text="每日水分约 30-40 ml/kg 体重（含食物水分）。70kg 成年人约 2.1-2.8L，"
                 "运动每小时额外 400-800ml；高温/出汗多时可加少量电解质。",
            source="EFSA + ACSM",
            tags=("principle", "hydration"),
        ),
        Document(
            id="principle:meal_frequency",
            text="餐次频率（3 餐 vs 6 餐）对总减脂效果差别不大，关键看总热量与蛋白分布。"
                 "若有胃肠不适或加餐，每餐含 25-40g 蛋白即可。",
            source="多项 RCT meta 综述",
            tags=("principle", "frequency"),
        ),
        Document(
            id="principle:sodium",
            text="食盐每日 <5g（钠 <2g）。中国人均摄入约 9-10g，主要来源是酱油、调味料、加工肉。"
                 "高血压人群尤其需控盐。",
            source="WHO/中国居民膳食指南",
            tags=("principle", "sodium"),
        ),
        Document(
            id="principle:added_sugar",
            text="添加糖每日 <25g（更优 <50g 总）。含糖饮料是主要来源，"
                 "一瓶 500ml 可乐含糖 53g，超过日上限。",
            source="WHO 限糖指南",
            tags=("principle", "sugar"),
        ),
        Document(
            id="principle:post_workout_carb_protein",
            text="力量训练后 30-90 分钟内可摄入 20-40g 蛋白 + 0.5-1.0 g/kg 碳水，"
                 "促进肌糖原恢复与肌蛋白合成。常见组合：希腊酸奶+香蕉、鸡胸+米饭、蛋白粉+燕麦。",
            source="ISSN Nutrient Timing (2017)",
            tags=("principle", "post_workout", "protein", "carb"),
        ),
        Document(
            id="principle:vegetable_volume",
            text="蔬菜以体积替代部分碳水可显著降低餐后 GI 与总热量，"
                 "餐前先吃蔬菜与蛋白再吃主食可降低胰岛素波动，对控糖与减脂有益。",
            source="多项营养干预研究综述",
            tags=("principle", "vegetable", "blood_sugar"),
        ),
        Document(
            id="principle:cooking_oil",
            text="家庭烹饪每日用油建议 25-30g。常用油各有侧重：橄榄油（沙拉/低温）、"
                 "山茶/菜籽油（炒菜）、亚麻籽油（不加热）。煎炸损失 EPA/DHA。",
            source="中国居民膳食指南2022",
            tags=("principle", "fat", "cooking"),
        ),
        Document(
            id="principle:alcohol_kcal",
            text="酒精 7 kcal/g，仅次于脂肪。一杯 350ml 啤酒约 150 kcal，"
                 "且会抑制脂肪氧化与睡眠质量，减脂期建议每周 ≤2 个标准饮酒单位。",
            source="WHO + 多项睡眠研究",
            tags=("principle", "alcohol"),
        ),
        Document(
            id="principle:medical_redline",
            text="本应用提供的营养建议为一般教育性质，不是医学诊断。"
                 "如有糖尿病、肾脏疾病、孕期、术后恢复、严重过敏等情况，请咨询注册营养师或医生。",
            source="HealthCoachAgent 安全免责声明",
            tags=("safety", "disclaimer"),
        ),
    ]
