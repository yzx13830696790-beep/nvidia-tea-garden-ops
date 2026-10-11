/**
 * 案例 01 端到端验证：车载运行数据流 —— 成功率区间 78~95。
 *
 * 静态检查和 HTTP 检查看不见的东西，只能靠真实浏览器：
 *   - 页面是不是真的渲染出了那三个统计值（Vue 数据结构和模板不匹配时会静默不渲染）
 *   - 点「刷新数据」是不是真的在区间内跳
 *   - 5 秒定时器跑 100 秒，会不会偶发越界、或者冻在某个值上
 */
const { run } = require('../../scripts/e2e_common.cjs')

const LO = 78, HI = 95

run({ path: '/device-management/picker-vehicle-data', shot: 'e2e', waitMs: 3500 },
  async ({ page, ck }) => {
    const readStats = () => page.evaluate(() => {
      const bars = [...document.querySelectorAll('.stats-bar')]
      const parse = el => {
        const l = el.querySelector('.stat-label'), v = el.querySelector('.stat-value')
        return l && v ? { label: l.innerText.trim(), value: v.innerText.trim() } : null
      }
      const first = bars.length
        ? [...bars[0].querySelectorAll('.stat-item')].map(parse).filter(Boolean) : []
      const cur = document.querySelector('.value-item .value-number')
      return { stats: first, current: cur ? cur.innerText.trim() : null, bars: bars.length }
    })
    const get = (a, kw) => { const it = a.find(x => x.label.includes(kw)); return it ? it.value : null }
    const num = v => { const n = parseFloat(v); return Number.isNaN(n) ? null : n }

    console.log('\n=== 1. 静态统计值 ===')
    const s0 = await readStats()
    console.log('  统计项 =', JSON.stringify(s0.stats))
    console.log('  当前成功率 =', s0.current)
    ck('最高成功率 = 95.0%', get(s0.stats, '最高') === '95.0%', get(s0.stats, '最高'))
    ck('最低成功率 = 78.0%', get(s0.stats, '最低') === '78.0%', get(s0.stats, '最低'))
    const avg0 = num(get(s0.stats, '平均'))
    ck('平均成功率在 [78,95]', avg0 !== null && avg0 >= LO && avg0 <= HI, get(s0.stats, '平均'))
    const cur0 = num(s0.current)
    ck('当前成功率在 [78,95]', cur0 !== null && cur0 >= LO && cur0 <= HI, s0.current)
    ck('折线图已渲染', await page.evaluate(() => !!document.querySelector('.chart-container canvas')))

    console.log('\n=== 2. 手动「刷新数据」x10 ===')
    const samples = []
    const btn = page.locator('button:has-text("刷新数据")').first()
    ck('找到刷新按钮', await btn.count() > 0)
    for (let i = 0; i < 10; i++) {
      await btn.click({ timeout: 5000 }).catch(() => {})
      await page.waitForTimeout(320)
      const v = num((await readStats()).current)
      samples.push(v)
      if (!(v >= LO && v <= HI)) ck('  第' + (i + 1) + '次刷新出界', false, v)
    }
    console.log('  10 次采样:', samples.join(', '))
    ck('手动刷新 10 次全部在区间内', samples.every(v => v >= LO && v <= HI))
    ck('手动刷新确实在变动', new Set(samples).size > 1, new Set(samples).size + ' 个不同值')
    const sAfter = await readStats()
    ck('刷新后极值仍是固定 95/78',
      get(sAfter.stats, '最高') === '95.0%' && get(sAfter.stats, '最低') === '78.0%')

    console.log('\n=== 3. 5 秒定时器观察 100 秒 ===')
    const auto = []
    for (let i = 0; i < 20; i++) {
      const st = await readStats()
      auto.push({ t: i * 5, cur: num(st.current), avg: num(get(st.stats, '平均')) })
      await page.waitForTimeout(5100)
    }
    console.log('  自动采样:', auto.map(a => a.t + 's:' + a.cur).join('  '))
    const aMin = Math.min(...auto.map(a => a.cur)), aMax = Math.max(...auto.map(a => a.cur))
    console.log('  观察区间: ' + aMin + ' ~ ' + aMax + '  (跨度 ' + (aMax - aMin).toFixed(1) + ')')
    ck('自动跳动不越界', aMin >= LO && aMax <= HI, 'min=' + aMin + ' max=' + aMax)
    ck('自动确实在变动', new Set(auto.map(a => a.cur)).size > 1)
    // 阈值 8 是先跑蒙特卡洛确认「20 步跨度 < 8」的概率极低才定下来的
    ck('自动跳动有可见幅度 (跨度>=8)', aMax - aMin >= 8, '跨度 ' + (aMax - aMin).toFixed(1))
    ck('平均成功率始终在区间内', auto.every(a => a.avg >= LO && a.avg <= HI))

    // 冻结检测：连续 4 个采样点（20 秒）完全相同 -> 疑似卡死（clamp 写法的典型症状）
    let freeze = 1, run_ = 1
    for (let i = 1; i < auto.length; i++) {
      if (auto[i].cur === auto[i - 1].cur) { run_++; freeze = Math.max(freeze, run_) } else run_ = 1
    }
    ck('没有冻结在某个值上（连续相同 < 4 点）', freeze < 4, '最长连续 ' + freeze + ' 点')

    const all = [...samples, ...auto.map(a => a.cur)]
    console.log('  全程 ' + all.length + ' 次采样: min=' + Math.min(...all).toFixed(1) +
      ' max=' + Math.max(...all).toFixed(1))
    ck('全程不越界', Math.min(...all) >= LO && Math.max(...all) <= HI)

    console.log('\n=== 4. 回归：同页另两块面板未被误伤 ===')
    const others = await page.evaluate(() => {
      const bars = [...document.querySelectorAll('.stats-bar')]
      const parse = el => {
        const l = el.querySelector('.stat-label'), v = el.querySelector('.stat-value')
        return l && v ? l.innerText.trim() + '=' + v.innerText.trim() : null
      }
      return bars.slice(1).map(b => [...b.querySelectorAll('.stat-item')].map(parse).filter(Boolean))
    })
    console.log('  车身姿态监测:', JSON.stringify(others[0]))
    console.log('  机械臂作业负载:', JSON.stringify(others[1]))
    ck('车身姿态标签未变', others[0] && others[0].every(x => /最大倾斜|最小倾斜|平均倾斜/.test(x)))
    ck('机械臂负载标签未变', others[1] && others[1].every(x => /最大负载|最小负载|平均负载/.test(x)))
    ck('车身姿态仍是动态区间 (<=25)',
      others[0] && parseFloat(others[0][0].split('=')[1]) <= 25, others[0] && others[0][0])
    ck('机械臂负载仍是动态区间 (<=90)',
      others[1] && parseFloat(others[1][0].split('=')[1]) <= 90, others[1] && others[1][0])
  })
