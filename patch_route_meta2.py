from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent / "frontend" / "TYXT_UI.html"

JS_PATCH = """
function renderGroupRouteMeta(routeInfo) {
  var bar = document.getElementById('groupRouteMetaBar');
  if (!bar) return;
  if (!routeInfo || !routeInfo.steps || routeInfo.steps.length === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  var parts = [];
  parts.push('<span class="rmb-label">路由</span>');
  routeInfo.steps.forEach(function(step, idx) {
    if (idx > 0) parts.push('<span class="rmb-arrow">&#x203A;</span>');
    var name = step.agent_name || step.agent_id || ('步骤' + (idx+1));
    var role = step.role ? (' <span class="rmb-tag">' + step.role + '</span>') : '';
    parts.push('<span>' + name + role + '</span>');
  });
  if (routeInfo.strategy) {
    parts.push('<span class="rmb-tag" style="margin-left:auto">' + routeInfo.strategy + '</span>');
  }
  bar.innerHTML = parts.join('');
}
"""

with open(HTML_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

if 'renderGroupRouteMeta' in content:
    print('[JS] 已存在，跳过')
else:
    idx = content.rfind('</script>')
    if idx == -1:
        print('[JS] 未找到 </script> 锚点，FAIL')
    else:
        content = content[:idx] + JS_PATCH + '\n</script>' + content[idx+9:]
        print('[JS] 注入成功')

with open(HTML_PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print('[WRITE] 写入完成')

with open(HTML_PATH, 'r', encoding='utf-8') as f:
    verify = f.read()

css_count = verify.count('group-route-meta-bar')
js_count = verify.count('renderGroupRouteMeta')
print(f'[VERIFY] group-route-meta-bar count = {css_count}')
print(f'[VERIFY] renderGroupRouteMeta count = {js_count}')

if css_count > 0 and js_count > 0:
    print('[RESULT] PASS - 两项均已写入磁盘')
else:
    print('[RESULT] FAIL - 有项未写入，请检查')
