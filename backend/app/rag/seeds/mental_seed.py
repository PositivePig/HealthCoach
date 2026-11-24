"""Seed mental health / wellbeing knowledge base.

Source attribution mostly drawn from:
  - APA (American Psychological Association) Guidelines
  - WHO Mental Health Atlas (2022)
  - Mayo Clinic: Stress management, Anxiety, Depression
  - NCBI/NIH: Sleep foundations, CBT techniques
  - Chinese Psychological Society: 心理健康指南

NOT a medical source. Always recommend professional help for clinical symptoms.

Tag taxonomy (used by mental_coach for filtered retrieval):
  - "principle" : general mental wellbeing principles
  - "coping"     : stress/anxiety coping techniques (CBT, mindfulness)
  - "sleep"      : sleep hygiene, insomnia management
  - "stress"     : work stress, time management, burnout prevention
  - "anxiety"    : anxiety symptoms, grounding techniques
  - "depression" : low mood, behavioral activation
  - "social"     : social support, communication skills
  - "redline"    : crisis keywords (self-harm, suicide ideation) → mandatory referral
  - "bridge"     : links between mental & physical health (for handoff to nutrition/fitness)
"""

from __future__ import annotations

from ..retriever import Document


def build_mental_corpus() -> list[Document]:
    return [
        # ---------- 大原则：心理健康基础 ----------
        Document(
            id="principle:mental_hygiene",
            text="心理健康维护需每日投入：保持规律睡眠（7-9小时）、"
                 "每周≥150分钟中等有氧、每日10分钟正念练习、维持社交连接。 "
                 "心理症状持续≥2周且影响功能时，建议咨询心理咨询师。",
            source="WHO Mental Health Atlas (2022) + APA Guidelines",
            tags=("principle", "sleep", "stress", "social"),
        ),
        Document(
            id="principle:cbt_basics",
            text="认知行为疗法（CBT）核心：识别负面自动思维 → 检验证据 → 生成平衡想法。 "
                 "常用技术：思维记录表、行为实验、暴露练习。 "
                 "轻度-中度焦虑/抑郁，CBT自助练习可显著改善症状（效应量d≈0.8）。",
            source="APA Clinical Practice Guideline (2023)",
            tags=("principle", "coping", "anxiety", "depression"),
        ),
        Document(
            id="principle:stress_dose",
            text="工作压力与表现呈倒U型曲线（Yerkes-Dodson定律）：适度压力提升表现，"
                 "过度压力导致 burnout。预警信号：持续疲劳、失眠、易怒、工作满意度下降。 "
                 "建议：任务拆解、设定边界、每日15分钟放松训练。",
            source="Mayo Clinic: Stress Management",
            tags=("principle", "stress", "burnout"),
        ),

        # ---------- 睡眠 ----------
        Document(
            id="sleep:hygiene",
            text="睡眠卫生核心准则：固定起床时间（含周末±1小时）、"
                 "睡前1小时避免蓝光（手机/电脑）、卧室温度18-22°C、"
                 "咖啡因截止下午2点、睡前3小时避免大餐/酒精。 "
                 "失眠CBT-I：刺激控制（床只用于睡眠）+ 睡眠限制（压缩在床时间提升至睡眠效率）。",
            source="American Academy of Sleep Medicine (AASM)",
            tags=("sleep", "hygiene", "cbt-i"),
        ),
        Document(
            id="sleep:duration",
            text="成人推荐睡眠7-9小时/晚。长期<6小时与免疫力下降30%、"
                 "焦虑风险升高25%、体重增加风险升高15%相关。 "
                 "质量>时长：深睡眠（N3期）占比15-25%为正常，REM睡眠占比20-25%。",
            source="NIH: National Sleep Foundation",
            tags=("sleep", "duration", "health"),
        ),
        Document(
            id="sleep:exercise_effect",
            text="规律有氧运动可缩短入睡潜伏期15-20分钟、提升深睡眠占比5-10%。 "
                 "但睡前3小时内高强度训练可能升高核心体温、延迟入睡。 "
                 "推荐：下午4-6点运动，睡前做温和拉伸/瑜伽。",
            source="Mayo Clinic: Exercise and Sleep",
            tags=("sleep", "exercise", "timing"),
        ),

        # ---------- 压力管理 ----------
        Document(
            id="stress:breathing_4-7-8",
            text="4-7-8呼吸法（Andrew Weil）：吸气4秒 → 屏息7秒 → 呼气8秒，"
                 "重复4-6轮。激活副交感神经，3分钟内降低心率10-15 bpm。 "
                 "适用于：考前紧张、公开演讲焦虑、失眠入睡困难。",
            source="Mayo Clinic: Stress Management Techniques",
            tags=("stress", "coping", "breathing"),
        ),
        Document(
            id="stress:time_management",
            text="时间管理四步法：1) 任务清单按重要性/紧急性分四象限；"
                 "2) 最重要的3件事优先完成（Eat That Frog）；"
                 "3) 番茄工作法（25分钟专注+5分钟休息）；"
                 "4) 每日结束时规划明日top3。 "
                 "避免多任务切换（注意力残留导致效率下降40%）。",
            source="APA: Work and Stress",
            tags=("stress", "time", "productivity"),
        ),
        Document(
            id="stress:burnout_prevention",
            text="职业倦怠三维度：情绪耗竭、去人格化、个人成就感降低。 "
                 "预防策略：设定工作边界（如19点后不回邮件）、"
                 "每工作90分钟休息10分钟、每周至少半天完全脱离工作、"
                 "建立同事支持网络。严重者建议EAP（员工援助计划）或心理咨询。",
            source='WHO: Burn-out an "occupational phenomenon" (2019)',
            tags=("stress", "burnout", "work"),
        ),

        # ---------- 焦虑应对 ----------
        Document(
            id="anxiety:grounding_5-4-3-2-1",
            text="5-4-3-2-1接地技术（急性焦虑/恐慌发作时）："
                 "说出5个看到的物体 → 4个触碰到的物体 → 3个听到的声音 → "
                 "2个闻到的气味 → 1个尝到的味道。 "
                 "原理：强制激活感官知觉，打断焦虑反刍循环。效果持续10-30分钟。",
            source="Mayo Clinic: Grounding Techniques",
            tags=("anxiety", "coping", "grounding", "panic"),
        ),
        Document(
            id="anxiety:progressive_muscle_relaxation",
            text="渐进式肌肉放松（PMR）：从脚趾开始，依次紧绷肌肉群5-10秒 → "
                 "突然放松，体验紧张-放松对比。全程20分钟，每日1-2次。 "
                 "可降低焦虑评分（GAD-7）3-5分，效果等同轻度镇静剂（无副作用）。",
            source="American Anxiety and Depression Association (ADAA)",
            tags=("anxiety", "coping", "pmr", "relaxation"),
        ),
        Document(
            id="anxiety:exercise_effect",
            text="规律有氧（每周3-5次，每次30-45分钟）可降低焦虑症状30-40%。 "
                 "机制：提升BDNF（脑源性神经营养因子）、降低皮质醇基线、"
                 "增加GABA（抑制性神经递质）。 "
                 "效果在运动后即刻至24小时内最明显（焦虑敏感者效果更显著）。",
            source="Harvard Health: Anxiety and Exercise",
            tags=("anxiety", "exercise", "neurobiology"),
        ),

        # ---------- 低情绪/抑郁 ----------
        Document(
            id="depression:behavioral_activation",
            text="行为激活（Behavioral Activation）：抑郁时动力下降，"
                 "但通过「计划→执行→奖励」循环可打破负反馈。 "
                 "步骤：1) 列出过去带来愉悦/成就感的活动；"
                 "2) 每天安排1-2个小活动（哪怕没心情也要做）；"
                 "3) 记录完成后的情绪变化。 "
                 "效应量d≈0.7，对中轻度抑郁效果显著。",
            source="APA Clinical Practice Guideline for Depression",
            tags=("depression", "coping", "behavioral_activation"),
        ),
        Document(
            id="depression:social_connection",
            text="社交隔离是抑郁的独立风险因素（风险比HR=1.5-2.0）。 "
                 "保护因素：每周≥2次面对面社交互动、加入兴趣社群、"
                 "养宠物（降低皮质醇、提升催产素）。 "
                 "注意：社交质量>数量，1-2个深度关系比20个点赞朋友更有保护力。",
            source="Harvard Study of Adult Development (85-year longitudinal)",
            tags=("depression", "social", "connection"),
        ),
        Document(
            id="depression:nutrition_link",
            text="营养与情绪存在双向关联："
                 "1) Omega-3脂肪酸（深海鱼、亚麻籽）可降低抑郁风险20-30%；"
                 "2) 地中海饮食模式（高果蔬、全谷物、橄榄油）与低抑郁评分相关；"
                 "3) 高糖饮食（≥50g/天添加糖）可能通过炎症反应升高抑郁风险。 "
                 "注意：营养干预为辅助，不能替代专业治疗。",
            source="WHO + Nutritional Neuroscience (2023 meta)",
            tags=("depression", "nutrition", "omega3", "bridge"),
        ),

        # ---------- 身心连接（bridge 知识）----------
        Document(
            id="bridge:exercise_mood",
            text="运动→情绪通路：急性运动（30分钟中等强度）即刻提升情绪，"
                 "效果持续2-6小时。长期（8-12周）规律运动等效于轻度抗抑郁药"
                 "（效应量d≈0.6）。推荐：快走、游泳、舞蹈（团体运动额外获得社交收益）。 "
                 "咨询健身教练制定可行计划，从每周2次、每次20分钟开始。",
            source="APA: Exercise and Mental Health",
            tags=("bridge", "exercise", "mood", "depression"),
        ),
        Document(
            id="bridge:nutrition_sleep",
            text="营养→睡眠质量：晚餐避免辛辣食物（可能延迟入睡30-60分钟）、"
                 "避免高脂大餐（消化负担影响深睡眠）、"
                 "可适量摄入色氨酸食物（牛奶、香蕉、燕麦）→ 促进褪黑素合成。 "
                 "睡前2小时避免大量饮水（减少夜尿次数）。 "
                 "营养师可帮助调整晚餐结构。",
            source="Sleep Medicine Reviews (2022)",
            tags=("bridge", "nutrition", "sleep", "diet"),
        ),
        Document(
            id="bridge:stress_eating",
            text="压力性进食（stress eating）：皮质醇升高导致对高糖高脂食物的渴望。 "
                 "应对策略：1) 识别情绪性饥饿（突然发生、渴望特定安慰食物）vs "
                 "生理性饥饿（逐渐发生、接受多种食物）；"
                 "2) 延迟10分钟再吃，做替代活动（散步、喝水）；"
                 "3) 提前准备健康零食（坚果、水果）。 "
                 "营养师可帮助制定低压力零食清单。",
            source="American Journal of Clinical Nutrition",
            tags=("bridge", "stress", "nutrition", "coping"),
        ),

        # ---------- 红线：危机干预 ----------
        Document(
            id="redline:self_harm",
            text="【红线】如果用户提到自伤行为（割腕、撞击、烧伤等）或自杀意念，"
                 "必须立即建议："
                 "1) 拨打危机干预热线：中国24小时心理援助热线 400-161-9995；"
                 "2) 告知可信赖的亲友或家人；"
                 "3) 前往最近医院急诊心理科。 "
                 "注意：不要承诺保密，确保安全是第一优先级。",
            source="Chinese Psychological Society: Crisis Intervention Guidelines",
            tags=("redline", "self_harm", "suicide", "crisis"),
        ),
        Document(
            id="redline:severe_depression",
            text="【红线】严重抑郁预警信号："
                 "1) 持续2周以上几乎每天大部分时间情绪低落或兴趣丧失；"
                 "2) 显著体重变化（1个月内±5%）、失眠或嗜睡、精神运动性激越或迟滞；"
                 "3) 疲劳、无价值感、注意力下降、反复想到死亡。 "
                 "符合5项以上且影响功能时，强烈建议前往精神科或心理咨询门诊评估。 "
                 "可提供：当地心理援助资源、三甲医院精神科列表。",
            source="DSM-5: Major Depressive Episode Criteria",
            tags=("redline", "depression", "clinical", "referral"),
        ),
        Document(
            id="redline:panic_attack",
            text="【红线】惊恐发作时（突发强烈恐惧+心悸/胸闷/窒息感/头晕，"
                 "通常10分钟内达峰），需排除心脏急症。 "
                 "首次发作建议：1) 急诊排除心梗/心律失常；"
                 "2) 确诊惊恐障碍后，CBT+药物（SSRI）联合治疗效果最佳。 "
                 "急性发作时：4-7-8呼吸法+接地技术可缓解，但需后续专业评估。",
            source="Mayo Clinic: Panic Disorder",
            tags=("redline", "anxiety", "panic", "medical_referral"),
        ),

        # ---------- 正念与冥想 ----------
        Document(
            id="coping:mindfulness_basics",
            text="正念（Mindfulness）定义：有意识地、不加评判地关注当下。 "
                 "入门练习：1) 正念呼吸（观察呼吸起伏，走神后温和拉回）；"
                 "2) 身体扫描（从脚趾到头顶，依次观察感受）；"
                 "3) 正念进食（慢慢吃，观察味道/质地）。 "
                 "每日10分钟，8周后焦虑评分平均降低4-6分（GAD-7）。",
            source="Jon Kabat-Zinn: MBSR (Mindfulness-Based Stress Reduction)",
            tags=("coping", "mindfulness", "meditation", "anxiety"),
        ),
        Document(
            id="coping:gratitude_journal",
            text="感恩日记：每天记录3件感恩的事（可大可小），"
                 "持续6周可提升主观幸福感评分15-20%（vs 对照组）。 "
                 "机制：训练大脑扫描正能量，对抗负面偏差（negativity bias）。 "
                 '建议：睡前写，具体描述（"今天同事帮我debug" vs "今天不错"）。',
            source="Greater Good Science Center (UC Berkeley)",
            tags=("coping", "gratitude", "positive_psychology"),
        ),
        Document(
            id="coping:social_support",
            text="社会支持缓冲压力的生物机制：倾诉降低皮质醇、提升催产素、"
                 "激活腹侧迷走神经（安全与连接感）。 "
                 "行动建议：1) 每周至少1次深度对话（>30分钟，非闲聊）；"
                 "2) 加入互助小组（减肥、戒烟、焦虑自助）；"
                 "3) 考虑宠物疗法（犬类可降低血压10-15 mmHg）。",
            source="APA: Stress and Social Support",
            tags=("coping", "social", "support", "biology"),
        ),

        # ---------- 工作-生活平衡 ----------
        Document(
            id="stress:work_life_balance",
            text="工作-生活平衡三原则："
                 "1) 物理边界（工作区 vs 休息区分离，远程工作尤为重要）；"
                 "2) 时间边界（固定下班时间，使用日历 blockers 保护个人时间）；"
                 '3) 心理边界（下班后不查邮件，练习"单任务"而非多线程）。 '
                 "每周至少半天完全脱离工作（no phone, no email）。",
            source="Harvard Business Review: Work-Life Balance",
            tags=("stress", "work", "boundary", "balance"),
        ),
        Document(
            id="stress:perfectionism",
            text="完美主义与焦虑/抑郁高度相关（r=0.4-0.6）。 "
                 '健康替代：从"完美完成"转向"足够好完成"（Good Enough Principle）。 '
                 "练习：设定时间盒（如30分钟完成PPT初稿），时间到必须交付，"
                 '接受"不完美但完成"优于"完美但拖延"。',
            source="APA: Perfectionism and Mental Health",
            tags=("stress", "coping", "perfectionism", "cognitive"),
        ),

        # ---------- 营养与心理（bridge）----------
        Document(
            id="bridge:gut_brain_axis",
            text="肠-脑轴（Gut-Brain Axis）：肠道菌群通过迷走神经、免疫、"
                 "神经递质（90%血清素在肠道合成）影响情绪。 "
                 "保护性饮食：高纤维（益生元，喂养有益菌）、发酵食品（酸奶、泡菜、康普茶）、"
                 "减少加工食品（可能破坏菌群多样性）。 "
                 "益生菌辅助改善焦虑症状（效应量d≈0.3-0.4，轻度但显著）。",
            source="Nature Reviews Gastroenterology & Hepatology (2023)",
            tags=("bridge", "nutrition", "gut", "microbiome", "anxiety"),
        ),
    ]
