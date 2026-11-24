export default function NotificationsPage() {
  const notifications = [
    {
      id: "1",
      title: "📊 每日健康日报",
      body: "今天摄入 1650 kcal，蛋白质 120g，达标！运动 45 分钟。",
      time: "昨晚 22:00",
      read: false,
    },
    {
      id: "2",
      title: "⚠️ 蛋白质摄入提醒",
      body: "最近 3 天蛋白质摄入不足，建议增加鸡蛋、鸡胸肉等食物。",
      time: "今天 08:30",
      read: false,
    },
    {
      id: "3",
      title: "✅ 睡眠目标达成",
      body: "昨晚睡眠 7.5 小时，超过目标！继续保持。",
      time: "今天 07:00",
      read: true,
    },
  ];

  return (
    <div className="max-w-2xl mx-auto p-4 space-y-4">
      <h1 className="text-2xl font-bold">🔔 推送中心</h1>
      <p className="text-sm text-gray-500">Agent 主动消息将在这里显示</p>

      <div className="space-y-3">
        {notifications.map((n) => (
          <div
            key={n.id}
            className={`border rounded-lg p-4 ${n.read ? "bg-white" : "bg-blue-50 border-blue-200"}`}
          >
            <div className="flex justify-between items-start">
              <h3 className={`font-semibold ${n.read ? "text-gray-700" : "text-gray-900"}`}>
                {n.title}
              </h3>
              {!n.read && (
                <span className="w-2 h-2 bg-blue-500 rounded-full flex-shrink-0 mt-1" />
              )}
            </div>
            <p className="text-sm text-gray-600 mt-1">{n.body}</p>
            <p className="text-xs text-gray-400 mt-2">{n.time}</p>
          </div>
        ))}
      </div>

      <p className="text-center text-sm text-gray-400 mt-8">
        ⚠️ 推送功能需要后端 <code>/api/proactive/notifications</code> 端点（W6 D6 待实现）
      </p>
    </div>
  );
}
