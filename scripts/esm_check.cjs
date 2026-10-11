// ESM 语法校验器。
//
// 补丁后的 chunk 必须能被 JS 引擎当作 ES Module 解析通过——压缩产物一旦括号切错，
// 浏览器会整页白屏，而 HTTP 层完全看不出问题（文件 200、大小正常）。
//
// 用法：
//   node --experimental-vm-modules scripts/esm_check.cjs <file...>
//   node --experimental-vm-modules scripts/esm_check.cjs --eval "<表达式>" "期望值"
//
// 退出码 0 = 全部通过；1 = 有文件语法失败；2 = 有求值结果不符。

const vm = require('vm')
const fs = require('fs')

const argv = process.argv.slice(2)

function fail(msg) {
  console.log(msg)
  process.exitCode = 1
}

// --eval 模式：把一段表达式放进沙箱真求值，用于验证「数组长度 / 常量值」这类
// 光看文本看不出来的东西。压缩产物里的表达式往往无法整体执行，但局部片段可以。
if (argv[0] === '--eval') {
  const expr = argv[1]
  const want = argv[2]
  try {
    const got = vm.runInNewContext(expr, {}, { timeout: 2000 })
    const s = JSON.stringify(got)
    const ok = want === undefined || s === want
    console.log(`[${ok ? 'OK' : 'FAIL'}] eval -> ${s}${want !== undefined ? '  (期望 ' + want + ')' : ''}`)
    process.exit(ok ? 0 : 2)
  } catch (e) {
    console.log(`[FAIL] eval 抛异常: ${e.message}`)
    process.exit(2)
  }
}

if (argv.length === 0) {
  console.log('用法: node --experimental-vm-modules scripts/esm_check.cjs <file...>')
  process.exit(64)
}

let bad = 0
for (const f of argv) {
  const src = fs.readFileSync(f, 'utf8')
  try {
    // 只要求「可解析」，不求值——求值会触发 import、DOM、副作用。
    new vm.SourceTextModule(src, { identifier: f })
    console.log(`OK   ${f}  (${src.length} chars)`)
  } catch (e) {
    bad++
    console.log(`FAIL ${f}`)
    console.log('     ' + e.message)
    if (e.lineNumber != null && e.columnNumber != null) {
      const lines = src.split('\n')
      const ln = lines[e.lineNumber - 1] || ''
      const col = e.columnNumber
      console.log(`     line ${e.lineNumber} col ${col}`)
      console.log('     ...' + ln.slice(Math.max(0, col - 120), col + 120) + '...')
    }
  }
}
process.exit(bad ? 1 : 0)
