"""Seed fitness / training knowledge base.

Source attribution mostly drawn from:
  - ACSM Guidelines for Exercise Testing and Prescription (11th ed.)
  - ISSN Position Stands (Protein, Nutrient Timing, Caffeine, Creatine)
  - WHO Guidelines on Physical Activity and Sedentary Behaviour (2020)
  - NSCA Essentials of Strength Training and Conditioning (4th ed.)

NOT a medical source. Numbers are educational approximations.

Tag taxonomy (used by fitness_coach for filtered retrieval):
  - "principle"  : general training principles / dose-response
  - "exercise"   : specific movement notes (form, regression, common errors)
  - "recovery"   : sleep, soreness, injury, rest
  - "cardio"     : aerobic / endurance
  - "strength"   : resistance / hypertrophy / power
  - "mobility"   : flexibility, joint health
  - "safety"     : red lines (chest pain, dizziness, doctor referral)
"""

from __future__ import annotations

from ..retriever import Document


def build_fitness_corpus() -> list[Document]:
    return [
        # ---------- 大原则：剂量-反应 ----------
        Document(
            id="principle:who_aerobic_dose",
            text="WHO 成人每周建议中等强度有氧 150-300 分钟 或 高强度 75-150 分钟，"
                 "或两者等效组合；并每周 ≥2 次涉及主要肌群的力量训练。",
            source="WHO Physical Activity Guidelines (2020)",
            tags=("principle", "cardio", "strength", "dose"),
        ),
        Document(
            id="principle:progressive_overload",
            text="渐进负荷是肌肉/力量增长核心：每 1-2 周通过增加重量(2-5%)、组数、"
                 "次数、缩短组间或改善动作质量之一来推进。一次只升一个变量更稳。",
            source="NSCA Essentials of Strength Training & Conditioning",
            tags=("principle", "strength", "hypertrophy"),
        ),
        Document(
            id="principle:hypertrophy_volume",
            text="肌肥大每个肌群每周 10-20 个有效组（reps 6-30，距离力竭 0-3 RIR）"
                 "效果较稳；超过 20 组收益边际递减且恢复需求骤增。",
            source="Schoenfeld et al. meta-analyses (2017-2022)",
            tags=("principle", "strength", "hypertrophy", "volume"),
        ),
        Document(
            id="principle:strength_intensity",
            text="纯力量目标：1-5 RM（85-100% 1RM），组数 3-6，组间 2-5 分钟。"
                 "肌肥大目标：6-12 RM（67-85%），组间 1-3 分钟。耐力：>15 RM。",
            source="ACSM/NSCA 训练目标对照",
            tags=("principle", "strength", "intensity"),
        ),
        Document(
            id="principle:cardio_zones",
            text="心率分区（max HR ≈ 220-年龄，仅估算）：Z2 60-70% 燃脂/有氧基础，"
                 "Z3 70-80% 节奏跑，Z4 80-90% 阈值，Z5 90-100% VO2max 间歇。"
                 "建议 80% Z2/20% Z4-5 的极化训练分布。",
            source="ACSM + Seiler 极化训练研究",
            tags=("principle", "cardio", "hr", "zones"),
        ),
        Document(
            id="principle:hiit_safety",
            text="HIIT（4x4、Tabata）能在更短时间内提升 VO2max，但对心血管负担大；"
                 "新手或久坐者应先建立 4-6 周 Z2 基础再做 HIIT，每周 ≤2 次为宜。",
            source="多项 HIIT vs MICT meta 综述",
            tags=("principle", "cardio", "hiit", "safety"),
        ),
        Document(
            id="principle:running_10pct",
            text="跑步加量遵循 10% 法则：周里程涨幅不超过上一周 10%，"
                 "连续 3 周加量后第 4 周减量 30-40% 作为减量周，可显著降低跑步伤病率。",
            source="跑步医学研究综述",
            tags=("principle", "cardio", "running", "load"),
        ),
        Document(
            id="principle:warmup_cooldown",
            text="训练前热身 5-10 分钟动态拉伸 + 渐进性低强度热身组（50-70% 工作重量），"
                 "训练后 5 分钟低强度有氧 + 静态拉伸 30-60 秒/部位。"
                 "训练前不要做长时间静态拉伸（会短暂降低力量输出 5-10%）。",
            source="ACSM + 多项静态拉伸 RCT",
            tags=("principle", "warmup", "mobility"),
        ),

        # ---------- 具体动作 ----------
        Document(
            id="exercise:squat",
            text="深蹲（杠铃/哑铃/自重）：膝盖大致跟随脚尖方向，下蹲到大腿与地面平行或更深，"
                 "保持中段紧绷与中立脊柱。常见错误：膝内扣、屈髋不足、骨盆后倾(butt wink)。"
                 "新手推荐高脚杯深蹲(Goblet Squat)起步。",
            source="NSCA + Starting Strength",
            tags=("exercise", "strength", "leg", "squat"),
        ),
        Document(
            id="exercise:deadlift",
            text="硬拉：髋部主导，杠铃贴腿，肩胛打包，离地瞬间髋膝同步发力。"
                 "新手优先六角杠或罗马尼亚硬拉(RDL)；下背部僵硬或腰椎不适者避免传统硬拉。"
                 "每周硬拉量不宜过高，恢复成本最大。",
            source="NSCA",
            tags=("exercise", "strength", "back", "hip", "deadlift"),
        ),
        Document(
            id="exercise:bench_press",
            text="卧推：肩胛后缩下沉，脚踩地稳定，杠铃下放至胸骨中下部，肘部约 45-75° 张角。"
                 "肩前侧/旋袖不适者可换上斜哑铃推举或地板推。",
            source="NSCA",
            tags=("exercise", "strength", "chest", "push"),
        ),
        Document(
            id="exercise:pullup_row",
            text="引体向上/划船：拉类训练能平衡推类肌群、改善圆肩。引体不能完成时可用："
                 "坐姿下拉、辅助引体带、反向划船(inverted row)、单臂哑铃划船循序渐进。",
            source="NSCA + 物理治疗推/拉对比",
            tags=("exercise", "strength", "back", "pull"),
        ),
        Document(
            id="exercise:plank",
            text="平板支撑：肘在肩正下方，臀腹同时收紧使身体一条直线，"
                 "颈部中立。30-60s × 3 组优于硬撑 3 分钟松散版本。"
                 "进阶：侧平板、Dead Bug、Bird Dog 等抗旋核心训练。",
            source="ACSM 核心训练建议",
            tags=("exercise", "core"),
        ),
        Document(
            id="exercise:running_form",
            text="跑步姿态：上身前倾（踝至肩呈一直线），步频 170-180 spm，"
                 "中前足着地于身体重心正下方，避免大跨步落跟前冲产生制动力。"
                 "提高步频是降低落地冲击与膝伤的最低成本干预之一。",
            source="跑步生物力学综述",
            tags=("exercise", "cardio", "running"),
        ),
        Document(
            id="exercise:cycling_basics",
            text="骑行：座垫高度使踩到底时膝盖微屈 25-30°，膝盖正对脚尖；"
                 "核心稳定避免骨盆左右晃动。室内功率骑行更易完成 Z2 长时间训练。",
            source="ACSM",
            tags=("exercise", "cardio", "cycling"),
        ),
        Document(
            id="exercise:swimming",
            text="游泳是低冲击全身有氧。蛙泳膝伤者改自由泳；"
                 "新手 30 分钟连续游通常能消耗 250-400 kcal（与体重和强度强相关）。",
            source="ACSM 能量消耗表",
            tags=("exercise", "cardio", "swim", "low_impact"),
        ),

        # ---------- 恢复 / 伤病 / 安全 ----------
        Document(
            id="recovery:sleep",
            text="睡眠每晚 7-9 小时是力量与恢复的基础。睡眠 <6h 一周即可降低肌肉合成速率 18%、"
                 "提升受伤率约 1.7 倍。优先固定就寝时间而非补眠。",
            source="多项睡眠 vs 运动表现研究",
            tags=("recovery", "sleep"),
        ),
        Document(
            id="recovery:doms",
            text="延迟性肌肉酸痛(DOMS) 通常 24-72h 达峰，无需停训：可对该肌群做"
                 "低强度血流促进训练(50% 重量×高次数)。冰敷对长期适应可能略有抑制，"
                 "更推荐主动恢复 + 充足蛋白与睡眠。",
            source="多项 DOMS 综述 + ISSN",
            tags=("recovery", "doms", "soreness"),
        ),
        Document(
            id="recovery:overtraining_signs",
            text="过度训练预警信号：晨起静息心率连续 3 天高于基线 5+ bpm、HRV 持续下降、"
                 "睡眠变差、情绪低落、训练表现退步。出现 ≥3 项应主动减量 30-50% 至少 1 周。",
            source="ACSM 过度训练综合征指南",
            tags=("recovery", "overtraining", "hrv"),
        ),
        Document(
            id="recovery:rice_to_peace_love",
            text="软组织急性损伤已不再推荐冰敷+长时间制动；现代建议 PEACE & LOVE："
                 "前 72h Protect/Elevate/Avoid antiinflammatory/Compression/Education，"
                 "之后 Load/Optimism/Vascularisation/Exercise 渐进负荷。",
            source="BJSM 2019 共识",
            tags=("recovery", "injury"),
        ),
        Document(
            id="recovery:knee_pain",
            text="膝前痛(髌股综合征 PFPS)常见诱因：股四/臀中力量不足、跑量陡增、"
                 "扁平足。处理：减量 30-50%、强化臀中(蚌式/侧抬腿)、避免深蹲超过疼痛角度。"
                 "持续 >2 周或上下楼疼痛明显应就医。",
            source="物理治疗 PFPS 指南",
            tags=("recovery", "knee", "injury"),
        ),
        Document(
            id="recovery:lower_back",
            text="非特异性下背痛常与久坐、髋屈紧、核心薄弱相关。急性期 48h 内避免"
                 "深屈膝硬拉/弓腰深蹲；以髋铰链(Hip Hinge)、Bird Dog、死虫式恢复模式。"
                 "出现下肢放射痛、麻木、大小便失禁需立即就医。",
            source="NSCA + 物理治疗共识",
            tags=("recovery", "back", "injury"),
        ),
        Document(
            id="recovery:rest_day",
            text="完全休息日 ≥1/周；进阶训练者 3-on-1-off 或 2-on-1-off。"
                 "积极恢复(走路/瑜伽/30 分钟 Z1 骑行)优于完全静卧，可加速恢复。",
            source="ACSM",
            tags=("recovery", "rest"),
        ),
        Document(
            id="safety:chest_pain_red_flag",
            text="运动中或后出现胸痛、胸闷、压榨感、左肩/下颌放射痛、晕厥、严重气短，"
                 "应立即停止训练并就医，疑似心血管事件。已知心血管疾病者运动前应医学评估。",
            source="AHA/ACSM 运动前筛查",
            tags=("safety", "redline"),
        ),
        Document(
            id="safety:dizzy_dehydration",
            text="头晕、恶心、肌肉抽搐多与脱水/电解质紊乱/低血糖有关。立即停训、"
                 "阴凉处补水(含电解质 + 适量糖)、监测症状。30 分钟未缓解或意识改变需就医。",
            source="ACSM 高温运动指南",
            tags=("safety", "redline", "hydration"),
        ),

        # ---------- 训练计划模板 ----------
        Document(
            id="plan:beginner_3day_full",
            text="新手 3 天/周全身：A 日 深蹲 3x8 + 卧推 3x8 + 划船 3x10 + 平板 3x40s；"
                 "B 日 RDL 3x8 + 推举 3x8 + 引体/下拉 3x8 + 死虫 3x10；"
                 "A/B 交替，间隔 1 天恢复。每 4 周加 5% 重量或一组。",
            source="NSCA 新手计划范例",
            tags=("plan", "strength", "beginner"),
        ),
        Document(
            id="plan:fat_loss_split",
            text="减脂期常用组合：每周 3 次抗阻(全身或推/拉/腿) + 2-3 次 Z2 有氧(40-60 分钟)"
                 "+ 1 次 HIIT(<25 分钟) + 每日 8000+ 步。蛋白 1.8-2.2 g/kg 维持瘦体重。",
            source="ACSM/ISSN 减脂综合方案",
            tags=("plan", "cardio", "strength", "cut"),
        ),
        Document(
            id="plan:hypertrophy_ppl",
            text="增肌 PPL 6 天分化：Push(胸肩三头) / Pull(背二头) / Legs，每个肌群 12-18 组/周。"
                 "若恢复跟不上(睡眠差/酸痛长)应回到 4-5 天分化。",
            source="多项肌肥大计划综述",
            tags=("plan", "strength", "hypertrophy"),
        ),
        Document(
            id="plan:5k_beginner",
            text="0-5K 8 周计划：每周 3 次，跑/走交替起步(跑 1' 走 2' x 8)，"
                 "每周延长跑段 30-60s，第 8 周连续跑 30 分钟约 5K。配合 1 次力量训练。",
            source="跑步入门通用方案",
            tags=("plan", "cardio", "running", "beginner"),
        ),

        # ---------- 营养-训练接口（供 fitness 反向 handoff 给 nutrition 引用）----------
        Document(
            id="bridge:fuel_pre_workout",
            text="训练前 1-2 小时摄入 0.5-1.0 g/kg 易消化碳水 + 10-20g 蛋白(可选)，"
                 "如燕麦+蛋白粉、香蕉+希腊酸奶、米饭+鸡胸。空腹有氧适用 Z2 短时段，"
                 "高强度建议补糖以维持表现。",
            source="ISSN Nutrient Timing",
            tags=("bridge", "nutrition", "pre_workout"),
        ),
        Document(
            id="bridge:hydration_intra",
            text="训练中每 15-20 分钟补水 150-250 ml；超过 60 分钟或大量出汗时"
                 "每升水加 0.3-0.7g 钠 + 30-60g 碳水以维持配速。",
            source="ACSM Hydration Position Stand",
            tags=("bridge", "nutrition", "hydration"),
        ),
    ]
