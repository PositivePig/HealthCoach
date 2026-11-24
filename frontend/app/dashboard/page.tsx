export default function DashboardPage() {
  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      <h1 className="text-2xl font-bold">📊 数据看板</h1>
      <p className="text-gray-500 text-sm">查看你的营养、运动、睡眠趋势</p>

      {/* Placeholder cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="border rounded-lg p-4">
          <h3 className="text-sm text-gray-500">今日热量</h3>
          <p className="text-2xl font-bold">-- kcal</p>
          <p className="text-xs text-gray-400">目标：1700 kcal</p>
        </div>
        <div className="border rounded-lg p-4">
          <h3 className="text-sm text-gray-500">蛋白质</h3>
          <p className="text-2xl font-bold">-- g</p>
          <p className="text-xs text-gray-400">目标：128 g</p>
        </div>
        <div className="border rounded-lg p-4">
          <h3 className="text-sm text-gray-500">运动时长</h3>
          <p className="text-2xl font-bold">-- min</p>
          <p className="text-xs text-gray-400">本周：-- min</p>
        </div>
      </div>

      {/* Placeholder charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="border rounded-lg p-4 h-64 flex items-center justify-center text-gray-400">
          📈 热量趋势图（即将上线）
        </div>
        <div className="border rounded-lg p-4 h-64 flex items-center justify-center text-gray-400">
          🏋️ 运动分布图（即将上线）
        </div>
        <div className="border rounded-lg p-4 h-64 flex items-center justify-center text-gray-400">
          😴 睡眠趋势图（即将上线）
        </div>
        <div className="border rounded-lg p-4 h-64 flex items-center justify-center text-gray-400">
          ❤️ 心率/HRV 图（即将上线）
        </div>
      </div>

      <p className="text-center text-sm text-gray-400">
        ⚠️ 数据看板需要后端 <code>/api/meals</code> 和 <code>/api/activities</code> 端点（W6 D5 待实现）
      </p>
    </div>
  );
}
