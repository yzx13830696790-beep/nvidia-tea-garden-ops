/**
 * 端到端脚本的公共骨架。
 *
 * 每个 case 的 e2e.js 只写"这个页面该显示什么"，不再重复样板：
 *   - 启动无头 Chrome（自动从 TG_CHROME 取路径）
 *   - 注入 localStorage token（该前端只检查有没有 token，不校验值）
 *   - 收集 pageerror 与 4xx/5xx
 *   - 统一的 [OK]/[FAIL] 计数与退出码
 *
 * 用法：
 *   const { run } = require('../../scripts/e2e_common.cjs')
 *   run({ path: '/task-scheduling/periodic-tasks' }, async ({ page, ck, stats }) => {
 *     ck('页面标题正确', (await page.title()).length > 0)
 *   })
 */
const path = require('path')

function loadPlaywright() {
  try {
    return require('playwright-core')
  } catch (e) {
    console.error('缺少 playwright-core。安装：')
    console.error('  npm i -g playwright-core   （或在本仓库 npm i playwright-core）')
    process.exit(64)
  }
}

/**
 * @param {{path?:string,url?:string,viewport?:{width:number,height:number},
 *          waitMs?:number,shot?:string,timeout?:number,initScript?:Function}} opts
 * @param {(ctx:{page,ck,browser,context,url,shot}) => Promise<void>} body
 */
async function run(opts, body) {
  const { chromium } = loadPlaywright()
  const BASE = process.env.TG_BASE_URL || 'http://127.0.0.1:8080'
  const URL_ = opts.url || (BASE + (opts.path || '/'))
  const SHOTS = process.env.TG_SHOT_DIR || __dirname
  const CHROME = process.env.TG_CHROME || undefined

  const browser = await chromium.launch({
    headless: true,
    ...(CHROME ? { executablePath: CHROME } : {}),
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  })
  const context = await browser.newContext({
    viewport: opts.viewport || { width: 1680, height: 1050 },
    timezoneId: 'Asia/Shanghai',
  })
  await context.addInitScript(opts.initScript || (() => {
    try { localStorage.setItem('token', 'd') } catch (e) {}
  }))

  const page = await context.newPage()
  const pageErrors = []
  const badResponses = []
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
  page.on('response', r => {
    const u = r.url()
    if (r.status() >= 400 && u.startsWith(BASE)) {
      badResponses.push(r.status() + ' ' + u.split('/').pop())
    }
  })

  let fail = 0
  const ck = (name, cond, extra) => {
    console.log((cond ? '  [OK]   ' : '  [FAIL] ') + name +
      (extra !== undefined ? '   ' + extra : ''))
    if (!cond) fail++
  }

  console.log('=== 打开 ' + URL_ + ' ===')
  await page.goto(URL_, { waitUntil: 'networkidle', timeout: opts.timeout || 45000 })
    .catch(() => {})
  await page.waitForTimeout(opts.waitMs || 3000)

  try {
    await body({ page, ck, browser, context, url: URL_, shot: SHOTS })
  } catch (e) {
    ck('脚本执行完成', false, String(e).slice(0, 300))
  }

  console.log('\n=== 页面错误 ===')
  ck('无 pageerror', pageErrors.length === 0, pageErrors.join(' || '))
  ck('无 4xx/5xx', badResponses.length === 0, badResponses.join(' || '))

  const shotPath = path.join(SHOTS, (opts.shot || 'e2e') + '.png')
  await page.screenshot({ path: shotPath, fullPage: true }).catch(() => {})
  console.log('  截图: ' + shotPath)

  console.log('\n' + (fail === 0
    ? '=========== 全部通过 ✓ ==========='
    : '=========== 失败 ' + fail + ' 项 ✗ ==========='))
  await browser.close()
  process.exit(fail === 0 ? 0 : 1)
}

/** 读取 Element Plus 表格：返回二维字符串数组。 */
async function readTable(page, selector) {
  return page.evaluate(sel => {
    const t = document.querySelector(sel)
    if (!t) return []
    return [...t.querySelectorAll('tbody tr')].map(tr =>
      [...tr.querySelectorAll('td')].map(td => (td.innerText || '').trim()))
  }, selector)
}

/** 读取 el-switch 的真实状态（aria-checked 在内部 .el-switch__input 上）。 */
async function switchState(root) {
  return root.evaluate(el => {
    const input = el.querySelector('.el-switch__input')
    return input ? input.getAttribute('aria-checked') : null
  })
}

module.exports = { run, readTable, switchState, BASE: process.env.TG_BASE_URL }
