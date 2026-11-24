export default function ActivityPage() {
  return (
    <div className="max-w-2xl mx-auto p-4 space-y-4">
      <h1 className="text-2xl font-bold">🏋️ 运动记录</h1>
      <p className="text-sm text-gray-500">记录你的运动，教练给你建议</p>

      <div className="border rounded-lg p-4 space-y-3">
        <div>
          <label className="text-sm font-medium">运动类型</label>
          <select className="w-full mt-1 px-3 py-2 border rounded-lg">
            <option>跑步</option>
            <option>力量训练</option>
            <option>游泳</option>
            <option>骑行</option>
            <option>瑜伽</option>
            <option>步行</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-sm font-medium">时长（分钟）</label>
            <input type="number" defaultValue="30" className="w-full mt-1 px-3 py-2 border rounded-lg" />
          </div>
          <div>
            <label className="text-sm font-medium">消耗（kcal）</label>
            <input type="number" defaultValue="" placeholder="可选" className="w-full mt-1 px-3 py-2 border rounded-lg" />
          </div>
        </div>
        <div>
          <label className="text-sm font-medium">备注</label>
          <input type="text" placeholder="例如：配速 5:30" className="w-full mt-1 px-3 py-2 border rounded-lg" />
        </div>
        <button className="w-full py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600">
          记录运动
        </button>
      </div>

      <div className="border rounded-lg p-4">
        <h3 className="font-semibold mb-2">最近运动</h3>
        <p className="text-sm text-gray-400 text-center py-8">暂无记录</p>
      </div>

      <p className="text-center text-sm text-gray-400">
        ⚠️ 运动记录需要后端 <code>/api/activities</code> 端点（待实现）
      </p>
    </div>
  );
}
