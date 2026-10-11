/**
 * 案例 02 端到端验证：周期性巡航任务编排新增「果园自动采摘任务」。
 *
 * 这个案例要验的正是「9 处改动是否都到位」——数据加了但映射没加，页面就会显示
 * 「未知类型」；下拉没加，编辑时选不到；total 没加，分页少一条。
 */
const { run, readTable, switchState } = require('../../scripts/e2e_common.cjs')

run({ path: '/task-scheduling/periodic-tasks', shot: 'e2e', waitMs: 3500 },
  async ({ page, ck }) => {
    console.log('\n=== 1. 列表数据 ===')
    const rows = await page.evaluate(() => {
      const t = document.querySelector('.el-table')
      if (!t) return []
      const heads = [...t.querySelectorAll('thead th')].map(th => th.innerText.trim())
      const body = [...t.querySelectorAll('tbody tr')].map(tr =>
        [...tr.querySelectorAll('td')].map(td => (td.innerText || '').trim()))
      return { heads, body, pages: document.body.innerText.match(/共\s*(\d+)\s*条/) }
    })
    console.log('  表头:', JSON.stringify(rows.heads))
    rows.body.forEach((r, i) => console.log('  行' + (i + 1) + ':', JSON.stringify(r)))

    const col = kw => rows.heads.findIndex(h => h.includes(kw))
    const cName = col('任务名称'), cType = col('任务类型'), cCycle = col('周期')
    const cDevice = col('设备'), cPrio = col('优先级'), cStatus = col('状态')
    console.log('  列索引:', JSON.stringify({ cName, cType, cCycle, cDevice, cPrio, cStatus }))

    ck('表格已渲染且有 4 行', rows.body.length === 4, rows.body.length + ' 行')

    const newRow = rows.body.find(r => r[cName] && r[cName].includes('果园自动采摘任务'))
    ck('找到新增行「果园自动采摘任务」', !!newRow, JSON.stringify(newRow))

    if (newRow) {
      ck('类型显示为「采摘任务」（而不是「未知类型」）',
        newRow[cType] === '采摘任务', newRow[cType])
      ck('周期为每天', /每天/.test(newRow[cCycle] || ''), newRow[cCycle])
      ck('设备数量为 1', /(^|\D)1(\D|$)/.test(newRow[cDevice] || ''), newRow[cDevice])
      ck('状态为等待中', (newRow[cStatus] || '').includes('等待中'), newRow[cStatus])
    }

    console.log('\n=== 2. 原有 3 条任务未被误伤 ===')
    const names = rows.body.map(r => r[cName])
    console.log('  任务名:', JSON.stringify(names))
    ck('原 3 条任务仍在',
      ['北区果园定时巡逻', '周末喷洒任务', '月度病虫害检查'].every(n => names.some(x => x && x.includes(n))))
    ck('无「未知类型」出现', !rows.body.some(r => (r[cType] || '').includes('未知类型')),
      rows.body.map(r => r[cType]).join(' | '))
    ck('文案统一为「果园」（未被旧副本回退成「农田」）',
      !(await page.evaluate(() => document.body.innerText)).includes('农田'))

    console.log('\n=== 3. 优先级（1 星）===')
    const rate = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.el-table tbody tr')]
      return rows.map(tr => {
        const r = tr.querySelector('.el-rate')
        if (!r) return null
        const item = r.querySelector('[aria-valuenow]')
        return item ? Number(item.getAttribute('aria-valuenow')) : null
      })
    })
    // 注意：el-rate 里有 decimal 占位元素，必须读 aria-valuenow，按 .el-rate__item 数会多算
    console.log('  各行星级:', JSON.stringify(rate))
    ck('新增行优先级 = 1 星', rate[names.findIndex(n => n && n.includes('果园自动采摘任务'))] === 1,
      String(rate[names.findIndex(n => n && n.includes('果园自动采摘任务'))]))

    console.log('\n=== 4. 「任务类型」下拉含「采摘任务」===')
    const editBtn = page.locator('.el-table tbody tr').last()
      .locator('button:has-text("编辑")').first()
    if (await editBtn.count() > 0) {
      await editBtn.click().catch(() => {})
      await page.waitForTimeout(1200)
      const opts = await page.evaluate(() => {
        const dlg = document.querySelector('.el-dialog, .el-drawer')
        if (!dlg) return []
        const sel = dlg.querySelector('.el-select')
        if (!sel) return []
        sel.querySelector('.el-select__wrapper, .el-input__wrapper')?.dispatchEvent(
          new MouseEvent('click', { bubbles: true }))
        return [...dlg.querySelectorAll('.el-select-dropdown__item')].map(o => o.innerText.trim())
      })
      console.log('  下拉选项:', JSON.stringify(opts))
      if (opts.length) ck('下拉含「采摘任务」', opts.includes('采摘任务'), opts.join(' | '))
      // 关掉弹窗
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(600)
    } else {
      console.log('  （未找到编辑按钮，跳过下拉检查）')
    }

    console.log('\n=== 5. 分页总数 ===')
    const total = await page.evaluate(() => {
      const m = document.body.innerText.match(/共\s*(\d+)\s*条/)
      return m ? Number(m[1]) : null
    })
    ck('分页总数为 4', total === 4, String(total))

    void readTable; void switchState
  })
